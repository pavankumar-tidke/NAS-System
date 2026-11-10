"""Admin settings proxied to the edge agent when AGENT_URL is set."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.core.agent_client import AgentClient, agent_mode_enabled
from app.middleware.rbac import require_roles
from app.models.user import Role, UserInDB
from app.schemas.api_response import APIEnvelope, ok
from app.services import primary_storage_service

router = APIRouter(prefix="/settings", tags=["settings"])


class PrimaryStorageBody(BaseModel):
    storage_path: str = Field(min_length=1, max_length=2048)


def _auth_header(request: Request) -> str | None:
    return request.headers.get("authorization")


@router.get(
    "/primary-storage",
    response_model=APIEnvelope,
    summary="Current primary STORAGE_PATH",
)
async def get_primary_storage(
    request: Request,
    _user: Annotated[UserInDB, Depends(require_roles(Role.admin))],
) -> APIEnvelope:
    if agent_mode_enabled():
        return await AgentClient.get_json(
            "/settings/primary-storage",
            _auth_header(request),
            context="primary storage",
        )
    return ok(primary_storage_service.current_primary_storage(), "Primary storage loaded")


@router.put(
    "/primary-storage",
    response_model=APIEnvelope,
    summary="Update primary STORAGE_PATH",
)
async def put_primary_storage(
    request: Request,
    body: PrimaryStorageBody,
    _user: Annotated[UserInDB, Depends(require_roles(Role.admin))],
) -> APIEnvelope:
    if agent_mode_enabled():
        return await AgentClient.get_json(
            "/settings/primary-storage",
            _auth_header(request),
            method="PUT",
            json_body=body.model_dump(),
            context="primary storage",
        )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Primary storage updates require AGENT_URL (edge agent)",
    )
