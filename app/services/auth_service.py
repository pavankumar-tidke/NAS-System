"""
User authentication: signup, lookup, and password verification.
"""

from bson import ObjectId

from app.core.security import hash_password, verify_password
from app.core.utils import utc_now
from app.db.mongo import get_db
from app.models.user import Role, UserCreate, UserInDB


def _doc_to_user(doc: dict) -> UserInDB:
    return UserInDB(
        id=str(doc["_id"]),
        name=doc["name"],
        email=doc["email"],
        role=Role(doc["role"]),
        created_at=doc["created_at"],
        password_hash=doc["password_hash"],
    )


async def get_user_by_email(email: str) -> UserInDB | None:
    db = get_db()
    doc = await db.users.find_one({"email": email.lower()})
    return _doc_to_user(doc) if doc else None


async def get_user_by_id(user_id: str) -> UserInDB | None:
    db = get_db()
    try:
        oid = ObjectId(user_id)
    except Exception:  # noqa: BLE001
        return None
    doc = await db.users.find_one({"_id": oid})
    return _doc_to_user(doc) if doc else None


async def create_user(data: UserCreate, role: Role = Role.member) -> UserInDB:
    """Create a new user; raises ValueError if email already exists."""
    db = get_db()
    email = data.email.lower()
    if await db.users.find_one({"email": email}):
        raise ValueError("Email already registered")

    now = utc_now()
    doc = {
        "name": data.name.strip(),
        "email": email,
        "password_hash": hash_password(data.password),
        "role": role.value,
        "created_at": now,
    }
    result = await db.users.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _doc_to_user(doc)


async def authenticate(email: str, password: str) -> UserInDB | None:
    user = await get_user_by_email(email)
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


