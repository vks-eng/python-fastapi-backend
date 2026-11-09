from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserRole
from app.repositories.utils import escape_like


class UserRepository:
    """Data access for users. Never commits: transaction boundaries belong to services."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email.lower()))
        return result.scalar_one_or_none()

    async def email_exists(self, email: str) -> bool:
        result = await self.session.execute(
            select(select(User.id).where(User.email == email.lower()).exists())
        )
        return bool(result.scalar())

    async def add(self, user: User) -> User:
        self.session.add(user)
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def list(
        self,
        *,
        offset: int,
        limit: int,
        role: UserRole | None = None,
        is_active: bool | None = None,
        search: str | None = None,
    ) -> tuple[Sequence[User], int]:
        conditions = []
        if role is not None:
            conditions.append(User.role == role)
        if is_active is not None:
            conditions.append(User.is_active == is_active)
        if search:
            pattern = f"%{escape_like(search)}%"
            conditions.append(
                or_(
                    User.email.ilike(pattern, escape="\\"),
                    User.full_name.ilike(pattern, escape="\\"),
                )
            )
        total = await self.session.scalar(select(func.count(User.id)).where(*conditions))
        result = await self.session.execute(
            select(User)
            .where(*conditions)
            .order_by(User.created_at.desc(), User.id)
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all(), int(total or 0)
