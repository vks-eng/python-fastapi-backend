"""Management commands.

    python -m app.cli create-admin --email admin@example.com
    python -m app.cli seed            # LOCAL/DEV ONLY: demo users + sample tasks

``create-admin`` reads the password from the ``ADMIN_PASSWORD`` environment variable or
prompts for it (never pass passwords as CLI arguments: they end up in shell history).

``seed`` creates well-known demo credentials and therefore refuses to run when
``ENVIRONMENT=production``.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from datetime import UTC, datetime, timedelta

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.security import hash_password
from app.db.session import Database
from app.models import Task, TaskPriority, TaskStatus, User, UserRole
from app.repositories.user import UserRepository
from app.schemas.user import Email, Password

# Demo credentials for local development only. Never use these anywhere real.
DEMO_ADMIN_EMAIL = "admin@example.com"
DEMO_ADMIN_PASSWORD = "Admin-Demo-2026!"  # noqa: S105 - documented local-only demo password
DEMO_USER_EMAIL = "demo@example.com"
DEMO_USER_PASSWORD = "Demo-User-2026!"  # noqa: S105 - documented local-only demo password

_DEMO_TASKS: list[tuple[str, str | None, TaskStatus, TaskPriority, int | None]] = [
    ("Set up CI pipeline", "Lint, test and build on every push", TaskStatus.DONE,
     TaskPriority.HIGH, -2),
    ("Write API documentation", "Document every endpoint with examples",
     TaskStatus.IN_PROGRESS, TaskPriority.MEDIUM, 3),
    ("Review pull requests", None, TaskStatus.TODO, TaskPriority.URGENT, 1),
    ("Plan sprint backlog", "Prioritise next sprint's work", TaskStatus.TODO,
     TaskPriority.LOW, 7),
    ("Rotate production secrets", "Quarterly key rotation", TaskStatus.TODO,
     TaskPriority.HIGH, 14),
    ("Archive old reports", None, TaskStatus.CANCELLED, TaskPriority.LOW, None),
]  # fmt: skip


async def create_admin(
    email: str, password: str, full_name: str | None, settings: Settings | None = None
) -> int:
    db = Database(settings or get_settings())
    try:
        async with db.session_factory() as session:
            repo = UserRepository(session)
            existing = await repo.get_by_email(email)
            if existing is not None:
                existing.role = UserRole.ADMIN
                existing.is_active = True
                await session.commit()
                print(f"Promoted existing user {email} to admin.")
                return 0
            await repo.add(
                User(
                    email=email,
                    password_hash=hash_password(password),
                    full_name=full_name,
                    role=UserRole.ADMIN,
                    is_active=True,
                )
            )
            await session.commit()
            print(f"Created admin user {email}.")
            return 0
    finally:
        await db.dispose()


async def seed(settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    if settings.is_production:
        print("Refusing to seed demo data in production.", file=sys.stderr)
        return 3
    db = Database(settings)
    try:
        async with db.session_factory() as session:
            repo = UserRepository(session)
            users: dict[str, User] = {}
            for email, password, role, name in (
                (DEMO_ADMIN_EMAIL, DEMO_ADMIN_PASSWORD, UserRole.ADMIN, "Demo Admin"),
                (DEMO_USER_EMAIL, DEMO_USER_PASSWORD, UserRole.USER, "Demo User"),
            ):
                user = await repo.get_by_email(email)
                if user is None:
                    user = await repo.add(
                        User(
                            email=email,
                            password_hash=hash_password(password),
                            full_name=name,
                            role=role,
                            is_active=True,
                        )
                    )
                users[email] = user

            demo_user = users[DEMO_USER_EMAIL]
            has_tasks = await session.scalar(
                select(Task.id).where(Task.owner_id == demo_user.id).limit(1)
            )
            created = 0
            if has_tasks is None:
                now = datetime.now(UTC)
                for title, description, status, priority, due_in_days in _DEMO_TASKS:
                    session.add(
                        Task(
                            owner_id=demo_user.id,
                            title=title,
                            description=description,
                            status=status,
                            priority=priority,
                            due_date=now + timedelta(days=due_in_days)
                            if due_in_days is not None
                            else None,
                            completed_at=now if status == TaskStatus.DONE else None,
                        )
                    )
                    created += 1
            await session.commit()
        print(f"Seeded demo users ({DEMO_ADMIN_EMAIL}, {DEMO_USER_EMAIL}) and {created} tasks.")
        return 0
    finally:
        await db.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="Create (or promote) an administrator")
    admin.add_argument("--email", required=True)
    admin.add_argument("--full-name", default=None)
    sub.add_parser("seed", help="Load demo users and tasks (local/dev only)")
    args = parser.parse_args(argv)

    if args.command == "seed":
        return asyncio.run(seed())

    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
    try:
        email = TypeAdapter(Email).validate_python(args.email)
        TypeAdapter(Password).validate_python(password)
    except ValidationError as exc:
        print(f"Invalid input: {exc.errors()[0]['msg']}", file=sys.stderr)
        return 2
    return asyncio.run(create_admin(email, password, args.full_name))


if __name__ == "__main__":
    raise SystemExit(main())
