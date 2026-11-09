from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models import AuthSession, RefreshToken, User


class AuthSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_session(
        self, *, user_id: uuid.UUID, user_agent: str | None, ip_address: str | None
    ) -> AuthSession:
        auth_session = AuthSession(
            user_id=user_id,
            user_agent=(user_agent or "")[:255] or None,
            ip_address=ip_address,
        )
        self.session.add(auth_session)
        await self.session.flush()
        return auth_session

    async def get_session_with_user(self, session_id: uuid.UUID) -> tuple[AuthSession, User] | None:
        result = await self.session.execute(
            select(AuthSession, User)
            .join(User, User.id == AuthSession.user_id)
            .where(AuthSession.id == session_id)
        )
        row = result.one_or_none()
        return (row[0], row[1]) if row else None

    async def add_refresh_token(
        self, *, session_id: uuid.UUID, token_hash: str, expires_at: datetime
    ) -> RefreshToken:
        token = RefreshToken(session_id=session_id, token_hash=token_hash, expires_at=expires_at)
        self.session.add(token)
        await self.session.flush()
        return token

    async def get_refresh_token_for_update(self, token_hash: str) -> RefreshToken | None:
        """Lock the token row so concurrent refreshes with the same token serialise."""
        result = await self.session.execute(
            select(RefreshToken)
            .options(joinedload(RefreshToken.session).joinedload(AuthSession.user))
            .where(RefreshToken.token_hash == token_hash)
            .with_for_update(of=RefreshToken)
        )
        return result.unique().scalar_one_or_none()

    async def revoke_session(self, session_id: uuid.UUID, *, reason: str, at: datetime) -> None:
        await self.session.execute(
            update(AuthSession)
            .where(AuthSession.id == session_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=at, revoked_reason=reason)
        )

    async def revoke_all_for_user(
        self,
        user_id: uuid.UUID,
        *,
        reason: str,
        at: datetime,
        except_session_id: uuid.UUID | None = None,
    ) -> None:
        stmt = (
            update(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=at, revoked_reason=reason)
        )
        if except_session_id is not None:
            stmt = stmt.where(AuthSession.id != except_session_id)
        await self.session.execute(stmt)
