"""
Map exceptions to the standard API envelope (no stack traces to clients).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

_log = logging.getLogger("uvicorn.error")


def _detail_to_message(detail: Any) -> str:
    if detail is None:
        return "Error"
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        parts: list[str] = []
        for item in detail:
            if isinstance(item, dict):
                parts.append(str(item.get("msg", item)))
            else:
                parts.append(str(item))
        return "; ".join(parts) if parts else "Error"
    if isinstance(detail, dict):
        return str(detail.get("message", detail))
    return str(detail)


def register_exception_handlers(app: Any) -> None:
    """Attach handlers; call once from create_app()."""

    @app.exception_handler(HTTPException)
    async def _http_exc(_request: Request, exc: HTTPException) -> JSONResponse:
        msg = _detail_to_message(exc.detail)
        code = exc.status_code
        return JSONResponse(
            status_code=code,
            content={"success": False, "message": msg, "data": None},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        errs = exc.errors()
        first = errs[0] if errs else {}
        loc = ".".join(str(x) for x in first.get("loc", ()))
        msg = f"{first.get('msg', 'Invalid request')}"
        if loc:
            msg = f"{msg} ({loc})"
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "success": False,
                "message": msg,
                "data": {"errors": errs} if errs else None,
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        _log.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "message": "Internal server error", "data": None},
        )
