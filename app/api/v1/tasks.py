from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentAuth, TaskServiceDep
from app.core.exceptions import AppError
from app.models import TaskPriority, TaskStatus
from app.schemas.common import ERROR_RESPONSES, NO_NUL_PATTERN, Page
from app.schemas.task import DueDate, TaskCreate, TaskFilters, TaskRead, TaskUpdate, parse_sort

router = APIRouter(
    prefix="/tasks",
    tags=["tasks"],
    responses={400: ERROR_RESPONSES[400], 401: ERROR_RESPONSES[401], 422: ERROR_RESPONSES[422]},
)


@router.post(
    "",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a task owned by the current user",
)
async def create_task(payload: TaskCreate, ctx: CurrentAuth, tasks: TaskServiceDep) -> TaskRead:
    return TaskRead.model_validate(await tasks.create(ctx.user, payload))


@router.get(
    "",
    response_model=Page[TaskRead],
    summary="List tasks with pagination, filtering, sorting and search",
    responses={400: ERROR_RESPONSES[400], 403: ERROR_RESPONSES[403]},
)
async def list_tasks(
    ctx: CurrentAuth,
    tasks: TaskServiceDep,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[
        list[TaskStatus] | None, Query(alias="status", description="Repeatable")
    ] = None,
    priority: Annotated[list[TaskPriority] | None, Query(description="Repeatable")] = None,
    q: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=100,
            pattern=NO_NUL_PATTERN,
            description="Search title/description",
        ),
    ] = None,
    due_before: DueDate | None = None,
    due_after: DueDate | None = None,
    owner_id: Annotated[uuid.UUID | None, Query(description="Admin only")] = None,
    sort: Annotated[
        str | None,
        Query(
            max_length=100,
            description="Comma-separated fields, '-' prefix for descending. "
            "Fields: created_at, updated_at, due_date, priority, status, title.",
            examples=["-priority,due_date"],
        ),
    ] = None,
) -> Page[TaskRead]:
    try:
        sort_keys = parse_sort(sort)
    except ValueError as exc:
        raise AppError(
            "Invalid sort parameter",
            code="validation_error",
            details=[{"field": "sort", "location": "query", "message": str(exc)}],
        ) from exc
    if due_before and due_after and due_after > due_before:
        raise AppError(
            "Invalid date range",
            code="validation_error",
            details=[
                {"field": "due_after", "location": "query", "message": "must be <= due_before"}
            ],
        )
    filters = TaskFilters(
        status=status_filter or [],
        priority=priority or [],
        search=q,
        due_before=due_before,
        due_after=due_after,
        owner_id=owner_id,
        sort=sort_keys,
    )
    return await tasks.list(ctx.user, filters, page=page, page_size=page_size)


@router.get(
    "/{task_id}",
    response_model=TaskRead,
    summary="Get a task",
    responses={404: ERROR_RESPONSES[404]},
)
async def get_task(task_id: uuid.UUID, ctx: CurrentAuth, tasks: TaskServiceDep) -> TaskRead:
    return TaskRead.model_validate(await tasks.get(ctx.user, task_id))


@router.patch(
    "/{task_id}",
    response_model=TaskRead,
    summary="Partially update a task",
    responses={404: ERROR_RESPONSES[404]},
)
async def update_task(
    task_id: uuid.UUID, payload: TaskUpdate, ctx: CurrentAuth, tasks: TaskServiceDep
) -> TaskRead:
    return TaskRead.model_validate(await tasks.update(ctx.user, task_id, payload))


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a task",
    responses={404: ERROR_RESPONSES[404]},
)
async def delete_task(task_id: uuid.UUID, ctx: CurrentAuth, tasks: TaskServiceDep) -> Response:
    await tasks.delete(ctx.user, task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
