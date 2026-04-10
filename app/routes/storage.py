"""
Storage volume status under STORAGE_PATH, block-device discovery, and optional mount ops.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.deps import get_current_user
from app.middleware.rbac import require_roles
from app.models.user import Role, UserInDB
from app.schemas.api_response import APIEnvelope, ok
from app.services import storage_service
from app.services import storage_devices_service as storage_hw

router = APIRouter(prefix="/storage", tags=["storage"])


class StorageStatus(BaseModel):
    """Bytes for total / used / free on the filesystem that contains STORAGE_PATH (Pi volume)."""

    total: int = Field(description="Total bytes on filesystem")
    used: int = Field(description="Used bytes")
    free: int = Field(description="Free bytes")
    usage_percentage: float = Field(description="used / total * 100")


@router.get(
    "/status",
    response_model=APIEnvelope,
    summary="Disk usage",
    description="Uses `shutil.disk_usage` on `STORAGE_PATH` (Pi HDD/SSD mount).",
)
async def storage_status(_user: Annotated[UserInDB, Depends(get_current_user)]) -> APIEnvelope:
    data = storage_service.get_storage_status()
    return ok(StorageStatus(**data).model_dump(mode="json"), "Storage status loaded")


class StorageCapabilities(BaseModel):
    storage_ops_enabled: bool
    format_enabled: bool
    mount_path_prefixes: list[str]


@router.get(
    "/capabilities",
    response_model=APIEnvelope,
    summary="Storage UI capabilities",
    description="Whether mount/unmount/format are enabled on this server (env + privileges).",
)
async def storage_capabilities(_user: Annotated[UserInDB, Depends(get_current_user)]) -> APIEnvelope:
    s = get_settings()
    return ok(
        StorageCapabilities(
            storage_ops_enabled=s.nas_storage_ops_enabled,
            format_enabled=s.nas_format_enabled,
            mount_path_prefixes=s.storage_mount_allow_prefixes_list(),
        ).model_dump(mode="json"),
        "Capabilities loaded",
    )


@router.get(
    "/devices",
    response_model=APIEnvelope,
    summary="Connected block devices",
    description="Discovery via `lsblk` (partitions); merged with saved labels and usage when mounted.",
)
async def list_storage_devices(
    _user: Annotated[UserInDB, Depends(require_roles(Role.member, Role.admin))],
) -> APIEnvelope:
    devices = await storage_hw.build_devices_response()
    return ok(devices, "Storage devices loaded")


class DeviceConfigBody(BaseModel):
    device_path: str = Field(description="Block device path e.g. /dev/sda1")
    friendly_name: str | None = None
    usage_type: Literal["general", "backup", "media", "ai"] = "general"
    auto_mount: bool = False
    suggested_mount_path: str | None = Field(
        default=None,
        description="Suggested mount point for UI (e.g. /mnt/storage1); not applied until mount is run.",
    )


@router.post(
    "/devices/config",
    response_model=APIEnvelope,
    summary="Save device preferences",
)
async def save_storage_device_config(
    body: DeviceConfigBody,
    _user: Annotated[UserInDB, Depends(require_roles(Role.admin))],
) -> APIEnvelope:
    storage_hw.validate_device_path(body.device_path)
    if body.suggested_mount_path:
        storage_hw.validate_mount_path(body.suggested_mount_path)
    await storage_hw.save_device_prefs(
        body.device_path,
        friendly_name=body.friendly_name,
        usage_type=body.usage_type,
        auto_mount=body.auto_mount,
        suggested_mount_path=body.suggested_mount_path,
    )
    devices = await storage_hw.build_devices_response()
    return ok(devices, "Device preferences saved")


class MountBody(BaseModel):
    device_path: str
    mount_point: str = Field(description="Where the filesystem should appear (under allowed prefixes)")
    fstype: str | None = Field(default=None, description="Optional `-t` for mount (e.g. ntfs, vfat)")


@router.post(
    "/mount",
    response_model=APIEnvelope,
    summary="Mount a block device",
)
async def mount_storage_device(
    body: MountBody,
    _user: Annotated[UserInDB, Depends(require_roles(Role.admin))],
) -> APIEnvelope:
    storage_hw.try_mount(body.device_path, body.mount_point, fstype=body.fstype)
    devices = await storage_hw.build_devices_response()
    return ok(devices, "Mounted")


class UnmountBody(BaseModel):
    mount_point: str
    lazy: bool = False


@router.post(
    "/unmount",
    response_model=APIEnvelope,
    summary="Unmount by mount point",
)
async def unmount_storage_device(
    body: UnmountBody,
    _user: Annotated[UserInDB, Depends(require_roles(Role.admin))],
) -> APIEnvelope:
    storage_hw.try_unmount(body.mount_point, lazy=body.lazy)
    devices = await storage_hw.build_devices_response()
    return ok(devices, "Unmounted")


class FormatBody(BaseModel):
    device_path: str
    fstype: Literal["ext4", "ntfs", "fat32"] = "ext4"


@router.post(
    "/format",
    response_model=APIEnvelope,
    summary="Format a partition (destructive)",
)
async def format_storage_device(
    body: FormatBody,
    _user: Annotated[UserInDB, Depends(require_roles(Role.admin))],
) -> APIEnvelope:
    storage_hw.try_format(body.device_path, body.fstype)
    devices = await storage_hw.build_devices_response()
    return ok(devices, "Formatted")


class BrowseEntry(BaseModel):
    name: str
    path: str
    type: Literal["directory", "file"]
    size: int


@router.get(
    "/browse",
    response_model=APIEnvelope,
    summary="List directory on an allowed mount",
)
async def browse_storage_path(
    path: Annotated[str, Query(description="Absolute path under allowed mount prefixes")],
    _user: Annotated[UserInDB, Depends(require_roles(Role.member, Role.admin))],
) -> APIEnvelope:
    entries = storage_hw.list_directory(path)
    return ok({"path": path, "entries": entries}, "Directory listed")
