"""User profile and admin user-management use-cases."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.core.security import hash_password, verify_password
from app.models import User, UserRole
from app.repositories.auth_session import AuthSessionRepository
from app.repositories.user import UserRepository
from app.schemas.common import Page, PageMeta
from app.schemas.user import AdminUserUpdate, UserRead, UserUpdate
from app.services.auth import AuthContext, RevocationReason

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.sessions = AuthSessionRepository(session)

    async def update_profile(self, ctx: AuthContext, data: UserUpdate) -> User:
        user = ctx.user
        fields = data.model_fields_set

        if "email" in fields and data.email and data.email != user.email:
            if await self.users.email_exists(data.email):
                raise ConflictError("Email is already registered", code="email_taken")
            user.email = data.email
        if "full_name" in fields:
            user.full_name = data.full_name
        if data.new_password is not None:
            if not verify_password(data.current_password or "", user.password_hash):
                raise AppError("Current password is incorrect", code="invalid_password")
            user.password_hash = hash_password(data.new_password)
            # Keep the caller's session; sign out every other device.
            await self.sessions.revoke_all_for_user(
                user.id,
                reason=RevocationReason.PASSWORD_CHANGED,
                at=datetime.now(UTC),
                except_session_id=ctx.session_id,
            )
        return await self._commit(user)

    # ------------------------------------------------------------------ admin
    async def list_users(
        self,
        *,
        page: int,
        page_size: int,
        role: UserRole | None,
        is_active: bool | None,
        search: str | None,
    ) -> Page[UserRead]:
        items, total = await self.users.list(
            offset=(page - 1) * page_size,
            limit=page_size,
            role=role,
            is_active=is_active,
            search=search,
        )
        return Page[UserRead](
            items=[UserRead.model_validate(u) for u in items],
            meta=PageMeta.build(page=page, page_size=page_size, total=total),
        )

    async def get_user(self, user_id: uuid.UUID) -> User:
        user = await self.users.get(user_id)
        if user is None:
            raise NotFoundError("User not found")
        return user

    async def admin_update(
        self, actor: AuthContext, user_id: uuid.UUID, data: AdminUserUpdate
    ) -> User:
        user = await self.get_user(user_id)
        fields = data.model_fields_set
        if user.id == actor.user.id and (
            (data.is_active is False) or ("role" in fields and data.role != UserRole.ADMIN)
        ):
            raise AppError(
                "Admins cannot deactivate or demote themselves", code="self_modification"
            )
        if "full_name" in fields:
            user.full_name = data.full_name
        if data.role is not None:
            user.role = data.role
        if data.is_active is not None and data.is_active != user.is_active:
            user.is_active = data.is_active
            if not data.is_active:
                await self.sessions.revoke_all_for_user(
                    user.id, reason=RevocationReason.ACCOUNT_DEACTIVATED, at=datetime.now(UTC)
                )
            logger.info(
                "user activation changed",
                extra={
                    "user_id": str(user.id),
                    "is_active": data.is_active,
                    "actor_id": str(actor.user.id),
                },
            )
        return await self._commit(user)

    async def _commit(self, user: User) -> User:
        try:
            await self.session.flush()
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("Email is already registered", code="email_taken") from exc
        await self.session.refresh(user)
        return user
