"""FastAPI dependencies: settings, DB session, services, authentication and rate limiting."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError, RateLimitExceededError
from app.core.rate_limit import RateLimiter
from app.db.session import Database
from app.services.auth import AuthContext, AuthService, ClientInfo
from app.services.task import TaskService
from app.services.user import UserService

_bearer = HTTPBearer(auto_error=False, description="JWT access token from /auth/login")


def get_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def get_database(request: Request) -> Database:
    return request.app.state.db  # type: ignore[no-any-return]


async def get_db_session(
    db: Annotated[Database, Depends(get_database)],
) -> AsyncIterator[AsyncSession]:
    async for session in db.session():
        yield session


def get_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter  # type: ignore[no-any-return]


def get_client_info(request: Request) -> ClientInfo:
    return ClientInfo(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
ClientInfoDep = Annotated[ClientInfo, Depends(get_client_info)]


def get_auth_service(session: DbSession, settings: SettingsDep) -> AuthService:
    return AuthService(session, settings)


def get_user_service(session: DbSession) -> UserService:
    return UserService(session)


def get_task_service(session: DbSession) -> TaskService:
    return TaskService(session)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]


async def get_auth_context(
    auth: AuthServiceDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Not authenticated", code="not_authenticated")
    return await auth.authenticate(credentials.credentials)


CurrentAuth = Annotated[AuthContext, Depends(get_auth_context)]


async def require_admin(ctx: CurrentAuth) -> AuthContext:
    if not ctx.user.is_admin:
        raise PermissionDeniedError("Administrator privileges required")
    return ctx


AdminAuth = Annotated[AuthContext, Depends(require_admin)]


def rate_limit(
    scope: str, limit_setting: str, window_setting: str
) -> Callable[..., Awaitable[None]]:
    """Per-client-IP fixed-window limit; limits are read from settings at request time."""

    async def _dependency(
        settings: SettingsDep,
        limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
        client: ClientInfoDep,
    ) -> None:
        if not settings.rate_limit_enabled:
            return
        limit: int = getattr(settings, limit_setting)
        window: int = getattr(settings, window_setting)
        result = await limiter.hit(f"{scope}:{client.ip_address or 'unknown'}", limit, window)
        if not result.allowed:
            raise RateLimitExceededError(retry_after=result.retry_after)

    return _dependency
