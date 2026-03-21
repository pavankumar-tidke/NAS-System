"""
Aggregated metrics for the dashboard home screen.
"""

from __future__ import annotations

from typing import Any

from app.db.mongo import get_db
from app.models.user import Role
from app.services.file_service import file_doc_to_public


def _files_match(actor_id: str, role: Role, owner_id: str | None) -> dict[str, Any]:
    if role == Role.admin:
        if owner_id:
            return {"user_id": owner_id}
        return {}
    return {"$or": [{"user_id": actor_id}, {"shared_with": actor_id}]}


async def overview(
    *,
    actor_id: str,
    role: Role,
    owner_id: str | None = None,
) -> dict[str, Any]:
    db = get_db()
    m = _files_match(actor_id, role, owner_id)

    agg = await db.files.aggregate(
        [
            {"$match": m},
            {
                "$facet": {
                    "stats": [
                        {"$group": {"_id": None, "count": {"$sum": 1}, "bytes": {"$sum": "$size"}}},
                    ],
                    "recent": [{"$sort": {"created_at": -1}}, {"$limit": 5}],
                }
            },
        ]
    ).to_list(length=1)

    facet = agg[0] if agg else {"stats": [], "recent": []}
    stats = facet.get("stats") or []
    total_files = int(stats[0]["count"]) if stats else 0
    total_storage_used = int(stats[0]["bytes"]) if stats else 0

    recent_files = [file_doc_to_public(d) for d in (facet.get("recent") or [])]

    dev_q: dict[str, Any] = {}
    if role == Role.admin:
        if owner_id:
            dev_q = {"user_id": owner_id}
    else:
        dev_q = {"user_id": actor_id}
    number_of_devices = await db.devices.count_documents(dev_q)

    return {
        "total_files": total_files,
        "total_storage_used": total_storage_used,
        "number_of_devices": number_of_devices,
        "recent_files": [f.model_dump(mode="json") for f in recent_files],
    }
