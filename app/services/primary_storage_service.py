"""Persist and hot-reload STORAGE_PATH for Pi deployments (non-agent mode)."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException, status

from app.core.config import get_settings

_ENV_KEY = "STORAGE_PATH"


def resolve_env_file_path() -> Path:
    return Path.cwd().resolve() / ".env"


def format_env_value(path: str) -> str:
    p = path.strip()
    if not p:
        return p
    if "\\" in p or " " in p:
        escaped = p.replace("\\", "\\\\")
        return f'"{escaped}"'
    return p


def replace_env_line(env_path: Path, key: str, value: str) -> None:
    prefix = f"{key}="
    lines: list[str] = []
    if env_path.is_file():
        raw = env_path.read_text(encoding="utf-8")
        for line in raw.splitlines():
            if line.startswith(prefix):
                continue
            lines.append(line)
    lines.append(f"{prefix}{value}")
    text = "\n".join(lines)
    if not text.endswith("\n"):
        text += "\n"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text(text, encoding="utf-8")


def current_primary_storage() -> dict[str, str]:
    settings = get_settings()
    path = str(settings.storage_path.expanduser().resolve())
    source = "env" if resolve_env_file_path().is_file() else "environment"
    return {"current_path": path, "source": source}


def validate_storage_path(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    allowed = get_settings().storage_mount_allow_prefixes_list()
    s = str(p)
    ok = any(s == prefix or s.startswith(prefix + os.sep) for prefix in allowed)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"storage_path must be under allowed prefixes: {allowed}",
        )
    return p


def apply_primary_storage(path: str) -> dict[str, str]:
    dest = validate_storage_path(path)
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="storage path is not writable or could not be created",
        ) from exc

    env_path = resolve_env_file_path()
    replace_env_line(env_path, _ENV_KEY, format_env_value(str(dest)))
    os.environ[_ENV_KEY] = str(dest)
    get_settings.cache_clear()

    return {"current_path": str(dest), "source": "env" if env_path.is_file() else "environment"}
