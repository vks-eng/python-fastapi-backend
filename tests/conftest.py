"""Test fixtures.

Database strategy (PostgreSQL only):
* If ``TEST_DATABASE_URL`` is set (CI uses a Postgres service container), it is used.
* Otherwise a throw-away PostgreSQL instance is started with ``pgserver`` (embedded
  binaries, dev-only dependency) in a temporary directory.

The schema is created by running the real Alembic migrations once per session.
Each test runs inside an outer transaction that is rolled back afterwards; services'
``commit()`` calls only release SAVEPOINTs (``join_transaction_mode="create_savepoint"``),
so tests are fully isolated without truncation.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.api.deps import get_db_session
from app.core.config import Settings, normalize_database_url
from app.core.security import hash_password
from app.main import create_app
from app.models import User, UserRole

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEST_JWT_SECRET = "test-secret-key-that-is-long-enough-0123456789"
DEFAULT_PASSWORD = "Sup3r-Secret-pw"


_LAYER_MARKERS = ("unit", "integration", "e2e", "contract")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Tag every test with its layer marker based on the folder it lives in."""
    for item in items:
        parts = Path(str(item.fspath)).parts
        for layer in _LAYER_MARKERS:
            if layer in parts:
                item.add_marker(getattr(pytest.mark, layer))


# --------------------------------------------------------------------------- database
@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        yield normalize_database_url(url)
        return

    try:
        import pgserver  # dev-only dependency
    except ImportError:  # pragma: no cover - depends on environment
        pytest.exit(
            "No PostgreSQL available: set TEST_DATABASE_URL or install the dev "
            "dependency 'pgserver'.",
            returncode=4,
        )
    data_dir = tempfile.mkdtemp(prefix="taskapi-pg-")
    server = pgserver.get_server(data_dir, cleanup_mode="stop")
    try:
        yield normalize_database_url(server.get_uri())
    finally:
        server.cleanup()
        shutil.rmtree(data_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def migrated_database(database_url: str) -> str:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    cfg.attributes["skip_logging_config"] = True
    # Exercise both directions of the migration, then leave the schema at head.
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    return database_url


@pytest.fixture(scope="session")
async def engine(migrated_database: str) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(migrated_database, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            autoflush=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


# --------------------------------------------------------------------------- app / client
def make_settings(database_url: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": database_url,
        "jwt_secret_key": TEST_JWT_SECRET,
        "environment": "test",
        "log_level": "WARNING",
        "log_json": True,
        "redis_url": None,
        "login_rate_limit": 1000,
        "register_rate_limit": 1000,
        "refresh_rate_limit": 1000,
        "db_pool_size": 1,
        "db_max_overflow": 0,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.fixture
def settings(migrated_database: str) -> Settings:
    return make_settings(migrated_database)


AppFactory = Callable[..., Awaitable[AsyncClient]]


@pytest.fixture
async def client_factory(
    migrated_database: str, db_session: AsyncSession
) -> AsyncIterator[AppFactory]:
    """Build an app (optionally with settings overrides) bound to the test transaction."""
    clients: list[AsyncClient] = []
    apps: list[Any] = []

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    async def factory(raise_app_exceptions: bool = True, **overrides: Any) -> AsyncClient:
        app = create_app(make_settings(migrated_database, **overrides))
        app.dependency_overrides[get_db_session] = _override_session
        transport = ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
        client = AsyncClient(transport=transport, base_url="http://testserver")
        clients.append(client)
        apps.append(app)
        return client

    yield factory
    for client in clients:
        await client.aclose()
    for app in apps:
        await app.state.db.dispose()
        await app.state.rate_limiter.close()


@pytest.fixture
async def client(client_factory: AppFactory) -> AsyncClient:
    return await client_factory()


# --------------------------------------------------------------------------- data helpers
UserFactory = Callable[..., Awaitable[User]]


@pytest.fixture
def user_factory(db_session: AsyncSession) -> UserFactory:
    async def factory(
        *,
        email: str | None = None,
        password: str = DEFAULT_PASSWORD,
        role: UserRole = UserRole.USER,
        is_active: bool = True,
        full_name: str | None = "Test User",
    ) -> User:
        user = User(
            email=email or f"user-{uuid.uuid4().hex[:10]}@example.com",
            password_hash=hash_password(password),
            role=role,
            is_active=is_active,
            full_name=full_name,
        )
        db_session.add(user)
        await db_session.flush()
        await db_session.refresh(user)
        return user

    return factory


async def login(client: AsyncClient, email: str, password: str = DEFAULT_PASSWORD) -> dict:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def bearer(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.fixture
async def user(user_factory: UserFactory) -> User:
    return await user_factory(email="alice@example.com")


@pytest.fixture
async def other_user(user_factory: UserFactory) -> User:
    return await user_factory(email="bob@example.com")


@pytest.fixture
async def admin(user_factory: UserFactory) -> User:
    return await user_factory(email="admin@example.com", role=UserRole.ADMIN)


@pytest.fixture
async def user_tokens(client: AsyncClient, user: User) -> dict:
    return await login(client, user.email)


@pytest.fixture
async def auth_headers(user_tokens: dict) -> dict[str, str]:
    return bearer(user_tokens)


@pytest.fixture
async def other_headers(client: AsyncClient, other_user: User) -> dict[str, str]:
    return bearer(await login(client, other_user.email))


@pytest.fixture
async def admin_headers(client: AsyncClient, admin: User) -> dict[str, str]:
    return bearer(await login(client, admin.email))
