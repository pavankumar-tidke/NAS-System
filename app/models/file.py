"""
File metadata schemas (content lives on local disk under STORAGE_PATH).
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class FileType(str, Enum):
    """Coarse NAS file categories for gallery-oriented clients."""

    image = "image"
    video = "video"
    doc = "doc"
    other = "other"


class FilePublic(BaseModel):
    """File metadata exposed to clients."""

    id: str
    user_id: str
    original_filename: str = Field(description="Filename as uploaded by the client")
    filename: str = Field(
        description="Same as original_filename (kept for older dashboard clients)",
    )
    filepath: str = Field(description="Path relative to STORAGE_PATH")
    mime_type: str = Field(description="Detected or declared MIME type")
    extension: str = Field(
        description="Lowercase extension including leading dot, e.g. .pdf (empty if none)",
    )
    size: int
    type: FileType
    created_at: datetime
    updated_at: datetime
    device_id: str | None = None
    uploaded_by_device_id: str | None = None
    synced: bool = False


class FileInDB(FilePublic):
    """Stored document; may add internal fields later."""

    shared_with: list[str] = Field(default_factory=list)
