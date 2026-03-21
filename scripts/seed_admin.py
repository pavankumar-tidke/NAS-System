#!/usr/bin/env python3
"""
Seed an admin user for first-time NAS setup.

Usage (from `backend/` directory):
  python scripts/seed_admin.py

Requires valid MONGO_URI and JWT_SECRET in `.env`.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

# Allow `python scripts/seed_admin.py` without installing as a package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.mongo import close_db, connect_db, ensure_indexes  # noqa: E402
from app.models.user import Role, UserCreate  # noqa: E402
from app.services import auth_service  # noqa: E402


async def run(email: str, password: str, name: str) -> None:
    await connect_db()
    await ensure_indexes()
    try:
        user = await auth_service.get_user_by_email(email)
        if user:
            if user.role != Role.admin:
                print("User exists but is not admin; update role in MongoDB manually.")
            else:
                print("Admin user already exists:", email)
            return
        created = await auth_service.create_user(
            UserCreate(name=name, email=email, password=password),
            role=Role.admin,
        )
        print("Created admin user:", created.email, "id=", created.id)
    finally:
        await close_db()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed NAS admin user")
    parser.add_argument("--email", default="admin@nas.local")
    parser.add_argument("--password", default="change-me-now")
    parser.add_argument("--name", default="NAS Admin")
    args = parser.parse_args()
    asyncio.run(run(args.email, args.password, args.name))


if __name__ == "__main__":
    main()
