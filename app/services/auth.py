"""Authentication use-cases: register, login, refresh-token rotation, logout, token checks."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AuthenticationError, ConflictError, PermissionDeniedError
from app.core.security import (
    AccessTokenClaims,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    password_needs_rehash,
    verify_password,
)
from app.models import AuthSession, User, UserRole
from app.repositories.auth_session import AuthSessionRepository
from app.repositories.user import UserRepository
from app.schemas.auth import TokenPair
from app.schemas.user import UserCreate

logger = logging.getLogger(__name__)
security_log = logging.getLogger("app.security")


class RevocationReason:
    LOGOUT = "logout"
    LOGOUT_ALL = "logout_all"
    REUSE_DETECTED = "refresh_token_reuse"
    PASSWORD_CHANGED = "password_changed"  # noqa: S105 - reason label, not a secret
    ACCOUNT_DEACTIVATED = "account_deactivated"


@dataclass(frozen=True, slots=True)
class ClientInfo:
    ip_address: str | None = None
    user_agent: str | None = None


@dataclass(frozen=True, slots=True)
class AuthContext:
    """The authenticated principal for the current request."""

    user: User
    session_id: uuid.UUID


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.sessions = AuthSessionRepository(session)

    # ------------------------------------------------------------------ registration
    async def register(self, data: UserCreate) -> User:
        if await self.users.email_exists(data.email):
            raise ConflictError("Email is already registered", code="email_taken")
        user = User(
            email=data.email,
            password_hash=hash_password(data.password),
            full_name=data.full_name,
            role=UserRole.USER,
            is_active=not self.settings.require_account_activation,
        )
        try:
            await self.users.add(user)
            await self.session.commit()
        except IntegrityError as exc:  # concurrent registration with the same e-mail
            await self.session.rollback()
            raise ConflictError("Email is already registered", code="email_taken") from exc
        logger.info("user registered", extra={"user_id": str(user.id)})
        return user

    # ------------------------------------------------------------------ login
    async def login(self, email: str, password: str, client: ClientInfo) -> TokenPair:
        user = await self.users.get_by_email(email)
        # verify_password always runs Argon2 (dummy hash for unknown users) to avoid
        # leaking account existence through response timing.
        if not verify_password(password, user.password_hash if user else None) or user is None:
            security_log.info("login failed", extra={"ip": client.ip_address})
            raise AuthenticationError("Incorrect email or password", code="invalid_credentials")
        if not user.is_active:
            raise PermissionDeniedError("Account is not active", code="account_inactive")

        now = datetime.now(UTC)
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        user.last_login_at = now
        auth_session = await self.sessions.create_session(
            user_id=user.id, user_agent=client.user_agent, ip_address=client.ip_address
        )
        tokens = await self._issue_tokens(user, auth_session, now)
        await self.session.commit()
        logger.info(
            "user logged in",
            extra={"user_id": str(user.id), "session_id": str(auth_session.id)},
        )
        return tokens

    # ------------------------------------------------------------------ refresh / rotation
    async def refresh(self, raw_refresh_token: str) -> TokenPair:
        now = datetime.now(UTC)
        token = await self.sessions.get_refresh_token_for_update(
            hash_refresh_token(raw_refresh_token)
        )
        if token is None:
            raise AuthenticationError("Invalid refresh token", code="invalid_refresh_token")

        auth_session = token.session
        user = auth_session.user

        if token.used_at is not None:
            # A rotated token was presented again: it has probably been stolen. Revoke the
            # whole family so that neither the attacker nor the victim can keep using it.
            await self.sessions.revoke_session(
                auth_session.id, reason=RevocationReason.REUSE_DETECTED, at=now
            )
            await self.session.commit()
            security_log.warning(
                "refresh token reuse detected; session revoked",
                extra={"user_id": str(user.id), "session_id": str(auth_session.id)},
            )
            raise AuthenticationError(
                "Refresh token has already been used", code="refresh_token_reused"
            )
        if auth_session.is_revoked:
            raise AuthenticationError("Session has been revoked", code="session_revoked")
        if token.expires_at <= now:
            raise AuthenticationError("Refresh token has expired", code="refresh_token_expired")
        if not user.is_active:
            raise PermissionDeniedError("Account is not active", code="account_inactive")

        token.used_at = now
        auth_session.last_used_at = now
        tokens = await self._issue_tokens(user, auth_session, now)
        await self.session.commit()
        return tokens

    # ------------------------------------------------------------------ logout
    async def logout(self, ctx: AuthContext, *, all_sessions: bool = False) -> None:
        now = datetime.now(UTC)
        if all_sessions:
            await self.sessions.revoke_all_for_user(
                ctx.user.id, reason=RevocationReason.LOGOUT_ALL, at=now
            )
        else:
            await self.sessions.revoke_session(
                ctx.session_id, reason=RevocationReason.LOGOUT, at=now
            )
        await self.session.commit()
        logger.info(
            "user logged out",
            extra={"user_id": str(ctx.user.id), "all_sessions": all_sessions},
        )

    # ------------------------------------------------------------------ access-token check
    async def authenticate(self, access_token: str) -> AuthContext:
        claims: AccessTokenClaims = decode_access_token(self.settings, access_token)
        found = await self.sessions.get_session_with_user(claims.session_id)
        if found is None:
            raise AuthenticationError("Session not found", code="invalid_token")
        auth_session, user = found
        if auth_session.user_id != claims.subject:
            raise AuthenticationError("Invalid access token", code="invalid_token")
        if auth_session.is_revoked:
            raise AuthenticationError("Session has been revoked", code="session_revoked")
        if not user.is_active:
            raise PermissionDeniedError("Account is not active", code="account_inactive")
        return AuthContext(user=user, session_id=auth_session.id)

    # ------------------------------------------------------------------ helpers
    async def _issue_tokens(
        self, user: User, auth_session: AuthSession, now: datetime
    ) -> TokenPair:
        refresh_lifetime = timedelta(days=self.settings.refresh_token_expire_days)
        raw_refresh = generate_refresh_token()
        await self.sessions.add_refresh_token(
            session_id=auth_session.id,
            token_hash=hash_refresh_token(raw_refresh),
            expires_at=now + refresh_lifetime,
        )
        access_token, expires_in = create_access_token(
            self.settings,
            user_id=user.id,
            session_id=auth_session.id,
            role=user.role.value,
            now=now,
        )
        return TokenPair(
            access_token=access_token,
            refresh_token=raw_refresh,
            expires_in=expires_in,
            refresh_expires_in=int(refresh_lifetime.total_seconds()),
        )
