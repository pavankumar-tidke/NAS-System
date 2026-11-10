"""Unit tests for STORAGE_PATH .env persistence helper."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services import primary_storage_service as svc


@pytest.fixture
def env_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MONGO_URI", "mongodb://127.0.0.1:27017/nas_test")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("STORAGE_PATH", "/mnt/nas_storage")
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_replace_env_line_updates_existing(env_cwd):
    env_path = env_cwd / ".env"
    env_path.write_text("FOO=bar\nSTORAGE_PATH=/old\n", encoding="utf-8")
    svc.replace_env_line(env_path, "STORAGE_PATH", "/mnt/new")
    text = env_path.read_text(encoding="utf-8")
    assert "FOO=bar" in text
    assert "STORAGE_PATH=/mnt/new" in text
    assert "/old" not in text


def test_append_when_missing(env_cwd):
    env_path = env_cwd / ".env"
    win_path = r"C:\NAS"
    svc.replace_env_line(env_path, "STORAGE_PATH", svc.format_env_value(win_path))
    text = env_path.read_text(encoding="utf-8")
    assert 'STORAGE_PATH="C:\\\\NAS"' in text or 'STORAGE_PATH="C:\\NAS"' in text
