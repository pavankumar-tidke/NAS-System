"""Persist mobile sync folder preferences (dashboard UI)."""

from __future__ import annotations

from typing import Any, Literal

from app.db.mongo import get_db

OrganizeBy = Literal["none", "date", "device"]


def default_config() -> dict[str, Any]:
    return {
        "default_root": "files/Mobile",
        "rules": [
            {"type": "image", "path": "Photos/Mobile"},
            {"type": "video", "path": "Videos/Mobile"},
            {"type": "doc", "path": "Documents/Mobile"},
            {"type": "other", "path": "files/Mobile/Others"},
        ],
        "auto_create_folders": True,
        "organize_by": "none",
    }


async def get_sync_config(user_id: str) -> dict[str, Any]:
    db = get_db()
    doc = await db.sync_preferences.find_one({"user_id": user_id})
    if not doc:
        return default_config()
    out = default_config()
    out.update(
        {
            "default_root": doc.get("default_root", out["default_root"]),
            "rules": doc.get("rules", out["rules"]),
            "auto_create_folders": bool(doc.get("auto_create_folders", True)),
            "organize_by": doc.get("organize_by", "none"),
        }
    )
    return out


async def set_sync_config(user_id: str, body: dict[str, Any]) -> dict[str, Any]:
    db = get_db()
    doc = {
        "user_id": user_id,
        "default_root": str(body.get("default_root", default_config()["default_root"])),
        "rules": body.get("rules", []),
        "auto_create_folders": bool(body.get("auto_create_folders", True)),
        "organize_by": body.get("organize_by", "none"),
    }
    await db.sync_preferences.update_one(
        {"user_id": user_id},
        {"$set": doc},
        upsert=True,
    )
    return await get_sync_config(user_id)
