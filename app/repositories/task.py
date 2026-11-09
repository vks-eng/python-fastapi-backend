from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task
from app.repositories.utils import escape_like
from app.schemas.task import TaskFilters

_SORT_COLUMNS: dict[str, Any] = {
    "created_at": Task.created_at,
    "updated_at": Task.updated_at,
    "due_date": Task.due_date,
    "priority": Task.priority,  # native PG enum: sorts low < medium < high < urgent
    "status": Task.status,
    "title": Task.title,
}


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, task_id: uuid.UUID) -> Task | None:
        return await self.session.get(Task, task_id)

    async def add(self, task: Task) -> Task:
        self.session.add(task)
        await self.session.flush()
        await self.session.refresh(task)
        return task

    async def delete(self, task: Task) -> None:
        await self.session.delete(task)
        await self.session.flush()

    async def refresh(self, task: Task) -> Task:
        await self.session.flush()
        await self.session.refresh(task)
        return task

    @staticmethod
    def _conditions(filters: TaskFilters) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = []
        if filters.owner_id is not None:
            conditions.append(Task.owner_id == filters.owner_id)
        if filters.status:
            conditions.append(Task.status.in_(filters.status))
        if filters.priority:
            conditions.append(Task.priority.in_(filters.priority))
        if filters.due_before is not None:
            conditions.append(Task.due_date < filters.due_before)
        if filters.due_after is not None:
            conditions.append(Task.due_date >= filters.due_after)
        if filters.search:
            pattern = f"%{escape_like(filters.search)}%"
            conditions.append(
                or_(
                    Task.title.ilike(pattern, escape="\\"),
                    Task.description.ilike(pattern, escape="\\"),
                )
            )
        return conditions

    async def list(
        self, filters: TaskFilters, *, offset: int, limit: int
    ) -> tuple[Sequence[Task], int]:
        conditions = self._conditions(filters)
        total = await self.session.scalar(select(func.count(Task.id)).where(*conditions))

        order_by = []
        for key in filters.sort:
            column = _SORT_COLUMNS[key.field]
            order_by.append(
                column.desc().nulls_last() if key.descending else column.asc().nulls_last()
            )
        order_by.append(Task.id.asc())  # deterministic tiebreaker for stable pagination

        result = await self.session.execute(
            select(Task).where(*conditions).order_by(*order_by).offset(offset).limit(limit)
        )
        return result.scalars().all(), int(total or 0)
