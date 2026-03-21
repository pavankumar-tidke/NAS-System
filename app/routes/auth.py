"""
Authentication: signup, login, refresh, and current user (`/auth/me`).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError
from pydantic import BaseModel, Field

from app.core.audit_log import log_auth_event
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.deps import get_current_user
from app.models.user import (
    AuthSessionPayload,
    UserCreate,
    UserInDB,
    UserLogin,
    UserPublic,
)
from app.schemas.api_response import APIEnvelope, ok
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


class RefreshBody(BaseModel):
    """Refresh token in JSON body (SPA-friendly)."""

    refresh_token: str = Field(description="JWT refresh token from login/signup")


def _user_public(u: UserInDB) -> UserPublic:
    return UserPublic(
        id=u.id,
        name=u.name,
        email=u.email,
        role=u.role,
        created_at=u.created_at,
    )


def _session_payload(user: UserInDB, access: str, refresh: str) -> dict:
    return AuthSessionPayload(
        access_token=access,
        refresh_token=refresh,
        token_type="bearer",
        user=_user_public(user),
    ).model_dump(mode="json")


@router.post(
    "/signup",
    response_model=APIEnvelope,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account",
    description="Creates a `member` user and returns JWT pair plus public profile.",
)
async def signup(body: UserCreate) -> APIEnvelope:
    try:
        user = await auth_service.create_user(body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    access = create_access_token(user.id, extra={"role": user.role.value})
    refresh = create_refresh_token(user.id)
    log_auth_event("signup", email=user.email, user_id=user.id)
    return ok(_session_payload(user, access, refresh), "Account created")


@router.post(
    "/login",
    response_model=APIEnvelope,
    summary="Login",
    description="Returns access + refresh tokens and the user profile for dashboard state.",
)
async def login(body: UserLogin) -> APIEnvelope:
    user = await auth_service.authenticate(body.email, body.password)
    if user is None:
        log_auth_event("login_failed", email=body.email)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    access = create_access_token(user.id, extra={"role": user.role.value})
    refresh = create_refresh_token(user.id)
    log_auth_event("login", email=user.email, user_id=user.id)
    return ok(_session_payload(user, access, refresh), "Logged in")


@router.post(
    "/refresh",
    response_model=APIEnvelope,
    summary="Refresh tokens",
    description="Exchange a valid refresh JWT for a new access + refresh pair.",
)
async def refresh_tokens(body: RefreshBody) -> APIEnvelope:
    try:
        payload = decode_token(body.refresh_token)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid subject")
    user = await auth_service.get_user_by_id(sub)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    access = create_access_token(user.id, extra={"role": user.role.value})
    new_refresh = create_refresh_token(user.id)
    log_auth_event("refresh", user_id=user.id)
    return ok(_session_payload(user, access, new_refresh), "Tokens refreshed")


@router.get(
    "/me",
    response_model=APIEnvelope,
    summary="Current user",
    description="Returns the authenticated user's public profile (same as `GET /users/me`).",
)
async def auth_me(user: Annotated[UserInDB, Depends(get_current_user)]) -> APIEnvelope:
    return ok(_user_public(user).model_dump(mode="json"), "Profile loaded")
