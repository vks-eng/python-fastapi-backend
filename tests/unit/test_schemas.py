"""Unit tests: request schemas, sort parsing and LIKE escaping.

Uses boundary-value analysis (min-1 / min / max / max+1) and equivalence partitioning
(one representative per valid/invalid class) directly on the Pydantic models.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.repositories.utils import escape_like
from app.schemas.auth import LoginRequest, RefreshRequest
from app.schemas.common import PageMeta, ensure_storable_text
from app.schemas.task import SortKey, TaskCreate, TaskUpdate, parse_sort
from app.schemas.user import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    AdminUserUpdate,
    UserCreate,
    UserUpdate,
)


def _pw(length: int) -> str:
    """A password of exactly `length` chars satisfying the letter+digit rule."""
    return ("a1" * length)[:length]


# --------------------------------------------------------------------------- boundary values
@pytest.mark.parametrize(
    ("length", "valid"),
    [
        (PASSWORD_MIN_LENGTH - 1, False),
        (PASSWORD_MIN_LENGTH, True),
        (PASSWORD_MAX_LENGTH, True),
        (PASSWORD_MAX_LENGTH + 1, False),
    ],
)
def test_password_length_boundaries(length: int, valid: bool) -> None:
    payload = {"email": "a@example.com", "password": _pw(length)}
    if valid:
        assert UserCreate(**payload).password == _pw(length)
    else:
        with pytest.raises(ValidationError):
            UserCreate(**payload)


@pytest.mark.parametrize(("length", "valid"), [(0, False), (1, True), (200, True), (201, False)])
def test_title_length_boundaries(length: int, valid: bool) -> None:
    if valid:
        assert len(TaskCreate(title="t" * length).title) == length
    else:
        with pytest.raises(ValidationError):
            TaskCreate(title="t" * length)


@pytest.mark.parametrize(("length", "valid"), [(5000, True), (5001, False)])
def test_description_length_boundaries(length: int, valid: bool) -> None:
    if valid:
        TaskCreate(title="t", description="d" * length)
    else:
        with pytest.raises(ValidationError):
            TaskCreate(title="t", description="d" * length)


@pytest.mark.parametrize(("length", "valid"), [(15, False), (16, True), (256, True), (257, False)])
def test_refresh_token_length_boundaries(length: int, valid: bool) -> None:
    if valid:
        RefreshRequest(refresh_token="r" * length)
    else:
        with pytest.raises(ValidationError):
            RefreshRequest(refresh_token="r" * length)


# --------------------------------------------------------------------------- equivalence classes
@pytest.mark.parametrize(
    ("password", "valid"),
    [
        ("Letters-and-1", True),  # letters + digit
        ("onlyletters", False),  # no digit
        ("1234567890", False),  # no letter
        (" Padded-pass1", True),  # whitespace is kept as typed (NIST SP 800-63B)
        ("Padded-pass1 ", True),  # whitespace is kept as typed (NIST SP 800-63B)
        ("Nul\x00byte-pass1", False),  # NUL byte
    ],
)
def test_password_classes(password: str, valid: bool) -> None:
    if valid:
        UserCreate(email="a@example.com", password=password)
    else:
        with pytest.raises(ValidationError):
            UserCreate(email="a@example.com", password=password)


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("user@example.com", "user@example.com"),
        ("Mixed.Case@Example.COM", "mixed.case@example.com"),
        ("first.last+tag@sub.example.org", "first.last+tag@sub.example.org"),
        ("no-at-sign.example.com", None),
        ("two@@example.com", None),
        ("missing-domain@", None),
        ("@missing-local.com", None),
        ("spaces in@example.com", None),
        ("", None),
    ],
)
def test_email_classes(email: str, expected: str | None) -> None:
    if expected:
        assert UserCreate(email=email, password="Valid-pass1").email == expected
    else:
        with pytest.raises(ValidationError):
            UserCreate(email=email, password="Valid-pass1")


@pytest.mark.parametrize(
    ("status", "valid"),
    [("todo", True), ("in_progress", True), ("done", True), ("cancelled", True),
     ("TODO", False), ("finished", False), ("", False), (1, False)],
)  # fmt: skip
def test_status_classes(status: object, valid: bool) -> None:
    if valid:
        TaskCreate(title="t", status=status)
    else:
        with pytest.raises(ValidationError):
            TaskCreate(title="t", status=status)


@pytest.mark.parametrize(
    ("priority", "valid"),
    [("low", True), ("medium", True), ("high", True), ("urgent", True),
     ("critical", False), ("High", False), (None, False)],
)  # fmt: skip
def test_priority_classes(priority: object, valid: bool) -> None:
    if valid:
        TaskCreate(title="t", priority=priority)
    else:
        with pytest.raises(ValidationError):
            TaskCreate(title="t", priority=priority)


@pytest.mark.parametrize(
    ("due_date", "valid"),
    [
        ("2030-01-01T00:00:00Z", True),
        ("2030-01-01T00:00:00+05:30", True),
        ("2030-01-01T00:00:00", False),  # naive
        ("2030-13-01T00:00:00Z", False),  # impossible month
        ("next week", False),
    ],
)
def test_due_date_classes(due_date: str, valid: bool) -> None:
    if valid:
        assert TaskCreate(title="t", due_date=due_date).due_date is not None
    else:
        with pytest.raises(ValidationError):
            TaskCreate(title="t", due_date=due_date)


# --------------------------------------------------------------------------- partial updates
def test_task_update_rules() -> None:
    assert TaskUpdate(description=None).model_fields_set == {"description"}
    for bad in ({}, {"title": None}, {"status": None}, {"priority": None}, {"owner_id": "x"}):
        with pytest.raises(ValidationError):
            TaskUpdate(**bad)


def test_user_update_rules() -> None:
    UserUpdate(full_name="  Jane  ")
    assert UserUpdate(full_name="  Jane  ").full_name == "Jane"
    for bad in (
        {},
        {"email": None},
        {"new_password": "N3w-password"},
        {"role": "admin"},
        {"is_active": True},
    ):
        with pytest.raises(ValidationError):
            UserUpdate(**bad)


def test_admin_update_rules() -> None:
    AdminUserUpdate(is_active=False)
    for bad in ({}, {"is_active": None}, {"role": None}, {"role": "root"}):
        with pytest.raises(ValidationError):
            AdminUserUpdate(**bad)


def test_login_request_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        LoginRequest(email="a@example.com", password="x", remember_me=True)


# --------------------------------------------------------------------------- helpers
def test_parse_sort() -> None:
    assert parse_sort(None) == [SortKey("created_at", descending=True)]
    assert parse_sort("-priority, due_date") == [
        SortKey("priority", descending=True),
        SortKey("due_date", descending=False),
    ]
    assert parse_sort("+title") == [SortKey("title", descending=False)]
    assert parse_sort(" , ") == [SortKey("created_at", descending=True)]


@pytest.mark.parametrize(
    "raw",
    [
        "nope",
        "password_hash",
        "title,-title",
        "title,status,priority,due_date",
        "title; DROP TABLE tasks",
        "created_at desc",
    ],
)
def test_parse_sort_rejects(raw: str) -> None:
    with pytest.raises(ValueError, match=r"sort|allowed"):
        parse_sort(raw)


def test_escape_like() -> None:
    assert escape_like(r"50%_off\now") == r"50\%\_off\\now"
    assert escape_like("plain") == "plain"


@pytest.mark.parametrize("bad", ["a\x00b", "\ud800"])
def test_ensure_storable_text_rejects(bad: str) -> None:
    with pytest.raises(ValueError, match=r"NUL|UTF-8"):
        ensure_storable_text(bad)


@pytest.mark.parametrize(
    ("total", "page_size", "pages"), [(0, 20, 0), (1, 20, 1), (20, 20, 1), (21, 20, 2)]
)
def test_page_meta(total: int, page_size: int, pages: int) -> None:
    assert PageMeta.build(page=1, page_size=page_size, total=total).pages == pages
