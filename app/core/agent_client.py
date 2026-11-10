"""
HTTP client for delegating file and disk operations to a Pi / edge agent (AGENT_URL).

Mirrors the public REST paths of this API on the agent host. The agent may not exist yet;
failures surface as clear HTTP errors for operators.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx
from fastapi import HTTPException, Request, UploadFile, status
from fastapi.responses import Response, StreamingResponse

from app.core.config import get_settings
from app.schemas.api_response import APIEnvelope, ok

_log = logging.getLogger("nas")

_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=120.0, pool=5.0)
_UPLOAD_TIMEOUT = httpx.Timeout(connect=5.0, read=600.0, write=600.0, pool=5.0)


def agent_mode_enabled() -> bool:
    return get_settings().agent_mode_enabled()


def _base_url() -> str:
    base = get_settings().agent_base_url()
    if not base:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AGENT_URL is not configured",
        )
    return base


def _build_headers(authorization: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if authorization:
        headers["Authorization"] = authorization
    token = get_settings().agent_token
    if token:
        headers["X-Agent-Token"] = token
    return headers


def _map_http_error(exc: httpx.HTTPError, *, context: str) -> HTTPException:
    if isinstance(exc, httpx.ConnectError):
        _log.warning("Agent unreachable (%s): %s", context, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Agent unreachable at AGENT_URL ({context})",
        ) from exc
    if isinstance(exc, httpx.TimeoutException):
        _log.warning("Agent timeout (%s): %s", context, exc)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Agent request timed out ({context})",
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Agent HTTP error ({context}): {exc}",
    ) from exc


def _raise_from_response(resp: httpx.Response, *, context: str) -> None:
    if resp.is_success:
        return
    detail: Any
    try:
        body = resp.json()
        if isinstance(body, dict) and "detail" in body:
            detail = body["detail"]
        elif isinstance(body, dict) and body.get("success") is False:
            detail = body.get("message") or body
        else:
            detail = body
    except (json.JSONDecodeError, ValueError):
        detail = resp.text or f"Agent returned HTTP {resp.status_code}"
    raise HTTPException(status_code=resp.status_code, detail=detail)


async def _parse_envelope(resp: httpx.Response, *, context: str) -> APIEnvelope:
    _raise_from_response(resp, context=context)
    try:
        payload = resp.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent returned non-JSON ({context})",
        ) from exc
    if isinstance(payload, dict) and "success" in payload:
        return APIEnvelope(**payload)
    return ok(payload, "Agent response")


def _passthrough_response(upstream: httpx.Response) -> Response:
    headers = {
        k: v
        for k, v in upstream.headers.items()
        if k.lower() not in ("content-encoding", "transfer-encoding", "connection")
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=headers,
        media_type=upstream.headers.get("content-type"),
    )


async def _stream_upstream(upstream: httpx.Response) -> AsyncIterator[bytes]:
    async for chunk in upstream.aiter_bytes():
        yield chunk


async def check_agent_reachable() -> str:
    """Probe agent GET /health; used by GET /health on the control plane."""
    base = get_settings().agent_base_url()
    if not base:
        return "not configured"
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            resp = await client.get(f"{base}/health", headers=_build_headers(None))
        if resp.status_code >= 500:
            return f"agent degraded (HTTP {resp.status_code})"
        if resp.status_code >= 400:
            return f"agent error (HTTP {resp.status_code})"
        return "ok"
    except httpx.HTTPError as exc:
        return f"unreachable: {exc}"


class AgentClient:
    """Thin async wrapper around httpx for agent delegation."""

    @staticmethod
    async def upload_file(
        request: Request,
        file: UploadFile,
        *,
        device_id: str | None,
        uploaded_by_device_id: str | None,
        path: str | None,
    ) -> APIEnvelope:
        url = f"{_base_url()}/files/upload"
        auth = request.headers.get("authorization")
        data: dict[str, str] = {}
        if device_id is not None:
            data["device_id"] = device_id
        if uploaded_by_device_id is not None:
            data["uploaded_by_device_id"] = uploaded_by_device_id
        if path is not None:
            data["path"] = path
        file_bytes = await file.read()
        files = {
            "file": (
                file.filename or "upload",
                file_bytes,
                file.content_type or "application/octet-stream",
            )
        }
        try:
            async with httpx.AsyncClient(timeout=_UPLOAD_TIMEOUT) as client:
                resp = await client.post(
                    url,
                    headers=_build_headers(auth),
                    data=data,
                    files=files,
                )
        except httpx.HTTPError as exc:
            raise _map_http_error(exc, context="upload") from exc
        return await _parse_envelope(resp, context="upload")

    @staticmethod
    async def get_json(
        path: str,
        authorization: str | None,
        *,
        params: Mapping[str, Any] | None = None,
        method: str = "GET",
        json_body: Any = None,
        context: str,
    ) -> APIEnvelope:
        url = f"{_base_url()}{path}"
        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                resp = await client.request(
                    method,
                    url,
                    headers={**_build_headers(authorization), "Accept": "application/json"},
                    params=params,
                    json=json_body,
                )
        except httpx.HTTPError as exc:
            raise _map_http_error(exc, context=context) from exc
        return await _parse_envelope(resp, context=context)

    @staticmethod
    async def get_binary(
        path: str,
        authorization: str | None,
        *,
        extra_headers: Mapping[str, str] | None = None,
        context: str,
    ) -> Response:
        url = f"{_base_url()}{path}"
        headers = _build_headers(authorization)
        if extra_headers:
            headers.update(extra_headers)
        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                resp = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise _map_http_error(exc, context=context) from exc
        if resp.status_code >= 400:
            _raise_from_response(resp, context=context)
        return _passthrough_response(resp)

    @staticmethod
    async def stream_binary(
        path: str,
        authorization: str | None,
        *,
        range_header: str | None,
        context: str,
    ) -> Response | StreamingResponse:
        url = f"{_base_url()}{path}"
        headers = _build_headers(authorization)
        if range_header:
            headers["Range"] = range_header
        client = httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
        try:
            req = client.build_request("GET", url, headers=headers)
            upstream = await client.send(req, stream=True)
        except httpx.HTTPError as exc:
            await client.aclose()
            raise _map_http_error(exc, context=context) from exc

        if upstream.status_code >= 400:
            body = await upstream.aread()
            await upstream.aclose()
            await client.aclose()
            fake = httpx.Response(upstream.status_code, content=body, request=upstream.request)
            _raise_from_response(fake, context=context)

        out_headers = {
            k: v
            for k, v in upstream.headers.items()
            if k.lower() not in ("content-encoding", "transfer-encoding", "connection")
        }

        async def _iter() -> AsyncIterator[bytes]:
            try:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        if upstream.status_code == status.HTTP_206_PARTIAL_CONTENT:
            return StreamingResponse(
                _iter(),
                status_code=upstream.status_code,
                headers=out_headers,
                media_type=upstream.headers.get("content-type"),
            )
        return StreamingResponse(
            _iter(),
            status_code=upstream.status_code,
            headers=out_headers,
            media_type=upstream.headers.get("content-type"),
        )
