"""JWT-backed sync folder preferences (Mobile Sync UI)."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.deps import get_current_user
from app.middleware.rbac import require_roles
from app.models.user import Role, UserInDB
from app.schemas.api_response import APIEnvelope, ok
from app.services import sync_config_service

router = APIRouter(prefix="/sync", tags=["sync"])


class SyncRule(BaseModel):
    type: Literal["image", "video", "doc", "other"]
    path: str = Field(min_length=1, max_length=500)


class SyncConfigBody(BaseModel):
    default_root: str = Field(default="files/Mobile", max_length=500)
    rules: list[SyncRule] = Field(default_factory=list)
    auto_create_folders: bool = True
    organize_by: Literal["none", "date", "device"] = "none"


@router.get(
    "/preferences",
    response_model=APIEnvelope,
    summary="Get mobile sync folder preferences",
)
async def get_prefs(user: Annotated[UserInDB, Depends(get_current_user)]) -> APIEnvelope:
    data = await sync_config_service.get_sync_config(user.id)
    return ok(data, "Sync preferences loaded")


@router.put(
    "/preferences",
    response_model=APIEnvelope,
    summary="Save mobile sync folder preferences",
)
async def put_prefs(
    body: SyncConfigBody,
    user: Annotated[UserInDB, Depends(require_roles(Role.member, Role.admin))],
) -> APIEnvelope:
    payload: dict[str, Any] = {
        "default_root": body.default_root,
        "rules": [r.model_dump() for r in body.rules],
        "auto_create_folders": body.auto_create_folders,
        "organize_by": body.organize_by,
    }
    data = await sync_config_service.set_sync_config(user.id, payload)
    return ok(data, "Sync preferences saved")
