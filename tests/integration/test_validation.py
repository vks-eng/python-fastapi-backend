"""Functional test techniques through the HTTP API.

* Boundary-value analysis: values at min-1 / min / max / max+1.
* Equivalence partitioning: one representative per valid / invalid class.
* Negative testing: malformed JSON, wrong types, unknown fields, invalid UUIDs, oversized
  payloads, wrong content type; each asserts the error envelope and its machine code.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import AppFactory

TASKS = "/api/v1/tasks"
REGISTER = "/api/v1/auth/register"


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert set(error) == {"code", "message", "details", "request_id"}
    assert error["code"] == code
    assert error["request_id"] == response.headers["x-request-id"]
    return error


# --------------------------------------------------------------------------- boundary values
@pytest.mark.parametrize(("length", "expected"), [(0, 422), (1, 201), (200, 201), (201, 422)])
async def test_title_length_boundaries(
    client: AsyncClient, auth_headers: dict, length: int, expected: int
) -> None:
    response = await client.post(TASKS, headers=auth_headers, json={"title": "t" * length})
    assert response.status_code == expected
    if expected == 201:
        assert len(response.json()["title"]) == length


@pytest.mark.parametrize(("length", "expected"), [(5000, 201), (5001, 422)])
async def test_description_length_boundaries(
    client: AsyncClient, auth_headers: dict, length: int, expected: int
) -> None:
    response = await client.post(
        TASKS, headers=auth_headers, json={"title": "t", "description": "d" * length}
    )
    assert response.status_code == expected


@pytest.mark.parametrize(("page_size", "expected"), [(0, 422), (1, 200), (100, 200), (101, 422)])
async def test_page_size_boundaries(
    client: AsyncClient, auth_headers: dict, page_size: int, expected: int
) -> None:
    response = await client.get(TASKS, headers=auth_headers, params={"page_size": page_size})
    assert response.status_code == expected


@pytest.mark.parametrize(
    ("page", "expected"), [(-1, 422), (0, 422), (1, 200), (10_000, 200), (10_001, 422)]
)
async def test_page_boundaries(
    client: AsyncClient, auth_headers: dict, page: int, expected: int
) -> None:
    response = await client.get(TASKS, headers=auth_headers, params={"page": page})
    assert response.status_code == expected


@pytest.mark.parametrize(("length", "expected"), [(7, 422), (8, 201), (128, 201), (129, 422)])
async def test_password_length_boundaries(client: AsyncClient, length: int, expected: int) -> None:
    password = ("a1" * 100)[:length]
    response = await client.post(
        REGISTER, json={"email": f"pw{length}@example.com", "password": password}
    )
    assert response.status_code == expected


@pytest.mark.parametrize(("q_length", "expected"), [(0, 422), (1, 200), (100, 200), (101, 422)])
async def test_search_length_boundaries(
    client: AsyncClient, auth_headers: dict, q_length: int, expected: int
) -> None:
    response = await client.get(TASKS, headers=auth_headers, params={"q": "q" * q_length})
    assert response.status_code == expected


async def test_due_date_range_boundaries(client: AsyncClient, auth_headers: dict) -> None:
    """due_after is inclusive, due_before is exclusive."""
    edge = "2030-06-01T00:00:00Z"
    await client.post(TASKS, headers=auth_headers, json={"title": "edge", "due_date": edge})

    async def count(**params: str) -> int:
        response = await client.get(TASKS, headers=auth_headers, params=params)
        assert response.status_code == 200
        return response.json()["meta"]["total"]

    assert await count(due_after=edge) == 1
    assert await count(due_before=edge) == 0
    assert await count(due_after="2030-06-01T00:00:01Z") == 0
    assert await count(due_before="2030-06-01T00:00:01Z") == 1
    assert await count(due_after=edge, due_before="2030-06-01T00:00:01Z") == 1
    # Equal bounds is a valid (empty) range; inverted bounds are rejected.
    assert await count(due_after=edge, due_before=edge) == 0
    inverted = await client.get(
        TASKS,
        headers=auth_headers,
        params={"due_after": "2030-06-02T00:00:00Z", "due_before": edge},
    )
    assert_error(inverted, 400, "validation_error")


# --------------------------------------------------------------------------- equivalence classes
@pytest.mark.parametrize(
    ("value", "expected"),
    [("todo", 200), ("in_progress", 200), ("done", 200), ("cancelled", 200),
     ("TODO", 422), ("archived", 422), ("", 422)],
)  # fmt: skip
async def test_status_filter_classes(
    client: AsyncClient, auth_headers: dict, value: str, expected: int
) -> None:
    response = await client.get(TASKS, headers=auth_headers, params={"status": value})
    assert response.status_code == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("low", 201), ("medium", 201), ("high", 201), ("urgent", 201),
     ("critical", 422), ("HIGH", 422), (3, 422)],
)  # fmt: skip
async def test_priority_classes(
    client: AsyncClient, auth_headers: dict, value: object, expected: int
) -> None:
    response = await client.post(
        TASKS, headers=auth_headers, json={"title": "t", "priority": value}
    )
    assert response.status_code == expected


@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        ("created_at", 200),
        ("-updated_at", 200),
        ("due_date,-priority", 200),
        ("status,title,-created_at", 200),
        ("id", 400),  # not whitelisted
        ("owner_id", 400),
        ("description", 400),
        ("title,title", 400),  # duplicate
        ("a,b,c,d", 400),  # too many
    ],
)
async def test_sort_field_classes(
    client: AsyncClient, auth_headers: dict, sort: str, expected: int
) -> None:
    response = await client.get(TASKS, headers=auth_headers, params={"sort": sort})
    assert response.status_code == expected
    if expected == 400:
        assert_error(response, 400, "validation_error")


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("valid.user@example.com", 201),
        ("UPPER@EXAMPLE.COM", 201),
        ("plus+tag@example.org", 201),
        ("no-at.example.com", 422),
        ("trailing-dot@example.com.", 422),
        ("a@b", 422),
        (12345, 422),
    ],
)
async def test_email_classes(client: AsyncClient, email: object, expected: int) -> None:
    response = await client.post(REGISTER, json={"email": email, "password": "Valid-pass1"})
    assert response.status_code == expected


# --------------------------------------------------------------------------- negative testing
async def test_malformed_json(client: AsyncClient, auth_headers: dict) -> None:
    response = await client.post(
        TASKS,
        headers={**auth_headers, "Content-Type": "application/json"},
        content=b'{"title": "unterminated',
    )
    error = assert_error(response, 422, "validation_error")
    assert error["details"][0]["type"] == "json_invalid"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        "just a string",
        {"title": 123},
        {"title": ["a"]},
        {"title": "ok", "description": {"nested": True}},
        {"title": "ok", "due_date": 1700000000.5},
        {"title": None},
    ],
)
async def test_wrong_types(client: AsyncClient, auth_headers: dict, payload: object) -> None:
    response = await client.post(TASKS, headers=auth_headers, json=payload)
    assert_error(response, 422, "validation_error")


@pytest.mark.parametrize(
    ("method", "url", "payload"),
    [
        ("POST", TASKS, {"title": "ok", "owner_id": "00000000-0000-0000-0000-000000000000"}),
        ("POST", TASKS, {"title": "ok", "completed_at": "2030-01-01T00:00:00Z"}),
        ("PATCH", "/api/v1/users/me", {"role": "admin"}),
        ("PATCH", "/api/v1/users/me", {"is_active": True}),
        ("POST", REGISTER, {"email": "x@example.com", "password": "Valid-pass1", "role": "admin"}),
    ],
)
async def test_unknown_fields_rejected(
    client: AsyncClient, auth_headers: dict, method: str, url: str, payload: dict
) -> None:
    response = await client.request(method, url, headers=auth_headers, json=payload)
    error = assert_error(response, 422, "validation_error")
    assert any(d["type"] == "extra_forbidden" for d in error["details"])


@pytest.mark.parametrize(
    "task_id", ["123", "not-a-uuid", "00000000-0000-0000-0000", "%27%20OR%201=1--"]
)
async def test_invalid_uuid_path(client: AsyncClient, auth_headers: dict, task_id: str) -> None:
    for method in ("GET", "PATCH", "DELETE"):
        response = await client.request(
            method, f"{TASKS}/{task_id}", headers=auth_headers, json={"title": "x"}
        )
        assert_error(response, 422, "validation_error")


async def test_oversized_payload_rejected(client_factory: AppFactory, user) -> None:
    client = await client_factory(max_request_body_bytes=2048)
    response = await client.post(
        REGISTER,
        json={"email": "big@example.com", "password": "Valid-pass1", "full_name": "x" * 5000},
    )
    assert_error(response, 413, "payload_too_large")


async def test_oversized_chunked_payload_rejected(client_factory: AppFactory) -> None:
    client = await client_factory(max_request_body_bytes=2048)

    async def chunks():
        for _ in range(10):
            yield b"x" * 1024

    response = await client.post(
        REGISTER, content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert_error(response, 413, "payload_too_large")


async def test_wrong_content_type(client: AsyncClient, auth_headers: dict) -> None:
    response = await client.post(
        TASKS,
        headers={**auth_headers, "Content-Type": "text/plain"},
        content=b'{"title": "x"}',
    )
    assert_error(response, 422, "validation_error")


@pytest.mark.parametrize("bad", ["nul\x00byte", "lone\ud800surrogate"])
async def test_unstorable_text_is_422_not_500(
    client: AsyncClient, auth_headers: dict, bad: str
) -> None:
    import json

    body = json.dumps({"title": bad}).encode()  # escapes keep the JSON itself valid
    response = await client.post(
        TASKS, headers={**auth_headers, "Content-Type": "application/json"}, content=body
    )
    assert_error(response, 422, "validation_error")
    search = await client.get(TASKS, headers=auth_headers, params={"q": "a\x00b"})
    assert_error(search, 422, "validation_error")


async def test_empty_body(client: AsyncClient, auth_headers: dict) -> None:
    response = await client.post(TASKS, headers=auth_headers)
    assert_error(response, 422, "validation_error")
