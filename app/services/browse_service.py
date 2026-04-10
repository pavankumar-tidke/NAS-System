"""
Path-based browsing, folders, move/copy/rename under storage/{user_id}/...
"""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path
from typing import Any, Literal

from bson import ObjectId
from fastapi import HTTPException, status

from app.core.config import get_settings
from app.core.utils import utc_now
from app.db.mongo import get_db
from app.models.file import FilePublic, FileType
from app.models.user import Role
from app.services import file_service as fs_mod
from app.services.file_service import file_doc_to_public, _list_filter_query


def _join_under(root: Path, rel: str) -> Path:
    """Join slash-separated `rel` under `root` (pathlib; works on all platforms)."""
    if not rel:
        return root
    parts = [p for p in rel.replace("\\", "/").split("/") if p and p != "."]
    return root.joinpath(*parts) if parts else root


def _user_root(user_id: str) -> Path:
    settings = get_settings()
    return (settings.storage_path / "storage" / user_id).resolve()


def normalize_rel_path(raw: str | None) -> str:
    """Return safe relative path (no .., no absolute). Empty string = root."""
    if not raw or not raw.strip():
        return ""
    parts: list[str] = []
    for p in raw.replace("\\", "/").strip("/").split("/"):
        p = p.strip()
        if not p or p == ".":
            continue
        if p == "..":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid path")
        if "/" in p or "\\" in p:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid path segment")
        parts.append(p)
    return "/".join(parts)


def _ensure_under_user(base: Path, target: Path) -> Path:
    try:
        resolved = target.resolve()
        resolved.relative_to(base)
        return resolved
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path escapes user storage") from exc


def ensure_user_tree(user_id: str) -> Path:
    root = _user_root(user_id)
    root.mkdir(parents=True, exist_ok=True)
    (root / "files").mkdir(parents=True, exist_ok=True)
    return root


def _direct_children_filepath_regex(user_id: str, rel_path: str) -> str:
    """Regex for Mongo: files directly inside rel_path (one filename segment after prefix)."""
    prefix = f"storage/{user_id}/{rel_path}/" if rel_path else f"storage/{user_id}/"
    return f"^{re.escape(prefix)}[^/]+$"


async def list_browse(
    *,
    user_id: str,
    actor_id: str,
    role: Role,
    owner_id: str | None,
    rel_path: str,
    limit: int,
    offset: int,
    sort: Literal["newest", "oldest"],
    search: str | None,
    type_filter: FileType | None,
) -> tuple[list[FilePublic], list[dict[str, str]], int]:
    """
    List subfolders + file rows for the given relative path under storage/{user_id}/.
    """
    ensure_user_tree(user_id)
    root = _user_root(user_id)
    base = _ensure_under_user(root, _join_under(root, rel_path))

    folders: list[dict[str, str]] = []
    if base.is_dir():
        try:
            for child in sorted(base.iterdir()):
                if child.is_dir() and not child.name.startswith("."):
                    sub = f"{rel_path}/{child.name}" if rel_path else child.name
                    folders.append({"name": child.name, "path": sub})
        except OSError:
            pass

    db = get_db()
    owner_filter = owner_id if role == Role.admin and owner_id else None
    base_q = _list_filter_query(
        actor_id=actor_id,
        role=role,
        owner_id=owner_filter,
        search=search,
        type_filter=type_filter,
    )
    path_q = {"filepath": {"$regex": _direct_children_filepath_regex(user_id, rel_path)}}
    filters: list[dict[str, Any]] = [path_q, {"user_id": user_id}]
    if base_q:
        filters.insert(0, base_q)
    query = {"$and": filters}

    direction = -1 if sort == "newest" else 1
    cursor = db.files.find(query).sort("created_at", direction).skip(offset).limit(limit)
    items: list[FilePublic] = []
    async for doc in cursor:
        items.append(file_doc_to_public(doc))

    total = await db.files.count_documents(query)
    return items, folders, total


