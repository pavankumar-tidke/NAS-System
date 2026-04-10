"""
Centralized settings loaded from environment (.env supported via pydantic-settings).
All tunables for Pi deployment live here.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration — override via environment or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="NAS Core API", alias="APP_NAME")
    debug: bool = Field(default=False, alias="DEBUG")
    environment: Literal["development", "production"] = Field(
        default="development",
        alias="ENVIRONMENT",
    )
    # Comma-separated origins, e.g. http://localhost:8080,http://localhost:3000
    cors_origins: str = Field(
        default="http://localhost:8080,http://localhost:3000",
        alias="CORS_ORIGINS",
    )
    # Used for startup log lines (match uvicorn --host/--port in run.sh).
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")

    mongo_uri: str = Field(..., alias="MONGO_URI")
    # If MONGO_URI has no database path (e.g. mongodb://host:27017), use this name.
    mongo_db_name: str | None = Field(default=None, alias="MONGO_DB_NAME")
    # Optional PEM bundle for Atlas TLS; default uses certifi (see connect_db).
    mongo_tls_ca_file: Path | None = Field(default=None, alias="MONGO_TLS_CA_FILE")
    jwt_secret: str = Field(..., alias="JWT_SECRET")
    jwt_access_expire_minutes: int = Field(default=30, alias="JWT_ACCESS_EXPIRE_MINUTES")
    jwt_refresh_expire_days: int = Field(default=14, alias="JWT_REFRESH_EXPIRE_DAYS")

    storage_path: Path = Field(default=Path("/mnt/nas_storage"), alias="STORAGE_PATH")
    max_upload_size: int = Field(default=524_288_000, alias="MAX_UPLOAD_SIZE")
    # Set to true in .env if your shell exports ENVIRONMENT=production but you still need local SPA CORS.
    nas_cors_dev: bool = Field(default=False, alias="NAS_CORS_DEV")

    # Mobile / device sync (Phase 3)
    sync_enabled: bool = Field(default=True, alias="SYNC_ENABLED")
    heartbeat_interval_seconds: int = Field(default=30, alias="HEARTBEAT_INTERVAL")
    device_timeout_seconds: int = Field(default=120, alias="DEVICE_TIMEOUT")

    # Block storage (Pi): requires privileges when enabled
    nas_storage_ops_enabled: bool = Field(default=False, alias="NAS_STORAGE_OPS_ENABLED")
    nas_format_enabled: bool = Field(default=False, alias="NAS_FORMAT_ENABLED")
    # Comma-separated allowed mount parent paths (e.g. /mnt,/media)
    storage_mount_allow_prefixes: str = Field(default="/mnt,/media", alias="STORAGE_MOUNT_ALLOW_PREFIXES")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _strip_cors(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v

    def cors_origin_list(self) -> list[str]:
        parts = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return parts if parts else ["http://localhost:8080"]

    def storage_mount_allow_prefixes_list(self) -> list[str]:
        parts = [p.strip().rstrip("/") for p in self.storage_mount_allow_prefixes.split(",") if p.strip()]
        return parts if parts else ["/mnt", "/media"]


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance (safe for import-time use)."""
    return Settings()
