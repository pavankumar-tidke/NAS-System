"""Agent stream proxy must buffer through Lambda (no StreamingResponse for Range)."""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import patch

import httpx
import pytest
from fastapi.responses import Response, StreamingResponse

from app.core.agent_client import AgentClient
from app.routes import files


def test_stream_route_agent_mode_always_uses_get_binary():
    src = inspect.getsource(files.stream_file)
    assert "get_binary" in src
    assert "stream_binary" not in src


@pytest.fixture
def agent_settings_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENT_URL", "http://agent.test")
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-for-unit-tests-only")
    monkeypatch.setenv("MONGO_URI", "mongodb://127.0.0.1:27017/nas-test")
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _run(coro):
    return asyncio.run(coro)


def test_get_binary_buffers_full_file_200(agent_settings_env):
    captured: dict = {}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, headers=None):
            captured["url"] = url
            captured["headers"] = headers
            return httpx.Response(
                200,
                content=b"full-body",
                headers={"Content-Type": "video/mp4", "Accept-Ranges": "bytes"},
            )

    async def _case():
        with patch("app.core.agent_client.httpx.AsyncClient", return_value=FakeClient()):
            resp = await AgentClient.get_binary(
                "/files/stream/vid",
                "Bearer token",
                context="stream",
            )
        assert isinstance(resp, Response)
        assert not isinstance(resp, StreamingResponse)
        assert resp.status_code == 200
        assert resp.body == b"full-body"
        assert captured["headers"]["Authorization"] == "Bearer token"

    _run(_case())


def test_get_binary_forwards_range_and_buffers_206(agent_settings_env):
    captured: dict = {}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, headers=None):
            captured["url"] = url
            captured["headers"] = headers
            return httpx.Response(
                206,
                content=b"0123",
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Range": "bytes 0-3/9999",
                    "Content-Length": "4",
                    "Accept-Ranges": "bytes",
                },
            )

    async def _case():
        with patch("app.core.agent_client.httpx.AsyncClient", return_value=FakeClient()):
            resp = await AgentClient.get_binary(
                "/files/stream/vid",
                "Bearer token",
                extra_headers={"Range": "bytes=0-3"},
                context="stream",
            )
        assert isinstance(resp, Response)
        assert not isinstance(resp, StreamingResponse)
        assert resp.status_code == 206
        assert resp.body == b"0123"
        assert resp.headers["content-range"] == "bytes 0-3/9999"
        assert captured["headers"]["Range"] == "bytes=0-3"

    _run(_case())
