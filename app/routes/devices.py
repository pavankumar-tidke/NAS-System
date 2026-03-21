"""
Device onboarding and lifecycle.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.deps import get_current_user
from app.models.device import DeviceCreate, DevicePublic
from app.models.user import Role, UserInDB
from app.schemas.api_response import APIEnvelope, ok
from app.services import device_service

router = APIRouter(prefix="/devices", tags=["devices"])


@router.post(
    "/register",
    response_model=APIEnvelope,
    status_code=status.HTTP_201_CREATED,
    summary="Register a device",
    description="Returns device metadata and a **one-time** `device_token` for future sync auth.",
)
async def register_device(
    body: DeviceCreate,
    user: Annotated[UserInDB, Depends(get_current_user)],
) -> APIEnvelope:
    dev = await device_service.register_device(user.id, body)
    return ok(dev.model_dump(mode="json"), "Device registered")


@router.get(
    "",
    response_model=APIEnvelope,
    summary="List devices",
    description="Lists devices for the current user; admins may filter with `user_id`.",
)
async def list_devices(
    user: Annotated[UserInDB, Depends(get_current_user)],
    user_id: str | None = Query(default=None, description="Admin only: filter by owner"),
) -> APIEnvelope:
    is_admin = user.role == Role.admin
    if user_id and not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only filter")
    items = await device_service.list_devices(actor_id=user.id, is_admin=is_admin, user_filter=user_id)
    return ok([d.model_dump(mode="json") for d in items], "Devices loaded")


@router.patch(
    "/{device_id}/heartbeat",
    response_model=APIEnvelope,
    summary="Device heartbeat",
    description="Updates `last_active` and `status=online` (call from mobile/desktop periodically).",
)
async def device_heartbeat(
    device_id: str,
    user: Annotated[UserInDB, Depends(get_current_user)],
) -> APIEnvelope:
    is_admin = user.role == Role.admin
    dev = await device_service.heartbeat_device(device_id, user.id, is_admin)
    if dev is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return ok(dev.model_dump(mode="json"), "Heartbeat recorded")


@router.get(
    "/{device_id}",
    response_model=APIEnvelope,
    summary="Get device",
    description="Also refreshes `last_active` when the device record is read.",
)
async def get_device(
    device_id: str,
    user: Annotated[UserInDB, Depends(get_current_user)],
) -> APIEnvelope:
    is_admin = user.role == Role.admin
    dev = await device_service.get_device(device_id, user.id, is_admin)
    if dev is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return ok(dev.model_dump(mode="json"), "Device loaded")


@router.delete(
    "/{device_id}",
    response_model=APIEnvelope,
    summary="Delete device",
    description="Removes the device registration.",
)
async def remove_device(
    device_id: str,
    user: Annotated[UserInDB, Depends(get_current_user)],
) -> APIEnvelope:
    is_admin = user.role == Role.admin
    ok_del = await device_service.delete_device(device_id, user.id, is_admin)
    if not ok_del:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return ok(None, "Device removed")
