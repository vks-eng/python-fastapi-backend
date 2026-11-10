from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AdminAuth, CurrentAuth, UserServiceDep
from app.models import UserRole
from app.schemas.common import ERROR_RESPONSES, NO_NUL_PATTERN, Page
from app.schemas.user import AdminUserUpdate, UserRead, UserUpdate

router = APIRouter(
    prefix="/users",
    tags=["users"],
    responses={400: ERROR_RESPONSES[400], 401: ERROR_RESPONSES[401], 422: ERROR_RESPONSES[422]},
)


@router.get("/me", response_model=UserRead, summary="Get the current user's profile")
async def read_me(ctx: CurrentAuth) -> UserRead:
    return UserRead.model_validate(ctx.user)


@router.patch(
    "/me",
    response_model=UserRead,
    summary="Update the current user's profile",
    responses={400: ERROR_RESPONSES[400], 409: ERROR_RESPONSES[409]},
)
async def update_me(payload: UserUpdate, ctx: CurrentAuth, users: UserServiceDep) -> UserRead:
    return UserRead.model_validate(await users.update_profile(ctx, payload))


# --------------------------------------------------------------------- admin only
@router.get(
    "",
    response_model=Page[UserRead],
    summary="List users (admin)",
    responses={403: ERROR_RESPONSES[403]},
)
async def list_users(
    _: AdminAuth,
    users: UserServiceDep,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    role: UserRole | None = None,
    is_active: bool | None = None,
    q: Annotated[str | None, Query(min_length=1, max_length=100, pattern=NO_NUL_PATTERN)] = None,
) -> Page[UserRead]:
    return await users.list_users(
        page=page, page_size=page_size, role=role, is_active=is_active, search=q
    )


@router.get(
    "/{user_id}",
    response_model=UserRead,
    summary="Get a user (admin)",
    responses={403: ERROR_RESPONSES[403], 404: ERROR_RESPONSES[404]},
)
async def get_user(user_id: uuid.UUID, _: AdminAuth, users: UserServiceDep) -> UserRead:
    return UserRead.model_validate(await users.get_user(user_id))


@router.patch(
    "/{user_id}",
    response_model=UserRead,
    summary="Activate/deactivate a user or change their role (admin)",
    responses={400: ERROR_RESPONSES[400], 403: ERROR_RESPONSES[403], 404: ERROR_RESPONSES[404]},
)
async def admin_update_user(
    user_id: uuid.UUID, payload: AdminUserUpdate, ctx: AdminAuth, users: UserServiceDep
) -> UserRead:
    return UserRead.model_validate(await users.admin_update(ctx, user_id, payload))
