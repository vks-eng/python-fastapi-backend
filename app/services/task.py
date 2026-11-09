"""Task use-cases with ownership-based authorization."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models import Task, TaskStatus, User
from app.repositories.task import TaskRepository
from app.schemas.common import Page, PageMeta
from app.schemas.task import TaskCreate, TaskFilters, TaskRead, TaskUpdate

logger = logging.getLogger(__name__)


def _apply_status(task: Task, status: TaskStatus, now: datetime) -> None:
    task.status = status
    task.completed_at = now if status == TaskStatus.DONE else None


class TaskService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.tasks = TaskRepository(session)

    async def create(self, user: User, data: TaskCreate) -> Task:
        task = Task(
            owner_id=user.id,
            title=data.title,
            description=data.description,
            priority=data.priority,
            due_date=data.due_date,
        )
        _apply_status(task, data.status, datetime.now(UTC))
        await self.tasks.add(task)
        await self.session.commit()
        logger.info("task created", extra={"task_id": str(task.id), "user_id": str(user.id)})
        return task

    async def get(self, user: User, task_id: uuid.UUID) -> Task:
        task = await self.tasks.get(task_id)
        # Non-owners get 404 rather than 403 so task ids cannot be probed for existence.
        if task is None or (task.owner_id != user.id and not user.is_admin):
            raise NotFoundError("Task not found", code="task_not_found")
        return task

    async def list(
        self, user: User, filters: TaskFilters, *, page: int, page_size: int
    ) -> Page[TaskRead]:
        if not user.is_admin:
            if filters.owner_id is not None and filters.owner_id != user.id:
                raise PermissionDeniedError("You may only list your own tasks")
            filters.owner_id = user.id
        items, total = await self.tasks.list(
            filters, offset=(page - 1) * page_size, limit=page_size
        )
        return Page[TaskRead](
            items=[TaskRead.model_validate(t) for t in items],
            meta=PageMeta.build(page=page, page_size=page_size, total=total),
        )

    async def update(self, user: User, task_id: uuid.UUID, data: TaskUpdate) -> Task:
        task = await self.get(user, task_id)
        changes = data.model_dump(exclude_unset=True)
        status = changes.pop("status", None)
        for field, value in changes.items():
            setattr(task, field, value)
        if status is not None and status != task.status:
            _apply_status(task, status, datetime.now(UTC))
        await self.tasks.refresh(task)
        await self.session.commit()
        return task

    async def delete(self, user: User, task_id: uuid.UUID) -> None:
        task = await self.get(user, task_id)
        await self.tasks.delete(task)
        await self.session.commit()
        logger.info("task deleted", extra={"task_id": str(task_id), "user_id": str(user.id)})
