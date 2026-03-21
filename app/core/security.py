"""
Password hashing (bcrypt) and JWT access/refresh token helpers.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import jwt

from app.core.config import get_settings

ALGORITHM = "HS256"


def hash_password(plain: str) -> str:
    """Hash a plaintext password for storage (bcrypt)."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, password_hash: str) -> bool:
    """Verify plaintext against stored bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), password_hash.encode("utf-8"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    """Issue a short-lived JWT access token (sub = user id)."""
    settings = get_settings()
    expire = _now() + timedelta(minutes=settings.jwt_access_expire_minutes)
    payload: dict[str, Any] = {
        "sub": subject,
        "exp": expire,
        "type": "access",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def create_refresh_token(subject: str) -> str:
    """Issue a longer-lived refresh token (stateless for Pi simplicity)."""
    settings = get_settings()
    expire = _now() + timedelta(days=settings.jwt_refresh_expire_days)
    payload = {
        "sub": subject,
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate JWT; raises JWTError on failure."""
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
