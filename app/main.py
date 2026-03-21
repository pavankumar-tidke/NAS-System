"""
FastAPI entrypoint: routers, MongoDB lifecycle, CORS, structured errors, OpenAPI metadata.
"""

from __future__ import annotations

import logging
import platform
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pymongo.errors import PyMongoError

from app.core.config import get_settings
from app.core.error_handlers import register_exception_handlers
from app.core.logging_setup import get_nas_logger, setup_nas_logging
from app.db.mongo import close_db, connect_db, ensure_indexes, ping_mongodb
from app.db.mongo_errors import mongo_startup_banner, summarize_mongo_error
from app.routes import auth, dashboard, devices, files, storage, sync, users

setup_nas_logging()
_uvicorn_logger = logging.getLogger("uvicorn.error")

TAGS_METADATA = [
    {
        "name": "auth",
        "description": "Signup, login, JWT refresh, and `GET /auth/me` for SPAs.",
    },
    {"name": "users", "description": "User profile aliases (`/users/me`)."},
    {"name": "devices", "description": "Device onboarding, heartbeat, and CRUD."},
    {
        "name": "files",
        "description": (
            "Multipart uploads into typed folders (`images/`, `videos/`, `documents/`, `others/`), "
            "paginated list with filename search and type filter, download, preview, ranged video."
        ),
    },
    {"name": "storage", "description": "Disk usage for the NAS data volume."},
    {"name": "dashboard", "description": "Aggregated metrics for the React dashboard home."},
    {
        "name": "sync",
        "description": (
            "Device-token sync: upload from mobile, incremental file delta (`GET /sync/files`), "
            "and token-based heartbeat."
        ),
    },
]


def _log_runtime_and_env() -> None:
    log = get_nas_logger()
    in_venv = getattr(sys, "base_prefix", sys.prefix) != sys.prefix
    log.info(
        "Python runtime: executable=%s in_venv_hint=%s version=%s",
        sys.executable,
        in_venv,
        platform.python_version(),
    )
    env_file = Path.cwd() / ".env"
    log.info(
        "Environment variables loaded from .env file (path: %s) exists=%s",
        env_file.resolve(),
        env_file.is_file(),
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Open Mongo connection pool and ensure indexes; release on shutdown."""
    log = get_nas_logger()
    settings = get_settings()

    _log_runtime_and_env()

    try:
        await connect_db()
        log.info("MongoDB: client pool created")
        await ensure_indexes()
        log.info(
            "MongoDB indexes ensured (collections: users, devices, files; indexes: email unique, user_id+created_at)"
        )
        db_name = await ping_mongodb()
        log.info("MongoDB connected (database=%s)", db_name)
    except PyMongoError as exc:
        log.error("MongoDB: NOT connected")
        print(mongo_startup_banner(exc), file=sys.stderr, flush=True)
        short = summarize_mongo_error(exc)
        _uvicorn_logger.error("%s", short)
        raise RuntimeError(short) from None

    sp = settings.storage_path.resolve()
    log.info("Storage: path=%s exists=%s", sp, sp.exists())

    sep = "#" * 50
    log.info("%s", sep)
    log.info(
        "%s running on port %s (bind: %s) [%s]",
        settings.app_name,
        settings.api_port,
        settings.api_host,
        settings.environment,
    )
    log.info("Internal access: http://localhost:%s", settings.api_port)
    log.info("External access: http://%s:%s", settings.api_host, settings.api_port)
    log.info("%s", sep)
    log.info(
        "NAS configuration: storage_path=%s max_upload_mb=%s jwt_access_min=%s jwt_refresh_days=%s debug=%s cors_origins=%s",
        sp,
        settings.max_upload_size // (1024 * 1024),
        settings.jwt_access_expire_minutes,
        settings.jwt_refresh_expire_days,
        settings.debug,
        settings.cors_origins,
    )
    log.info("NAS API ready ✅")

    yield

    log.info("Shutting down: closing MongoDB client")
    await close_db()


def create_app() -> FastAPI:
    """Application factory (tests + ASGI servers)."""
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description=(
            "Personal NAS REST API — JSON responses use `{success, message, data}` except raw "
            "file download / preview / stream endpoints."
        ),
        version="0.2.0",
        lifespan=lifespan,
        debug=settings.debug,
        openapi_tags=TAGS_METADATA,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    register_exception_handlers(app)

    # Permissive CORS: `*` + `credentials: false` (JWT lives in `Authorization`, not cookies).
    # For locked-down production, run behind a reverse proxy that sets CORS or set a fork with
    # `allow_origins` + `allow_credentials=True` and an explicit origin list.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(devices.router)
    app.include_router(files.router)
    app.include_router(storage.router)
    app.include_router(sync.router)
    app.include_router(dashboard.router)

    @app.websocket("/ws")
    async def websocket_placeholder(websocket: WebSocket) -> None:
        """Placeholder for realtime (Phase 3)."""
        await websocket.accept()
        await websocket.close(code=1000)

    return app


app = create_app()