async def create_folder(*, user_id: str, parent_path: str, name: str) -> dict[str, str]:
    """Create a directory under storage/{user_id}/{parent_path}/{name}."""
    parent_path = normalize_rel_path(parent_path)
    safe_name = Path(name.strip()).name
    if not safe_name or safe_name in (".", "..") or "/" in name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid folder name")
    ensure_user_tree(user_id)
    root = _user_root(user_id)
    dest = _ensure_under_user(root, _join_under(root, parent_path) / safe_name)
    if dest.exists():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Folder already exists")
    dest.mkdir(parents=True, exist_ok=True)
    keep = dest / ".nas_keep"
    try:
        keep.write_text("")
    except OSError:
        pass
    rel = f"{parent_path}/{safe_name}" if parent_path else safe_name
    return {"name": safe_name, "path": rel}


def _folder_tree_nodes(path: Path, rel: str, max_depth: int, depth: int) -> dict[str, Any] | None:
    if depth > max_depth or not path.is_dir():
        return None
    children: list[dict[str, Any]] = []
    try:
        for child in sorted(path.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            sub_rel = f"{rel}/{child.name}" if rel else child.name
            node = _folder_tree_nodes(child, sub_rel, max_depth, depth + 1)
            children.append(
                {
                    "name": child.name,
                    "path": sub_rel,
                    "children": node["children"] if node else [],
                }
            )
    except OSError:
        pass
    return {"name": Path(rel).name if rel else "", "path": rel, "children": children}


async def get_folder_tree(*, user_id: str, max_depth: int = 8) -> dict[str, Any]:
    ensure_user_tree(user_id)
    root = _user_root(user_id) / "files"
    root.mkdir(parents=True, exist_ok=True)
    children: list[dict[str, Any]] = []
    try:
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            sub = _folder_tree_nodes(child, child.name, max_depth, 1)
            if sub:
                children.append(sub)
    except OSError:
        pass
    return {"name": "files", "path": "files", "children": children}


async def move_files(
    *,
    user_id: str,
    actor_id: str,
    role: Role,
    file_ids: list[str],
    target_path: str,
) -> int:
    target_path = normalize_rel_path(target_path)
    ensure_user_tree(user_id)
    root = _user_root(user_id)
    dest_dir = _ensure_under_user(root, _join_under(root, target_path))
    dest_dir.mkdir(parents=True, exist_ok=True)

    db = get_db()
    moved = 0
    for fid in file_ids:
        try:
            oid = ObjectId(fid)
        except Exception:  # noqa: BLE001
            continue
        doc = await db.files.find_one({"_id": oid})
        if not doc or str(doc["user_id"]) != user_id:
            continue
        if role == Role.member and str(doc["user_id"]) != actor_id:
            continue
        old_rel = doc["filepath"]
        old_abs = (get_settings().storage_path / old_rel).resolve()
        if not fs_mod.verify_path_under_storage(old_abs):
            continue
        fname = Path(old_rel).name
        new_rel_path = f"storage/{user_id}/{target_path}/{fname}"
        new_abs = (get_settings().storage_path / new_rel_path).resolve()
        if not fs_mod.verify_path_under_storage(new_abs):
            continue
        if new_abs.exists():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Target exists: {fname}")
        try:
            shutil.move(str(old_abs), str(new_abs))
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Move failed: {exc}",
            ) from exc
        await db.files.update_one(
            {"_id": oid},
            {"$set": {"filepath": new_rel_path, "updated_at": utc_now()}},
        )
        moved += 1
    return moved


