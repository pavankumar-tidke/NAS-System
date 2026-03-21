"""Small shared helpers (IDs, time) to avoid duplication across services."""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Timezone-aware UTC now for MongoDB-friendly timestamps."""
    return datetime.now(timezone.utc)
