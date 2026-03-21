"""
Role-based access helpers. Admin bypasses role lists; guest is read-oriented on routes
that attach `require_roles` with member/admin only.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.deps import get_current_user
from app.models.user import Role, UserInDB


def require_roles(*roles: Role) -> Callable[..., UserInDB]:
    """
    Build a FastAPI dependency that ensures the current user has one of the given roles.
    Users with role `admin` always pass.
    """

    allowed = set(roles)

    async def _dependency(user: Annotated[UserInDB, Depends(get_current_user)]) -> UserInDB:
        if user.role == Role.admin:
            return user
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions for this action",
            )
        return user

    return _dependency