async def copy_file(
    *,
    user_id: str,
    actor_id: str,
    role: Role,
    file_id: str,
    target_path: str,
) -> FilePublic | None:
    target_path = normalize_rel_path(target_path)
    ensure_user_tree(user_id)
    root = _user_root(user_id)
    dest_dir = _ensure_under_user(root, _join_under(root, target_path))
    dest_dir.mkdir(parents=True, exist_ok=True)

    db = get_db()
    try:
        oid = ObjectId(file_id)
    except Exception:  # noqa: BLE001
        return None
    doc = await db.files.find_one({"_id": oid})
    if not doc or str(doc["user_id"]) != user_id:
        return None
    if role == Role.member and str(doc["user_id"]) != actor_id:
        return None

    old_abs = (get_settings().storage_path / doc["filepath"]).resolve()
    if not old_abs.is_file() or not fs_mod.verify_path_under_storage(old_abs):
        return None

    orig_name = doc.get("original_filename") or "unnamed"
    new_unique = f"{uuid.uuid4().hex}_{Path(orig_name).name}"
    new_rel = f"storage/{user_id}/{target_path}/{new_unique}"
    new_abs = (get_settings().storage_path / new_rel).resolve()
    if not file_service_verify_under_storage(new_abs.parent):
        return None
    try:
        shutil.copy2(old_abs, new_abs)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Copy failed: {exc}",
        ) from exc

    size = new_abs.stat().st_size
    now = utc_now()
    new_doc = {
        "user_id": doc["user_id"],
        "original_filename": orig_name,
        "filename": orig_name,
        "filepath": new_rel,
        "mime_type": doc.get("mime_type"),
        "extension": doc.get("extension", ""),
        "size": size,
        "type": doc.get("type", "other"),
        "created_at": now,
        "updated_at": now,
        "device_id": doc.get("device_id"),
        "uploaded_by_device_id": doc.get("uploaded_by_device_id"),
        "synced": bool(doc.get("synced", False)),
        "shared_with": doc.get("shared_with", []),
    }
    res = await db.files.insert_one(new_doc)
    new_doc["_id"] = res.inserted_id
    return file_doc_to_public(new_doc)


async def rename_file(
    *,
    user_id: str,
    actor_id: str,
    role: Role,
    file_id: str,
    new_name: str,
) -> FilePublic | None:
    safe = Path(new_name.strip()).name
    if not safe or safe in (".", ".."):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid name")

    db = get_db()
    try:
        oid = ObjectId(file_id)
    except Exception:  # noqa: BLE001
        return None
    doc = await db.files.find_one({"_id": oid})
    if not doc or str(doc["user_id"]) != user_id:
        return None
    if role == Role.guest:
        return None
    if role == Role.member and str(doc["user_id"]) != actor_id:
        return None

    await db.files.update_one(
        {"_id": oid},
        {"$set": {"original_filename": safe, "filename": safe, "updated_at": utc_now()}},
    )
    doc = await db.files.find_one({"_id": oid})
    return file_doc_to_public(doc) if doc else None


async def rename_folder(
    *,
    user_id: str,
    actor_id: str,
    role: Role,
    path: str,
    new_name: str,
) -> str:
    if role == Role.guest:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    path = normalize_rel_path(path)
    safe_new = Path(new_name.strip()).name
    if not safe_new or "/" in new_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid name")

    root = _user_root(user_id)
    old_dir = _ensure_under_user(root, _join_under(root, path))
    if not old_dir.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")
    parent = old_dir.parent
    new_dir = _ensure_under_user(root, parent / safe_new)
    if new_dir.exists():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Folder already exists")
    try:
        old_dir.rename(new_dir)
    except OSError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    old_prefix = f"storage/{user_id}/{path}"
    new_prefix = f"storage/{user_id}/{path.rsplit('/', 1)[0]}/{safe_new}" if "/" in path else f"storage/{user_id}/{safe_new}"

    db = get_db()
    cursor = db.files.find({"user_id": user_id, "filepath": {"$regex": f"^{re.escape(old_prefix)}/"}})
    async for doc in cursor:
        fp = doc["filepath"]
        suffix = fp[len(old_prefix) :]
        new_fp = new_prefix + suffix
        await db.files.update_one(
            {"_id": doc["_id"]},
            {"$set": {"filepath": new_fp, "updated_at": utc_now()}},
        )

    return f"{path.rsplit('/', 1)[0]}/{safe_new}" if "/" in path else safe_new
