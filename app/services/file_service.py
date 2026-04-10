"""
File metadata + streaming to local disk. Designed for large uploads (chunked writes).

On-disk layout under STORAGE_PATH: ``storage/{user_id}/{images|videos|documents|others}/``
"""

from __future__ import annotations

import mimetypes
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from bson import ObjectId
from fastapi import HTTPException, UploadFile, status

from app.core.config import get_settings
from app.core.utils import utc_now
from app.db.mongo import get_db
from app.models.file import FilePublic, FileType
from app.models.user import Role


CHUNK_SIZE = 1024 * 1024  # 1 MiB chunks — reasonable for Pi memory

_IMAGE_EXT = frozenset(
    {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp", ".tif", ".tiff", ".svg", ".avif"}
)
_VIDEO_EXT = frozenset({".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".mpeg", ".mpg"})
_DOC_EXT = frozenset(
    {
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".txt",
        ".md",
        ".csv",
        ".rtf",
        ".odt",
        ".ods",
        ".odp",
        ".json",
        ".xml",
        ".html",
        ".htm",
    }
)


def _folder_for_type(ftype: FileType) -> str:
    return {
        FileType.image: "images",
        FileType.video: "videos",
        FileType.doc: "documents",
        FileType.other: "others",
    }[ftype]


def _normalize_path_under_files(raw: str | None) -> str | None:
    """Safe relative path under storage/{user_id}/files/ (segments only).

    ``None`` = use legacy typed folders (images/videos/...). ``""`` = root of ``files/``.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return ""
    parts: list[str] = []
    for p in s.replace("\\", "/").strip("/").split("/"):
        p = p.strip()
        if not p or p == ".":
            continue
        if p == "..":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid destination path",
            )
        parts.append(p)
    return "/".join(parts) if parts else ""


def guess_media_type(filename: str) -> str:
    mt, _ = mimetypes.guess_type(filename)
    return mt or "application/octet-stream"


def _effective_mime(filename: str, content_type: str | None) -> str:
    ct = (content_type or "").strip()
    if ct:
        base = ct.split(";")[0].strip().lower()
        if base and base != "application/octet-stream":
            return base
    mt, _ = mimetypes.guess_type(filename)
    return (mt or "application/octet-stream").lower()


def _classify_file(filename: str, content_type: str | None) -> FileType:
    mime = _effective_mime(filename, content_type)
    ext = Path(filename).suffix.lower()

    if mime.startswith("image/") or ext in _IMAGE_EXT:
        return FileType.image
    if mime.startswith("video/") or ext in _VIDEO_EXT:
        return FileType.video
    if mime.startswith("text/"):
        return FileType.doc
    if mime in {
        "application/pdf",
        "application/msword",
        "application/rtf",
        "application/json",
        "application/xml",
    } or mime.startswith(
        (
            "application/vnd.openxmlformats-officedocument",
            "application/vnd.ms-",
            "application/vnd.oasis.opendocument",
        )
    ):
        return FileType.doc
    if ext in _DOC_EXT:
        return FileType.doc
    return FileType.other


def _parse_stored_type(raw: str) -> FileType:
    try:
        return FileType(raw)
    except ValueError:
        return FileType.other


def file_doc_to_public(doc: dict) -> FilePublic:
    """Map a MongoDB file document to FilePublic (backward compatible with legacy rows)."""
    legacy_name = doc.get("filename") or doc.get("original_filename") or "unnamed"
    original = doc.get("original_filename") or legacy_name
    ext = doc.get("extension")
    if ext is None:
        ext = Path(original).suffix.lower()
    elif ext and not ext.startswith("."):
        ext = f".{ext}"

    mime = doc.get("mime_type") or guess_media_type(original)
    created = doc["created_at"]
    updated = doc.get("updated_at") or created

    return FilePublic(
        id=str(doc["_id"]),
        user_id=str(doc["user_id"]),
        original_filename=original,
        filename=original,
        filepath=doc["filepath"],
        mime_type=mime,
        extension=ext or "",
        size=int(doc["size"]),
        type=_parse_stored_type(str(doc.get("type", "other"))),
        created_at=created,
        updated_at=updated,
        device_id=doc.get("device_id"),
        uploaded_by_device_id=doc.get("uploaded_by_device_id"),
        synced=bool(doc.get("synced", False)),
    )


def _visibility_query(*, actor_id: str, role: Role, owner_id: str | None) -> dict:
    if role == Role.admin:
        if owner_id:
            return {"user_id": owner_id}
        return {}
    return {
        "$or": [
            {"user_id": actor_id},
            {"shared_with": actor_id},
        ]
    }


def _list_filter_query(
    *,
    actor_id: str,
    role: Role,
    owner_id: str | None,
    search: str | None,
    type_filter: FileType | None,
) -> dict:
    base = _visibility_query(actor_id=actor_id, role=role, owner_id=owner_id)
    clauses: list[dict] = []
    if base:
        clauses.append(base)

    if search and (q := search.strip()):
        esc = re.escape(q)
        clauses.append(
            {
                "$or": [
                    {"original_filename": {"$regex": esc, "$options": "i"}},
                    {"filename": {"$regex": esc, "$options": "i"}},
                ]
            }
        )

    if type_filter is not None:
        clauses.append({"type": type_filter.value})

    if not clauses:
        return {}
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


async def _allocate_original_filename(user_id: str, desired: str) -> str:
    """
    If the user already has a file with this original_filename, use 'name (1).ext', etc.
    (Disk objects stay unique via UUID prefix; this is the display / metadata name.)
    """
    db = get_db()
    path = Path(desired)
    stem = path.stem
    ext = path.suffix
    candidate = path.name
    n = 0
    while await db.files.count_documents({"user_id": user_id, "original_filename": candidate}, limit=1):
        n += 1
        candidate = f"{stem} ({n}){ext}"
    return candidate


async def list_files_changed_since(
    *,
    user_id: str,
    since: datetime,
    limit: int = 2000,
) -> list[FilePublic]:
    """Files whose effective modification time (updated_at or created_at) is after `since`."""
    db = get_db()
    query: dict = {
        "user_id": user_id,
        "$expr": {
            "$gt": [
                {"$ifNull": ["$updated_at", "$created_at"]},
                since,
            ]
        },
    }
    items: list[FilePublic] = []
    cursor = db.files.find(query).sort([("created_at", 1)]).limit(limit)
    async for doc in cursor:
        items.append(file_doc_to_public(doc))
    return items


async def save_upload(
    *,
    user_id: str,
    upload: UploadFile,
    device_id: str | None,
    uploaded_by_device_id: str | None,
    declared_content_length: int | None = None,
    relative_path: str | None = None,
) -> FilePublic:
    """Stream upload to disk and persist metadata.

    If ``relative_path`` is set, files are stored under ``storage/{user_id}/files/{relative_path}/``.
    Otherwise legacy layout ``storage/{user_id}/{images|videos|documents|others}/`` is used.
    """
    settings = get_settings()
    max_size = settings.max_upload_size
    root = settings.storage_path
    root.mkdir(parents=True, exist_ok=True)

    if declared_content_length is not None and declared_content_length > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds MAX_UPLOAD_SIZE (Content-Length)",
        )

    raw_name = Path(upload.filename or "unnamed").name
    safe_name = await _allocate_original_filename(user_id, raw_name)
    mime = _effective_mime(safe_name, upload.content_type)
    ftype = _classify_file(safe_name, upload.content_type)
    subdir = _folder_for_type(ftype)
    ext = Path(safe_name).suffix.lower()

    unique = f"{uuid.uuid4().hex}_{safe_name}"
    dest_under_files = _normalize_path_under_files(relative_path)
    if dest_under_files is not None:
        user_dir = root / "storage" / user_id / "files"
        if dest_under_files:
            for segment in dest_under_files.split("/"):
                user_dir = user_dir / segment
        user_dir.mkdir(parents=True, exist_ok=True)
    else:
        user_dir = root / "storage" / user_id / subdir
        user_dir.mkdir(parents=True, exist_ok=True)
    dest = user_dir / unique
    relative = str(dest.relative_to(root))

    size = 0
    try:
        with dest.open("wb") as out:
            while True:
                chunk = await upload.read(CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_size:
                    dest.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="File exceeds MAX_UPLOAD_SIZE",
                    )
                out.write(chunk)
    except HTTPException:
        raise
    except OSError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Storage write failed: {exc}",
        ) from exc

    db = get_db()
    now = utc_now()
    doc = {
        "user_id": user_id,
        "original_filename": safe_name,
        "filename": safe_name,
        "filepath": relative,
        "mime_type": mime,
        "extension": ext,
        "size": size,
        "type": ftype.value,
        "created_at": now,
        "updated_at": now,
        "device_id": device_id,
        "uploaded_by_device_id": uploaded_by_device_id,
        "synced": True,
        "shared_with": [],
    }
    res = await db.files.insert_one(doc)
    doc["_id"] = res.inserted_id
    return file_doc_to_public(doc)


async def list_files_page(
    *,
    actor_id: str,
    role: Role,
    owner_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
    sort: Literal["newest", "oldest"] = "newest",
    search: str | None = None,
    type_filter: FileType | None = None,
) -> tuple[list[FilePublic], int]:
    """Paginated listing with total count (RBAC + optional filename search + type filter)."""
    db = get_db()
    query = _list_filter_query(
        actor_id=actor_id,
        role=role,
        owner_id=owner_id,
        search=search,
        type_filter=type_filter,
    )

    direction = -1 if sort == "newest" else 1
    cursor = db.files.find(query).sort("created_at", direction).skip(offset).limit(limit)

    items: list[FilePublic] = []
    async for doc in cursor:
        items.append(file_doc_to_public(doc))

    total = await db.files.count_documents(query)
    return items, total


async def get_file_meta(
    file_id: str,
    *,
    actor_id: str,
    role: Role,
) -> FilePublic | None:
    db = get_db()
    try:
        oid = ObjectId(file_id)
    except Exception:  # noqa: BLE001
        return None
    doc = await db.files.find_one({"_id": oid})
    if not doc:
        return None
    if not _can_access_file(doc, actor_id=actor_id, role=role):
        return None
    return file_doc_to_public(doc)


def _can_access_file(
    doc: dict,
    *,
    actor_id: str,
    role: Role,
) -> bool:
    owner = str(doc["user_id"])
    shared = doc.get("shared_with") or []
    if role == Role.admin:
        return True
    if owner == actor_id:
        return True
    return actor_id in shared


async def delete_file(
    file_id: str,
    *,
    actor_id: str,
    role: Role,
) -> bool:
    """Remove DB row and best-effort delete from disk."""
    db = get_db()
    try:
        oid = ObjectId(file_id)
    except Exception:  # noqa: BLE001
        return False
    doc = await db.files.find_one({"_id": oid})
    if not doc or not _can_access_file(doc, actor_id=actor_id, role=role):
        return False
    if role == Role.guest:
        return False
    if role == Role.member and str(doc["user_id"]) != actor_id:
        return False

    settings = get_settings()
    abs_path = settings.storage_path / doc["filepath"]
    await db.files.delete_one({"_id": oid})
    try:
        abs_path.unlink(missing_ok=True)
    except OSError:
        pass
    return True


def resolve_absolute_path(relative: str) -> Path:
    settings = get_settings()
    return (settings.storage_path / relative).resolve()


def verify_path_under_storage(path: Path) -> bool:
    """Prevent path traversal on download."""
    settings = get_settings()
    try:
        path.relative_to(settings.storage_path.resolve())
        return True
    except ValueError:
        return False
