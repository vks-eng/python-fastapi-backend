"""Application configuration loaded from environment variables (12-factor style)."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def normalize_database_url(value: str) -> str:
    """Accept postgres:// / postgresql:// URLs and force the asyncpg driver."""
    for prefix in ("postgres://", "postgresql://"):
        if value.startswith(prefix):
            value = "postgresql+asyncpg://" + value.removeprefix(prefix)
    if not value.startswith("postgresql+asyncpg://"):
        raise ValueError("DATABASE_URL must be a PostgreSQL URL (postgresql+asyncpg://...)")
    return value


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """All runtime configuration. Secrets are never hardcoded; see `.env.example`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- application -------------------------------------------------------------
    app_name: str = "TaskForge API"
    app_version: str = "1.0.0"
    environment: Environment = Environment.DEVELOPMENT
    api_v1_prefix: str = "/api/v1"
    docs_enabled: bool = True
    max_request_body_bytes: int = Field(default=1_048_576, ge=1024)

    # --- logging -----------------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = True

    # --- database (PostgreSQL only) -------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/taskdb",
        description="SQLAlchemy async URL, must use the postgresql+asyncpg driver.",
    )
    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_pool_timeout: float = Field(default=30.0, gt=0)
    db_pool_recycle: int = Field(default=1800, ge=-1)
    db_echo: bool = False
    db_statement_timeout_ms: int = Field(default=15000, ge=0)

    # --- auth / JWT --------------------------------------------------------------
    jwt_secret_key: SecretStr = Field(..., description="HMAC secret, >= 32 chars.")
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_issuer: str = "taskforge-api"
    jwt_audience: str = "taskforge-api"
    access_token_expire_minutes: int = Field(default=15, ge=1, le=1440)
    refresh_token_expire_days: int = Field(default=14, ge=1, le=365)
    require_account_activation: bool = Field(
        default=False,
        description="If true, new accounts stay inactive until an admin activates them.",
    )

    # --- CORS --------------------------------------------------------------------
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    cors_allow_credentials: bool = False

    # --- redis / rate limiting ---------------------------------------------------
    redis_url: str | None = Field(
        default=None,
        description="Optional. When unset (or unreachable) an in-process limiter is used.",
    )
    rate_limit_enabled: bool = True
    login_rate_limit: int = Field(default=5, ge=1, description="Attempts per window per IP.")
    login_rate_limit_window_seconds: int = Field(default=60, ge=1)
    register_rate_limit: int = Field(default=10, ge=1)
    register_rate_limit_window_seconds: int = Field(default=3600, ge=1)
    refresh_rate_limit: int = Field(default=30, ge=1)
    refresh_rate_limit_window_seconds: int = Field(default=60, ge=1)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []
            if value.startswith("["):
                import json

                return json.loads(value)
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("database_url")
    @classmethod
    def _require_asyncpg(cls, value: str) -> str:
        return normalize_database_url(value)

    @field_validator("jwt_secret_key")
    @classmethod
    def _secret_strength(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters long")
        return value

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.environment == Environment.PRODUCTION and "*" in self.cors_origins:
            raise ValueError("Wildcard CORS origin is not allowed in production")
        if self.cors_allow_credentials and "*" in self.cors_origins:
            raise ValueError("CORS credentials cannot be combined with a wildcard origin")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
