"""
Device onboarding schemas (mobile/desktop sync clients).
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class DeviceCreate(BaseModel):
    """Client payload to register a new device."""

    device_name: str = Field(min_length=1, max_length=200)
    device_type: Literal["mobile", "desktop"]


class DevicePublic(BaseModel):
    """Device returned from APIs (token never included except once at registration)."""

    id: str = Field(description="Mongo document id (use as device_id for sync APIs)")
    device_id: str = Field(description="Same as id — stable id for mobile sync clients")
    user_id: str
    device_name: str
    device_type: str
    status: str = Field(description="online if last_active within DEVICE_TIMEOUT, else offline")
    last_active: datetime | None
    last_sync_time: datetime | None = Field(
        default=None,
        description="Server-side cursor for incremental sync (updated after GET /sync/files)",
    )
    sync_enabled: bool = True
    permissions: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DeviceRegisterResponse(DevicePublic):
    """
    Registration response: includes device_token once for the client to store.
    Use `device_id` + `device_token` on sync endpoints (header X-Device-Token).
    """

    device_token: str
    heartbeat_interval_seconds: int = Field(
        default=30,
        description="Suggested heartbeat interval for mobile clients",
    )


class DeviceInDB(DevicePublic):
    """Full device document shape including hashed sync token."""

    device_token_hash: str | None = None


class SyncHeartbeatBody(BaseModel):
    """POST /sync/heartbeat JSON body."""

    device_id: str = Field(description="Must match the device authenticated by device_token")
    timestamp: datetime | None = Field(
        default=None,
        description="Optional client clock time (server still uses authoritative UTC)",
    )
