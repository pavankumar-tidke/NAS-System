"""
Storage volume status under STORAGE_PATH.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.deps import get_current_user
from app.models.user import UserInDB
from app.schemas.api_response import APIEnvelope, ok
from app.services import storage_service

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
