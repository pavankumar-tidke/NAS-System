"""
NAS files: multipart upload, paginated listing, download, image preview, ranged video stream.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse

from app.core.audit_log import log_file_download, log_file_upload
from app.deps import get_current_user
from app.middleware.rbac import require_roles
from app.models.file import FilePublic, FileType
from app.models.user import Role, UserInDB
from app.schemas.api_response import APIEnvelope, ok
from app.services import file_service
from app.services.file_streaming import iter_file_bytes, parse_range_header

router = APIRouter(prefix="/files", tags=["files"])


def _file_media_type(meta: FilePublic) -> str:
    return meta.mime_type or file_service.guess_media_type(meta.original_filename)


@router.post(
    "/upload",
    response_model=APIEnvelope,
    status_code=status.HTTP_201_CREATED,
    summary="Multipart upload",
    description=(
        "Streams the file under `storage/{user_id}/{images|videos|documents|others}/` "
        "based on MIME/extension. "
        "Honours `MAX_UPLOAD_SIZE` and optional `Content-Length` pre-check."
    ),
)
async def upload_file(
    request: Request,
    user: Annotated[UserInDB, Depends(require_roles(Role.member, Role.admin))],
    file: Annotated[UploadFile, File(..., description="File body (multipart field `file`)")],
    device_id: str | None = Form(default=None),
    uploaded_by_device_id: str | None = Form(default=None),
) -> APIEnvelope:
    raw_cl = request.headers.get("content-length")
    declared: int | None = None
    if raw_cl and raw_cl.isdigit():
        declared = int(raw_cl)
    meta = await file_service.save_upload(
        user_id=user.id,
        upload=file,
        device_id=device_id,
        uploaded_by_device_id=uploaded_by_device_id,
        declared_content_length=declared,
    )
    log_file_upload(
        user_id=user.id,
        file_id=meta.id,
        filename=meta.filename,
        size=meta.size,
    )
    return ok(meta.model_dump(mode="json"), "Upload complete")


@router.get(
    "",
    response_model=APIEnvelope,
    summary="List files (paginated)",
    description=(
        "Pagination via `limit` and `offset`; sort by `created_at` (`newest` | `oldest`). "
        "Optional `search` matches original filename (case-insensitive substring). "
        "Optional `type` filters by category: `image`, `video`, `doc`, `other`."
    ),
)
async def list_files(
    user: Annotated[UserInDB, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100, description="Page size (max 100 for Pi)")] = 20,
    offset: Annotated[int, Query(ge=0, description="Offset for pagination")] = 0,
    sort: Annotated[
        Literal["newest", "oldest"],
        Query(description="Sort by created_at"),
    ] = "newest",
    search: Annotated[str | None, Query(description="Substring match on original filename")] = None,
    file_type: Annotated[
        Literal["image", "video", "doc", "other"] | None,
        Query(alias="type", description="Filter by file category"),
    ] = None,
    user_id: Annotated[str | None, Query(description="Admin only: filter by owner")] = None,
) -> APIEnvelope:
    is_admin = user.role == Role.admin
    if user_id and not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only filter")
    owner_filter = user_id if is_admin else None
    type_filter = FileType(file_type) if file_type is not None else None
    items, total = await file_service.list_files_page(
        actor_id=user.id,
        role=user.role,
        owner_id=owner_filter,
        limit=limit,
        offset=offset,
        sort=sort,
        search=search,
        type_filter=type_filter,
    )
    return ok(
        {
            "items": [i.model_dump(mode="json") for i in items],
            "total": total,
            "limit": limit,
            "offset": offset,
            "sort": sort,
            "search": search,
            "type": file_type,
        },
        "Files loaded",
    )


@router.get(
    "/download/{file_id}",
    summary="Download full file",
    description="Returns raw bytes with correct filename (not JSON envelope).",
    response_class=FileResponse,
)
async def download_file(
    file_id: str,
    user: Annotated[UserInDB, Depends(get_current_user)],
) -> FileResponse:
    meta = await file_service.get_file_meta(file_id, actor_id=user.id, role=user.role)
    if meta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    path = file_service.resolve_absolute_path(meta.filepath)
    if not file_service.verify_path_under_storage(path) or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File missing on disk")
    log_file_download(user_id=user.id, file_id=meta.id, filename=meta.original_filename, partial=False)
    media = _file_media_type(meta)
    return FileResponse(path=path, filename=meta.original_filename, media_type=media)


@router.get(
    "/preview/{file_id}",
    summary="Image preview",
    description="Same as download but **images only** — suitable for `<img src>`.",
    response_class=FileResponse,
)
async def preview_file(
    file_id: str,
    user: Annotated[UserInDB, Depends(get_current_user)],
) -> FileResponse:
    meta = await file_service.get_file_meta(file_id, actor_id=user.id, role=user.role)
    if meta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    if meta.type != FileType.image:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Preview is only available for image type files",
        )
    path = file_service.resolve_absolute_path(meta.filepath)
    if not file_service.verify_path_under_storage(path) or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File missing on disk")
    media = _file_media_type(meta)
    return FileResponse(path=path, media_type=media, filename=meta.original_filename)


@router.get(
    "/stream/{file_id}",
    response_model=None,
    summary="Stream with Range support",
    description="Use for HTML5 video (`<video src>`). Supports `Range: bytes=…` → `206 Partial Content`.",
)
async def stream_file(
    request: Request,
    file_id: str,
    user: Annotated[UserInDB, Depends(get_current_user)],
):
    meta = await file_service.get_file_meta(file_id, actor_id=user.id, role=user.role)
    if meta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    path = file_service.resolve_absolute_path(meta.filepath)
    if not file_service.verify_path_under_storage(path) or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File missing on disk")
    size = path.stat().st_size
    media = _file_media_type(meta)
    rng = parse_range_header(request.headers.get("range"), size)
    if rng is None:
        log_file_download(user_id=user.id, file_id=meta.id, filename=meta.original_filename, partial=False)
        return FileResponse(
            path=path,
            media_type=media,
            headers={"Accept-Ranges": "bytes"},
            filename=meta.original_filename,
        )
    start, end = rng
    log_file_download(user_id=user.id, file_id=meta.id, filename=meta.original_filename, partial=True)
    length = end - start + 1
    headers = {
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
    }
    return StreamingResponse(
        iter_file_bytes(path, start, end),
        media_type=media,
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        headers=headers,
    )


@router.get(
    "/{file_id}",
    response_model=APIEnvelope,
    summary="File metadata",
)
async def get_file(
    file_id: str,
    user: Annotated[UserInDB, Depends(get_current_user)],
) -> APIEnvelope:
    meta = await file_service.get_file_meta(file_id, actor_id=user.id, role=user.role)
    if meta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return ok(meta.model_dump(mode="json"), "File loaded")


@router.delete(
    "/{file_id}",
    response_model=APIEnvelope,
    summary="Delete file",
)
async def delete_file(
    file_id: str,
    user: Annotated[UserInDB, Depends(require_roles(Role.member, Role.admin))],
) -> APIEnvelope:
    ok_del = await file_service.delete_file(file_id, actor_id=user.id, role=user.role)
    if not ok_del:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return ok(None, "File deleted")
