"""
Lightweight audit lines for Pi (no separate log store).
"""

from __future__ import annotations

from app.core.logging_setup import get_nas_logger

_log = get_nas_logger()


def log_auth_event(event: str, *, email: str | None = None, user_id: str | None = None) -> None:
    _log.info("audit auth event=%s email=%s user_id=%s", event, email, user_id)


def log_file_upload(*, user_id: str, file_id: str, filename: str, size: int) -> None:
    _log.info("audit upload user_id=%s file_id=%s name=%s size=%s", user_id, file_id, filename, size)


def log_file_download(*, user_id: str, file_id: str, filename: str, partial: bool = False) -> None:
    _log.info(
        "audit download user_id=%s file_id=%s name=%s partial=%s",
        user_id,
        file_id,
        filename,
        partial,
    )


def log_sync_event(
    event: str,
    *,
    user_id: str | None = None,
    device_id: str | None = None,
    detail: str | None = None,
) -> None:
    _log.info(
        "audit sync event=%s user_id=%s device_id=%s %s",
        event,
        user_id,
        device_id,
        detail or "",
    )
