"""
Path-based browse, folders, move/copy/rename (JWT).
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from app.deps import get_current_user
from app.middleware.rbac import require_roles
from app.models.file import FileType
from app.models.user import Role, UserInDB
from app.schemas.api_response import APIEnvelope, ok
from app.services import browse_service

router = APIRouter(prefix="/files", tags=["files"])


class CreateFolderBody(BaseModel):
    parent_path: str = Field(default="", description="Relative path under user storage")
    name: str = Field(min_length=1, max_length=200)


class MoveFilesBody(BaseModel):
    file_ids: list[str] = Field(min_length=1)
    target_path: str = Field(description="Destination folder relative to user root")


class CopyFileBody(BaseModel):
    file_id: str
    target_path: str


class RenameFileBody(BaseModel):
    file_id: str
    new_name: str = Field(min_length=1, max_length=500)


class RenameFolderBody(BaseModel):
    path: str = Field(description="Folder path to rename")
    new_name: str = Field(min_length=1, max_length=200)


@router.get(
    "/browse",
    response_model=APIEnvelope,
    summary="Browse folder",
    description="List files and subfolders at a path under storage/{user_id}/.",
)
async def browse_files(
    user: Annotated[UserInDB, Depends(get_current_user)],
    path: Annotated[str, Query(description="Relative path (e.g. files or files/Documents)")] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: Annotated[Literal["newest", "oldest"], Query()] = "newest",
    search: Annotated[str | None, Query()] = None,
    file_type: Annotated[
        Literal["image", "video", "doc", "other"] | None,
        Query(alias="type"),
    ] = None,
    user_id: Annotated[str | None, Query(description="Admin only: browse another user's tree")] = None,
) -> APIEnvelope:
    is_admin = user.role == Role.admin
    if user_id and not is_admin:
        from fastapi import HTTPException

        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only filter")
    owner = user_id if is_admin and user_id else None
    tree_owner = owner or user.id
    rel = browse_service.normalize_rel_path(path)
    tf = FileType(file_type) if file_type is not None else None
    items, folders, total = await browse_service.list_browse(
        user_id=tree_owner,
        actor_id=user.id,
        role=user.role,
        owner_id=owner,
        rel_path=rel,
        limit=limit,
        offset=offset,
        sort=sort,
        search=search,
        type_filter=tf,
    )
    parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
    return ok(
        {
            "path": rel,
            "parent_path": parent,
            "folders": folders,
            "items": [i.model_dump(mode="json") for i in items],
            "total": total,
            "limit": limit,
            "offset": offset,
            "sort": sort,
            "search": search,
            "type": file_type,
        },
        "Browse loaded",
    )


@router.post(
    "/folders",
    response_model=APIEnvelope,
    status_code=status.HTTP_201_CREATED,
    summary="Create folder",
)
async def create_folder(
    body: CreateFolderBody,
    user: Annotated[UserInDB, Depends(require_roles(Role.member, Role.admin))],
) -> APIEnvelope:
    data = await browse_service.create_folder(user_id=user.id, parent_path=body.parent_path, name=body.name)
    return ok(data, "Folder created")


@router.post(
    "/move",
    response_model=APIEnvelope,
    summary="Move files",
)
async def move_files(
    body: MoveFilesBody,
    user: Annotated[UserInDB, Depends(require_roles(Role.member, Role.admin))],
) -> APIEnvelope:
    n = await browse_service.move_files(
        user_id=user.id,
        actor_id=user.id,
        role=user.role,
        file_ids=body.file_ids,
        target_path=body.target_path,
    )
    return ok({"moved": n}, f"Moved {n} file(s)")


@router.post(
    "/copy",
    response_model=APIEnvelope,
    summary="Copy file",
    status_code=status.HTTP_201_CREATED,
)
async def copy_file_route(
    body: CopyFileBody,
    user: Annotated[UserInDB, Depends(require_roles(Role.member, Role.admin))],
) -> APIEnvelope:
    meta = await browse_service.copy_file(
        user_id=user.id,
        actor_id=user.id,
        role=user.role,
        file_id=body.file_id,
        target_path=body.target_path,
    )
    if meta is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return ok(meta.model_dump(mode="json"), "File copied")


@router.post(
    "/rename",
    response_model=APIEnvelope,
    summary="Rename file",
)
async def rename_file_route(
    body: RenameFileBody,
    user: Annotated[UserInDB, Depends(require_roles(Role.member, Role.admin))],
) -> APIEnvelope:
    meta = await browse_service.rename_file(
        user_id=user.id,
        actor_id=user.id,
        role=user.role,
        file_id=body.file_id,
        new_name=body.new_name,
    )
    if meta is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return ok(meta.model_dump(mode="json"), "Renamed")


@router.post(
    "/folders/rename",
    response_model=APIEnvelope,
    summary="Rename folder",
)
async def rename_folder_route(
    body: RenameFolderBody,
    user: Annotated[UserInDB, Depends(require_roles(Role.member, Role.admin))],
) -> APIEnvelope:
    new_path = await browse_service.rename_folder(
        user_id=user.id,
        actor_id=user.id,
        role=user.role,
        path=body.path,
        new_name=body.new_name,
    )
    return ok({"path": new_path}, "Folder renamed")


@router.get(
    "/folders/tree",
    response_model=APIEnvelope,
    summary="Folder tree for picker",
)
async def folder_tree(
    user: Annotated[UserInDB, Depends(get_current_user)],
    max_depth: Annotated[int, Query(ge=1, le=20)] = 8,
) -> APIEnvelope:
    tree = await browse_service.get_folder_tree(user_id=user.id, max_depth=max_depth)
    return ok(tree, "Folder tree loaded")
