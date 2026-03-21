"""
Standard JSON envelope for dashboard / mobile clients.

Binary routes (file download, preview, range stream) skip this shape.
"""

from typing import Any

from pydantic import BaseModel, Field


class APIEnvelope(BaseModel):
    """{ success, message, data } — used for all JSON responses."""

    success: bool = Field(description="Whether the request succeeded")
    message: str = Field(description="Human-readable summary")
    data: Any = Field(default=None, description="Payload; shape depends on endpoint")


def ok(data: Any = None, message: str = "Success") -> APIEnvelope:
    """Build a successful envelope."""
    return APIEnvelope(success=True, message=message, data=data)
