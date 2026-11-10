"""
Unauthenticated liveness/readiness: plain JSON (not the API envelope).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Response, status
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError

from app.core.config import get_settings
from app.db.mongo import ping_mongodb

router = APIRouter(tags=["health"])


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _check_storage_config() -> str:
    try:
        settings = get_settings()
    except Exception as exc:  # noqa: BLE001 — surface config load failure in health body
        return f"settings not loaded: {exc}"

    sp = settings.storage_path.expanduser()
    try:
        resolved = sp.resolve()
    except OSError as exc:
        return f"storage_path invalid ({sp}): {exc}"

    if not resolved.exists():
        return f"storage_path does not exist ({resolved})"
    if not resolved.is_dir():
        return f"storage_path is not a directory ({resolved})"
    if not os.access(resolved, os.W_OK):
        return f"storage_path is not writable ({resolved})"
    return "ok"


async def _check_mongo() -> str:
    try:
        await ping_mongodb()
    except RuntimeError as exc:
        return str(exc)
    except PyMongoError as exc:
        return str(exc)
    return "ok"


@router.get(
    "/health",
    summary="Service health",
    description=(
        "Plain JSON health probe (no auth). Returns `status` ok or degraded, per-check results, "
        "and a UTC timestamp. Not wrapped in the standard `{success, message, data}` envelope."
    ),
    response_class=JSONResponse,
)
async def health() -> Response:
    checks: dict[str, str] = {
        "app": "ok",
        "mongo": await _check_mongo(),
        "storage/config": _check_storage_config(),
    }
    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    body = {
        "status": overall,
        "checks": checks,
        "timestamp": _utc_timestamp(),
    }
    code = status.HTTP_200_OK if overall == "ok" else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(content=body, status_code=code)
