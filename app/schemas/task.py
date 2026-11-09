from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BeforeValidator,
    Field,
    model_validator,
)

from app.models.enums import TaskPriority, TaskStatus
from app.schemas.common import (
    NO_NUL_PATTERN,
    NON_BLANK_PATTERN,
    InputModel,
    ORMModel,
    ensure_storable_text,
    strip_non_blank,
)

# Length limits apply to the raw input; surrounding whitespace is then stripped.
Title = Annotated[
    str,
    Field(min_length=1, max_length=200, json_schema_extra={"pattern": NON_BLANK_PATTERN}),
    AfterValidator(strip_non_blank),
]
Description = Annotated[
    str,
    Field(max_length=5000, json_schema_extra={"pattern": NO_NUL_PATTERN}),
    AfterValidator(ensure_storable_text),
]


def _require_iso_string(value: object) -> object:
    # Pydantic would otherwise also accept Unix timestamps; the API contract is ISO-8601.
    if value is not None and not isinstance(value, str | datetime):
        raise ValueError("must be an ISO-8601 date-time string with a timezone offset")
    return value


DueDate = Annotated[AwareDatetime, BeforeValidator(_require_iso_string)]

TASK_SORT_FIELDS = frozenset(
    {"created_at", "updated_at", "due_date", "priority", "status", "title"}
)
MAX_SORT_KEYS = 3


class TaskCreate(InputModel):
    title: Title
    description: Description | None = None
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    due_date: DueDate | None = Field(
        default=None, description="ISO-8601 timestamp with timezone offset"
    )


class TaskUpdate(InputModel):
    """Partial update: only provided fields are changed; `null` clears nullable fields."""

    title: Title | None = None
    description: Description | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_date: DueDate | None = None

    @model_validator(mode="after")
    def _check(self) -> TaskUpdate:
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        for name in ("title", "status", "priority"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class TaskRead(ORMModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    due_date: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SortKey:
    field: str
    descending: bool


@dataclass(slots=True)
class TaskFilters:
    """Validated filter/sort criteria passed from the API layer to the service layer."""

    status: list[TaskStatus] = field(default_factory=list)
    priority: list[TaskPriority] = field(default_factory=list)
    search: str | None = None
    due_before: datetime | None = None
    due_after: datetime | None = None
    owner_id: uuid.UUID | None = None
    sort: list[SortKey] = field(default_factory=lambda: [SortKey("created_at", descending=True)])


def parse_sort(raw: str | None) -> list[SortKey]:
    """Parse ``"-due_date,priority"`` into sort keys. Raises ``ValueError`` on bad input."""
    if not raw:
        return [SortKey("created_at", descending=True)]
    keys: list[SortKey] = []
    seen: set[str] = set()
    for part in (p.strip() for p in raw.split(",")):
        if not part:
            continue
        descending = part.startswith("-")
        name = part.lstrip("+-")
        if name not in TASK_SORT_FIELDS:
            allowed = ", ".join(sorted(TASK_SORT_FIELDS))
            raise ValueError(f"unsupported sort field '{name}'; allowed: {allowed}")
        if name in seen:
            raise ValueError(f"duplicate sort field '{name}'")
        seen.add(name)
        keys.append(SortKey(name, descending))
    if len(keys) > MAX_SORT_KEYS:
        raise ValueError(f"at most {MAX_SORT_KEYS} sort fields are allowed")
    return keys or [SortKey("created_at", descending=True)]
