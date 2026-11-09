"""Configuration testing: Settings validation across environment combinations."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings, normalize_database_url
from app.core.rate_limit import InMemoryRateLimiter, RedisRateLimiter, build_rate_limiter

SECRET = "s" * 40


def make(**values) -> Settings:
    return Settings(_env_file=None, **{"jwt_secret_key": SECRET, **values})  # type: ignore[call-arg]


def test_defaults_are_safe() -> None:
    settings = make()
    assert settings.environment == "development"
    assert settings.cors_origins == []
    assert settings.cors_allow_credentials is False
    assert settings.redis_url is None
    assert settings.access_token_expire_minutes == 15
    assert settings.rate_limit_enabled is True


def test_jwt_secret_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    with pytest.raises(ValidationError, match="jwt_secret_key"):
        Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.parametrize(("length", "valid"), [(31, False), (32, True)])
def test_jwt_secret_minimum_length(length: int, valid: bool) -> None:
    if valid:
        make(jwt_secret_key="k" * length)
    else:
        with pytest.raises(ValidationError, match="at least 32"):
            make(jwt_secret_key="k" * length)


def test_secret_is_masked_in_repr() -> None:
    assert SECRET not in repr(make())
    assert SECRET not in str(make().model_dump())


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("postgres://u:p@h:5432/db", "postgresql+asyncpg://u:p@h:5432/db"),
        ("postgresql://u@h/db", "postgresql+asyncpg://u@h/db"),
        ("postgresql+asyncpg://u@h/db", "postgresql+asyncpg://u@h/db"),
    ],
)
def test_database_url_normalisation(raw: str, expected: str) -> None:
    assert normalize_database_url(raw) == expected
    assert make(database_url=raw).database_url == expected


@pytest.mark.parametrize(
    "raw", ["sqlite+aiosqlite:///x.db", "mysql://u@h/db", "postgresql+psycopg2://u@h/db", ""]
)
def test_non_postgres_urls_rejected(raw: str) -> None:
    with pytest.raises(ValidationError, match="PostgreSQL"):
        make(database_url=raw)


@pytest.mark.parametrize(
    ("environment", "origins", "credentials", "valid"),
    [
        ("production", "*", False, False),  # wildcard in prod
        ("production", "https://app.example.com", True, True),
        ("development", "*", False, True),  # allowed outside prod
        ("development", "*", True, False),  # credentials + wildcard never allowed
        ("staging", "https://a.com,https://b.com", False, True),
    ],
)
def test_cors_combinations(environment: str, origins: str, credentials: bool, valid: bool) -> None:
    values = {
        "environment": environment,
        "cors_origins": origins,
        "cors_allow_credentials": credentials,
    }
    if valid:
        make(**values)
    else:
        with pytest.raises(ValidationError):
            make(**values)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", []),
        ("https://a.com", ["https://a.com"]),
        (" https://a.com , https://b.com ", ["https://a.com", "https://b.com"]),
        ('["https://c.com"]', ["https://c.com"]),
    ],
)
def test_cors_origin_parsing(raw: str, expected: list[str]) -> None:
    assert make(cors_origins=raw).cors_origins == expected


def test_settings_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET_KEY", SECRET)
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("CORS_ORIGINS", "https://x.com,https://y.com")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "5")
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@db/app")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.environment == "staging"
    assert settings.cors_origins == ["https://x.com", "https://y.com"]
    assert settings.access_token_expire_minutes == 5
    assert settings.database_url == "postgresql+asyncpg://u:p@db/app"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("access_token_expire_minutes", 0),
        ("refresh_token_expire_days", 0),
        ("login_rate_limit", 0),
        ("db_pool_size", 0),
        ("log_level", "VERBOSE"),
        ("environment", "prod"),
        ("jwt_algorithm", "none"),
        ("max_request_body_bytes", 10),
    ],
)
def test_out_of_range_values_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make(**{field: value})


def test_redis_unset_selects_in_memory_limiter() -> None:
    assert isinstance(build_rate_limiter(make().redis_url), InMemoryRateLimiter)
    assert isinstance(build_rate_limiter(""), InMemoryRateLimiter)


def test_redis_configured_selects_redis_limiter() -> None:
    assert isinstance(build_rate_limiter("redis://localhost:6379/0"), RedisRateLimiter)
