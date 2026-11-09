"""Management commands and application lifespan.

These tests commit through their own engine (outside the per-test transaction), so they
clean up the rows they create explicitly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app import cli
from app.main import create_app
from app.models import Task, User, UserRole
from tests.conftest import make_settings

CLI_EMAILS = [cli.DEMO_ADMIN_EMAIL, cli.DEMO_USER_EMAIL, "root@example.com"]


@pytest.fixture
async def cleanup(engine: AsyncEngine) -> AsyncIterator[None]:
    yield
    async with engine.begin() as conn:
        await conn.execute(delete(User).where(User.email.in_(CLI_EMAILS)))


async def test_create_admin_creates_then_promotes(
    migrated_database: str, engine: AsyncEngine, cleanup: None
) -> None:
    settings = make_settings(migrated_database)
    assert await cli.create_admin("root@example.com", "R00t-password", "Root", settings) == 0
    async with engine.connect() as conn:
        role = await conn.scalar(select(User.role).where(User.email == "root@example.com"))
    assert role == UserRole.ADMIN

    async with engine.begin() as conn:
        await conn.execute(
            User.__table__.update()
            .where(User.email == "root@example.com")
            .values(role=UserRole.USER, is_active=False)
        )
    assert await cli.create_admin("root@example.com", "ignored-1", None, settings) == 0
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                select(User.role, User.is_active).where(User.email == "root@example.com")
            )
        ).one()
    assert row == (UserRole.ADMIN, True)


async def test_seed_is_idempotent(
    migrated_database: str, engine: AsyncEngine, cleanup: None
) -> None:
    settings = make_settings(migrated_database)
    assert await cli.seed(settings) == 0
    assert await cli.seed(settings) == 0
    async with engine.connect() as conn:
        users = await conn.scalar(select(func.count(User.id)).where(User.email.in_(CLI_EMAILS)))
        tasks = await conn.scalar(
            select(func.count(Task.id))
            .join(User, User.id == Task.owner_id)
            .where(User.email == cli.DEMO_USER_EMAIL)
        )
    assert users == 2
    assert tasks == len(cli._DEMO_TASKS)


async def test_seed_refuses_production(migrated_database: str) -> None:
    settings = make_settings(migrated_database, environment="production")
    assert await cli.seed(settings) == 3


def test_create_admin_rejects_weak_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "weak")
    assert cli.main(["create-admin", "--email", "root@example.com"]) == 2


def test_create_admin_rejects_invalid_email(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "G00d-password")
    assert cli.main(["create-admin", "--email", "not-an-email"]) == 2


async def test_lifespan_startup_and_shutdown(migrated_database: str) -> None:
    app = create_app(make_settings(migrated_database))
    async with app.router.lifespan_context(app):
        await app.state.db.ping()
