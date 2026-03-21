"""
Shared FastAPI dependencies: DB access, JWT user resolution, device sync auth.
"""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from app.core.config import get_settings
from app.core.security import decode_token
from app.models.user import UserInDB
from app.services import auth_service, device_service

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> UserInDB:
    """Resolve Bearer JWT to a user document (access token only); sets request.state.user."""
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(creds.credentials)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid subject")

    user = await auth_service.get_user_by_id(sub)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    request.state.user = user
    return user


async def require_device_token(
    x_device_token: Annotated[str | None, Header(alias="X-Device-Token")] = None,
    device_token: Annotated[str | None, Header(alias="Device-Token")] = None,
) -> dict:
    """
    Authenticate mobile/desktop sync calls using the token from POST /devices/register.
    Accepts `X-Device-Token` or `Device-Token` header.
    """
    settings = get_settings()
    if not settings.sync_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sync is disabled on this server",
        )
    raw = (x_device_token or device_token or "").strip()
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Device-Token or Device-Token header",
        )
    doc = await device_service.authenticate_device_token(raw)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked device token",
        )
    return doc
