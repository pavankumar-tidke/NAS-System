"""
Dashboard aggregation (home screen widgets).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.deps import get_current_user
from app.models.user import Role, UserInDB
from app.schemas.api_response import APIEnvelope, ok
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get(
    "/overview",
    response_model=APIEnvelope,
    summary="Dashboard overview",
    description="File counts, sum of file sizes, device count, and 5 most recent files.",
)
async def dashboard_overview(
    user: Annotated[UserInDB, Depends(get_current_user)],
    user_id: Annotated[
        str | None,
        Query(description="Admin only: scope metrics to this owner's data"),
    ] = None,
) -> APIEnvelope:
    is_admin = user.role == Role.admin
    if user_id and not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only filter")
    owner = user_id if is_admin else None
    data = await dashboard_service.overview(actor_id=user.id, role=user.role, owner_id=owner)
    return ok(data, "Overview loaded")
