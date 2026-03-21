"""
User-related schemas and role enum (admin / member / guest).
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, EmailStr, Field


class Role(str, Enum):
    """Basic RBAC roles for NAS operations."""

    admin = "admin"
    member = "member"
    guest = "guest"


class UserCreate(BaseModel):
    """Signup payload."""

    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    """Login payload."""

    email: EmailStr
    password: str


class UserPublic(BaseModel):
    """Safe user representation for API responses."""

    id: str
    name: str
    email: EmailStr
    role: Role
    created_at: datetime


class UserInDB(UserPublic):
    """User as stored in MongoDB (includes hash; never serialize to clients)."""

    password_hash: str


class TokenPair(BaseModel):
    """JWT access + refresh tokens returned after login/signup."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AuthSessionPayload(BaseModel):
    """Tokens plus public user — returned from login/signup/refresh for SPA clients."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserPublic
