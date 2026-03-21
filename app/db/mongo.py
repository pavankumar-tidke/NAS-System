"""
Motor client lifecycle: connect on app startup, close on shutdown.
"""

from __future__ import annotations

from typing import Any

import certifi
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ConfigurationError

from app.core.config import Settings, get_settings

_client: AsyncIOMotorClient | None = None


def _motor_client_kwargs(settings: Settings) -> dict[str, Any]:
    """TLS CA bundle for Atlas (mongodb+srv) — avoids broken system CA paths on some macOS/Python builds."""
    kw: dict[str, Any] = {"maxPoolSize": 10, "minPoolSize": 1}
    uri = settings.mongo_uri.strip()
    if uri.startswith("mongodb+srv://") or "tls=true" in uri.lower():
        ca = str(settings.mongo_tls_ca_file) if settings.mongo_tls_ca_file else certifi.where()
        kw["tlsCAFile"] = ca
    return kw


async def connect_db() -> None:
    """Create a single shared Motor client (connection pool)."""
    global _client
    settings = get_settings()
    _client = AsyncIOMotorClient(settings.mongo_uri, **_motor_client_kwargs(settings))


async def close_db() -> None:
    """Close Motor client on application shutdown."""
    global _client
    if _client is not None:
        _client.close()
        _client = None


async def ensure_indexes() -> None:
    """Create indexes once at startup (idempotent)."""
    db = get_db()
    await db.users.create_index("email", unique=True)
    await db.devices.create_index([("user_id", 1), ("created_at", -1)])
    await db.devices.create_index("device_token_hash", unique=True)
    await db.files.create_index([("user_id", 1), ("created_at", -1)])
    await db.files.create_index([("user_id", 1), ("type", 1), ("created_at", -1)])
    await db.files.create_index([("user_id", 1), ("updated_at", -1)])


async def ping_mongodb() -> str:
    """
    Confirm the server responds; returns the logical database name (for status logs).
    """
    db = get_db()
    await db.command("ping")
    return db.name


def get_db() -> AsyncIOMotorDatabase:
    """
    Return the app database.

    PyMongo raises if the URI has no database path; we fall back to MONGO_DB_NAME or `nas`.
    """
    if _client is None:
        raise RuntimeError("Database not initialized; call connect_db() on startup")
    settings = get_settings()
    if settings.mongo_db_name:
        return _client[settings.mongo_db_name]
    try:
        return _client.get_default_database()
    except ConfigurationError:
        return _client["nas"]
