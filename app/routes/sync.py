"""
Mobile / desktop sync engine: token-based upload, incremental file listing, heartbeat.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status

from app.core.audit_log import log_file_upload, log_sync_event
from app.core.utils import utc_now
from app.deps import require_device_token
from app.models.device import SyncHeartbeatBody
from app.schemas.api_response import APIEnvelope, ok
from app.schemas.sync import SyncFileItem, SyncFilesData
from app.services import device_service, file_service

router = APIRouter(prefix="/sync", tags=["sync"])

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_since_query(value: str | None) -> datetime | None:
    if value is None or not value.strip():
        return None
    v = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(v)
    return _as_utc(parsed)


def _mongo_dt(value: datetime | None) -> datetime:
    if value is None:
        return _EPOCH
    return _as_utc(value)


@router.post(
    "/upload",
    response_model=APIEnvelope,
    status_code=status.HTTP_201_CREATED,
    summary="Sync upload (device token)",
    description=(
        "Upload a file as an authenticated device. Requires `X-Device-Token` (or `Device-Token`). "
        "Associates `user_id` and `device_id` with the file metadata."
    ),
)
async def sync_upload(
    request: Request,
    device_doc: Annotated[dict, Depends(require_device_token)],
    file: Annotated[UploadFile, File(..., description="File body (multipart field `file`)")],
) -> APIEnvelope:
    user_id = str(device_doc["user_id"])
    dev_id = str(device_doc["_id"])
    raw_cl = request.headers.get("content-length")
    declared: int | None = None
    if raw_cl and raw_cl.isdigit():
        declared = int(raw_cl)
    try:
        meta = await file_service.save_upload(
            user_id=user_id,
            upload=file,
            device_id=dev_id,
            uploaded_by_device_id=dev_id,
            declared_content_length=declared,
        )
    except HTTPException as exc:
        log_sync_event(
            "upload_error",
            user_id=user_id,
            device_id=dev_id,
            detail=str(exc.detail),
        )
        raise
    log_file_upload(
        user_id=user_id,
        file_id=meta.id,
        filename=meta.original_filename,
        size=meta.size,
    )
    log_sync_event("upload", user_id=user_id, device_id=dev_id, detail=f"file_id={meta.id}")
    return ok(meta.model_dump(mode="json"), "Sync upload complete")


@router.get(
    "/files",
    response_model=APIEnvelope,
    summary="Incremental file list (device token)",
    description=(
        "Returns files for the device's user modified after `since` (ISO 8601). "
        "If `since` is omitted, uses this device's stored `last_sync_time`, "
        "or full history from epoch on first sync. "
        "Updates `last_sync_time` to `server_time` when the response is built."
    ),
)
async def sync_list_files(
    device_doc: Annotated[dict, Depends(require_device_token)],
    since: Annotated[str | None, Query(description="ISO 8601; omit to use server-side last_sync_time")] = None,
    limit: Annotated[int, Query(ge=1, le=2000, description="Max rows (Pi-friendly cap)")] = 500,
) -> APIEnvelope:
    user_id = str(device_doc["user_id"])
    dev_id = str(device_doc["_id"])
    parsed = _parse_since_query(since)
    boundary = parsed if parsed is not None else _mongo_dt(device_doc.get("last_sync_time"))
    items = await file_service.list_files_changed_since(
        user_id=user_id,
        since=boundary,
        limit=limit,
    )
    server_time = utc_now()
    await device_service.update_device_last_sync(device_doc["_id"], server_time)
    payload = SyncFilesData(
        items=[
            SyncFileItem(
                id=i.id,
                original_filename=i.original_filename,
                mime_type=i.mime_type,
                size=i.size,
                type=i.type.value,
                updated_at=i.updated_at,
            )
            for i in items
        ],
        server_time=server_time,
        since=boundary,
        truncated=len(items) >= limit,
    )
    log_sync_event(
        "list",
        user_id=user_id,
        device_id=dev_id,
        detail=f"count={len(items)} since={boundary.isoformat()}",
    )
    return ok(payload.model_dump(mode="json"), "Sync delta loaded")


@router.post(
    "/heartbeat",
    response_model=APIEnvelope,
    summary="Sync heartbeat (device token)",
    description="Updates `last_active` and online status. `device_id` must match the authenticated device.",
)
async def sync_heartbeat(
    body: SyncHeartbeatBody,
    device_doc: Annotated[dict, Depends(require_device_token)],
) -> APIEnvelope:
    user_id = str(device_doc["user_id"])
    dev = await device_service.heartbeat_device_by_token(
        doc=device_doc,
        device_id=body.device_id,
        client_ts=body.timestamp,
    )
    if dev is None:
        log_sync_event(
            "heartbeat_denied",
            user_id=user_id,
            device_id=body.device_id,
            detail="device_id mismatch",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="device_id does not match device token",
        )
    log_sync_event("heartbeat", user_id=user_id, device_id=body.device_id)
    return ok(dev.model_dump(mode="json"), "Heartbeat recorded")
