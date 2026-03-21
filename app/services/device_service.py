"""
Device lifecycle: onboarding, listing, sync token auth, and removal. Token is hashed at rest.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from bson import ObjectId

from app.core.config import get_settings
from app.core.utils import utc_now
from app.db.mongo import get_db
from app.models.device import DeviceCreate, DeviceInDB, DevicePublic, DeviceRegisterResponse


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _effective_status(last_active: datetime | None) -> str:
    """Derive online/offline from last_active and DEVICE_TIMEOUT."""
    if last_active is None:
        return "offline"
    settings = get_settings()
    if (utc_now() - last_active) > timedelta(seconds=settings.device_timeout_seconds):
        return "offline"
    return "online"


def _doc_to_device(doc: dict, *, include_token_hash: bool = False) -> DeviceInDB:
    did = str(doc["_id"])
    la = doc.get("last_active")
    st = _effective_status(la)
    base = DeviceInDB(
        id=did,
        device_id=did,
        user_id=str(doc["user_id"]),
        device_name=doc["device_name"],
        device_type=doc["device_type"],
        status=st,
        last_active=la,
        last_sync_time=doc.get("last_sync_time"),
        sync_enabled=bool(doc.get("sync_enabled", True)),
        permissions=doc.get("permissions") or {},
        created_at=doc["created_at"],
        device_token_hash=doc.get("device_token_hash"),
    )
    if not include_token_hash:
        base.device_token_hash = None
    return base


def _to_public(d: DeviceInDB) -> DevicePublic:
    return DevicePublic(
        id=d.id,
        device_id=d.device_id,
        user_id=d.user_id,
        device_name=d.device_name,
        device_type=d.device_type,
        status=d.status,
        last_active=d.last_active,
        last_sync_time=d.last_sync_time,
        sync_enabled=d.sync_enabled,
        permissions=d.permissions,
        created_at=d.created_at,
    )


async def register_device(user_id: str, body: DeviceCreate) -> DeviceRegisterResponse:
    """Create a device row and return a one-time device_token for sync clients."""
    settings = get_settings()
    db = get_db()
    raw_token = secrets.token_urlsafe(32)
    now = utc_now()
    doc = {
        "user_id": user_id,
        "device_name": body.device_name.strip(),
        "device_type": body.device_type,
        "status": "online",
        "last_active": now,
        "last_sync_time": None,
        "sync_enabled": True,
        "permissions": {},
        "device_token_hash": _hash_token(raw_token),
        "created_at": now,
    }
    res = await db.devices.insert_one(doc)
    doc["_id"] = res.inserted_id
    public = _to_public(_doc_to_device(doc))
    return DeviceRegisterResponse(
        **public.model_dump(),
        device_token=raw_token,
        heartbeat_interval_seconds=settings.heartbeat_interval_seconds,
    )


async def authenticate_device_token(raw_token: str) -> dict | None:
    """
    Validate device token; returns the raw Mongo device document or None.
    Respects global SYNC_ENABLED and per-device sync_enabled.
    """
    settings = get_settings()
    if not settings.sync_enabled:
        return None
    db = get_db()
    doc = await db.devices.find_one({"device_token_hash": _hash_token(raw_token)})
    if not doc or not doc.get("sync_enabled", True):
        return None
    return doc


async def update_device_last_sync(device_oid: ObjectId, when: datetime) -> None:
    await get_db().devices.update_one({"_id": device_oid}, {"$set": {"last_sync_time": when}})


async def list_devices(
    *,
    actor_id: str,
    is_admin: bool,
    user_filter: str | None = None,
) -> list[DevicePublic]:
    db = get_db()
    query: dict = {}
    if is_admin and user_filter:
        query["user_id"] = user_filter
    elif not is_admin:
        query["user_id"] = actor_id

    out: list[DevicePublic] = []
    async for doc in db.devices.find(query).sort("created_at", -1):
        out.append(_to_public(_doc_to_device(doc)))
    return out


async def get_device(device_id: str, actor_id: str, is_admin: bool) -> DevicePublic | None:
    db = get_db()
    try:
        oid = ObjectId(device_id)
    except Exception:  # noqa: BLE001
        return None
    doc = await db.devices.find_one({"_id": oid})
    if not doc:
        return None
    if not is_admin and str(doc["user_id"]) != actor_id:
        return None
    now = utc_now()
    await db.devices.update_one(
        {"_id": oid},
        {"$set": {"last_active": now, "status": "online"}},
    )
    doc["last_active"] = now
    doc["status"] = "online"
    return _to_public(_doc_to_device(doc))


async def delete_device(device_id: str, actor_id: str, is_admin: bool) -> bool:
    db = get_db()
    try:
        oid = ObjectId(device_id)
    except Exception:  # noqa: BLE001
        return False
    doc = await db.devices.find_one({"_id": oid})
    if not doc:
        return False
    if not is_admin and str(doc["user_id"]) != actor_id:
        return False
    await db.devices.delete_one({"_id": oid})
    return True


async def heartbeat_device(device_id: str, actor_id: str, is_admin: bool) -> DevicePublic | None:
    """Mark device online and refresh last_active (JWT-authenticated heartbeat)."""
    db = get_db()
    try:
        oid = ObjectId(device_id)
    except Exception:  # noqa: BLE001
        return None
    doc = await db.devices.find_one({"_id": oid})
    if not doc:
        return None
    if not is_admin and str(doc["user_id"]) != actor_id:
        return None
    now = utc_now()
    await db.devices.update_one(
        {"_id": oid},
        {"$set": {"last_active": now, "status": "online"}},
    )
    doc["last_active"] = now
    doc["status"] = "online"
    return _to_public(_doc_to_device(doc))


async def heartbeat_device_by_token(
    *,
    doc: dict,
    device_id: str,
    client_ts: datetime | None,
) -> DevicePublic | None:
    """Sync API heartbeat: same device as token, optional client timestamp ignored for authority."""
    oid = doc["_id"]
    if str(oid) != device_id:
        return None
    now = utc_now()
    await get_db().devices.update_one(
        {"_id": oid},
        {"$set": {"last_active": now, "status": "online"}},
    )
    doc = await get_db().devices.find_one({"_id": oid})
    if not doc:
        return None
    _ = client_ts  # reserved for skew logging
    return _to_public(_doc_to_device(doc))
