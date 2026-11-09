from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import AuthServiceDep, ClientInfoDep, CurrentAuth, rate_limit
from app.schemas.auth import LoginRequest, RefreshRequest, TokenPair
from app.schemas.common import ERROR_RESPONSES
from app.schemas.user import UserCreate, UserRead

router = APIRouter(prefix="/auth", tags=["auth"], responses={422: ERROR_RESPONSES[422]})


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account",
    responses={409: ERROR_RESPONSES[409], 429: ERROR_RESPONSES[429]},
    dependencies=[
        Depends(rate_limit("register", "register_rate_limit", "register_rate_limit_window_seconds"))
    ],
)
async def register(payload: UserCreate, auth: AuthServiceDep) -> UserRead:
    user = await auth.register(payload)
    return UserRead.model_validate(user)


@router.post(
    "/login",
    response_model=TokenPair,
    summary="Exchange credentials for an access/refresh token pair",
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403], 429: ERROR_RESPONSES[429]},
    dependencies=[
        Depends(rate_limit("login", "login_rate_limit", "login_rate_limit_window_seconds"))
    ],
)
async def login(payload: LoginRequest, auth: AuthServiceDep, client: ClientInfoDep) -> TokenPair:
    return await auth.login(payload.email, payload.password, client)


@router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Rotate a refresh token (reuse of a rotated token revokes the session)",
    responses={401: ERROR_RESPONSES[401], 429: ERROR_RESPONSES[429]},
    dependencies=[
        Depends(rate_limit("refresh", "refresh_rate_limit", "refresh_rate_limit_window_seconds"))
    ],
)
async def refresh(payload: RefreshRequest, auth: AuthServiceDep) -> TokenPair:
    return await auth.refresh(payload.refresh_token)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke the current session (or all sessions) and its tokens",
    responses={401: ERROR_RESPONSES[401]},
)
async def logout(
    ctx: CurrentAuth,
    auth: AuthServiceDep,
    all_sessions: bool = Query(default=False, description="Sign out from every device"),
) -> Response:
    await auth.logout(ctx, all_sessions=all_sessions)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
