"""
User profile (legacy path kept for clients already using `/users/me`).
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import get_current_user
from app.models.user import UserInDB, UserPublic
from app.schemas.api_response import APIEnvelope, ok

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    response_model=APIEnvelope,
    summary="Current user (alias)",
    description="Prefer `GET /auth/me` for new dashboard code.",
)
async def read_me(user: Annotated[UserInDB, Depends(get_current_user)]) -> APIEnvelope:
    payload = UserPublic(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role,
        created_at=user.created_at,
    ).model_dump(mode="json")
    return ok(payload, "Profile loaded")
