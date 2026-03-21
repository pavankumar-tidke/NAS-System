"""Minimal payloads for mobile sync clients."""

from datetime import datetime

from pydantic import BaseModel, Field


class SyncFileItem(BaseModel):
    """Lightweight file row for incremental sync."""

    id: str
    original_filename: str
    mime_type: str
    size: int
    type: str
    updated_at: datetime


class SyncFilesData(BaseModel):
    items: list[SyncFileItem]
    server_time: datetime = Field(description="Store this and send as `since` on next sync")
    since: datetime = Field(description="Effective lower bound used for this response")
    truncated: bool = Field(
        default=False,
        description="True if row count hit `limit`; repeat with higher limit or tighter `since`",
    )
