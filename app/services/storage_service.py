"""
Disk usage for the configured STORAGE_PATH (mounted volume on Pi).
"""

import shutil

from app.core.config import get_settings


def get_storage_status() -> dict[str, int | float]:
    """
    Return total/used/free bytes for the filesystem containing STORAGE_PATH (Pi mount),
    plus usage_percentage (used/total * 100).
    """
    settings = get_settings()
    path = settings.storage_path
    path.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(path)
    total = int(usage.total)
    used = int(usage.used)
    free = int(usage.free)
    pct = round((used / total) * 100.0, 2) if total > 0 else 0.0
    return {
        "total": total,
        "used": used,
        "free": free,
        "usage_percentage": pct,
    }
