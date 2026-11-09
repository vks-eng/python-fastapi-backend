"""Task CRUD, validation, pagination, filtering, sorting, search and authorization."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.models import User

TASKS = "/api/v1/tasks"


async def create_task(client: AsyncClient, headers: dict, **fields) -> dict:
    payload = {"title": "Task", **fields}
    response = await client.post(TASKS, headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------- CRUD
@pytest.mark.smoke
async def test_create_task_with_defaults(
    client: AsyncClient, auth_headers: dict, user: User
) -> None:
    task = await create_task(client, auth_headers, title="  Write report  ")
    assert task["title"] == "Write report"
    assert task["status"] == "todo"
    assert task["priority"] == "medium"
    assert task["owner_id"] == str(user.id)
    assert task["description"] is None
    assert task["completed_at"] is None


async def test_create_task_full(client: AsyncClient, auth_headers: dict) -> None:
    due = (datetime.now(UTC) + timedelta(days=3)).replace(microsecond=0)
    task = await create_task(
        client,
        auth_headers,
        title="Ship",
        description="Release v1",
        priority="urgent",
        status="done",
        due_date=due.isoformat(),
    )
    assert task["priority"] == "urgent"
    assert datetime.fromisoformat(task["due_date"]) == due
    assert task["completed_at"] is not None


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"title": ""}, "title"),
        ({"title": "   "}, "title"),
        ({"title": "x" * 201}, "title"),
        ({"title": "ok", "description": "x" * 5001}, "description"),
        ({"title": "ok", "status": "unknown"}, "status"),
        ({"title": "ok", "priority": "critical"}, "priority"),
        ({"title": "ok", "due_date": "2030-01-01T10:00:00"}, "due_date"),  # naive datetime
        ({"title": "ok", "due_date": "tomorrow"}, "due_date"),
        ({"title": "ok", "owner_id": str(uuid.uuid4())}, "owner_id"),  # mass assignment
        ({}, "title"),
    ],
)
async def test_create_task_validation(
    client: AsyncClient, auth_headers: dict, payload: dict, field: str
) -> None:
    response = await client.post(TASKS, headers=auth_headers, json=payload)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert any(d["field"] == field for d in error["details"]), error


async def test_create_task_malformed_json(client: AsyncClient, auth_headers: dict) -> None:
    response = await client.post(
        TASKS,
        headers={**auth_headers, "Content-Type": "application/json"},
        content=b"{not json",
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_get_task(client: AsyncClient, auth_headers: dict) -> None:
    task = await create_task(client, auth_headers)
    response = await client.get(f"{TASKS}/{task['id']}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == task


async def test_get_missing_and_invalid_task(client: AsyncClient, auth_headers: dict) -> None:
    missing = await client.get(f"{TASKS}/{uuid.uuid4()}", headers=auth_headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "task_not_found"
    invalid = await client.get(f"{TASKS}/123", headers=auth_headers)
    assert invalid.status_code == 422


async def test_update_task_partial(client: AsyncClient, auth_headers: dict) -> None:
    task = await create_task(client, auth_headers, description="keep me", priority="low")
    response = await client.patch(
        f"{TASKS}/{task['id']}", headers=auth_headers, json={"title": "Renamed"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Renamed"
    assert body["description"] == "keep me"
    assert body["priority"] == "low"
    assert datetime.fromisoformat(body["updated_at"]) >= datetime.fromisoformat(task["updated_at"])


async def test_update_status_tracks_completion(client: AsyncClient, auth_headers: dict) -> None:
    task = await create_task(client, auth_headers)
    url = f"{TASKS}/{task['id']}"
    done = (await client.patch(url, headers=auth_headers, json={"status": "done"})).json()
    assert done["status"] == "done"
    assert done["completed_at"] is not None
    reopened = (
        await client.patch(url, headers=auth_headers, json={"status": "in_progress"})
    ).json()
    assert reopened["completed_at"] is None


async def test_update_can_clear_nullable_fields(client: AsyncClient, auth_headers: dict) -> None:
    task = await create_task(client, auth_headers, description="d", due_date="2030-01-01T00:00:00Z")
    response = await client.patch(
        f"{TASKS}/{task['id']}", headers=auth_headers, json={"description": None, "due_date": None}
    )
    assert response.status_code == 200
    assert response.json()["description"] is None
    assert response.json()["due_date"] is None


@pytest.mark.parametrize(
    "payload",
    [{}, {"title": None}, {"status": None}, {"priority": "nope"}, {"id": str(uuid.uuid4())}],
)
async def test_update_task_validation(
    client: AsyncClient, auth_headers: dict, payload: dict
) -> None:
    task = await create_task(client, auth_headers)
    response = await client.patch(f"{TASKS}/{task['id']}", headers=auth_headers, json=payload)
    assert response.status_code == 422


async def test_delete_task(client: AsyncClient, auth_headers: dict) -> None:
    task = await create_task(client, auth_headers)
    url = f"{TASKS}/{task['id']}"
    assert (await client.delete(url, headers=auth_headers)).status_code == 204
    assert (await client.get(url, headers=auth_headers)).status_code == 404
    assert (await client.delete(url, headers=auth_headers)).status_code == 404


async def test_tasks_require_authentication(client: AsyncClient) -> None:
    assert (await client.get(TASKS)).status_code == 401
    assert (await client.post(TASKS, json={"title": "x"})).status_code == 401


# --------------------------------------------------------------------------- authorization
@pytest.mark.security
async def test_cross_user_access_is_prevented(
    client: AsyncClient, auth_headers: dict, other_headers: dict
) -> None:
    task = await create_task(client, auth_headers, title="Alice's secret")
    url = f"{TASKS}/{task['id']}"

    # Other users get 404 (not 403) so task ids can't be probed.
    assert (await client.get(url, headers=other_headers)).status_code == 404
    patch = await client.patch(url, headers=other_headers, json={"title": "pwned"})
    assert patch.status_code == 404
    assert (await client.delete(url, headers=other_headers)).status_code == 404

    listing = await client.get(TASKS, headers=other_headers)
    assert listing.json()["meta"]["total"] == 0

    # Task is untouched for its owner.
    owner_view = await client.get(url, headers=auth_headers)
    assert owner_view.json()["title"] == "Alice's secret"


@pytest.mark.security
async def test_non_admin_cannot_filter_by_other_owner(
    client: AsyncClient, auth_headers: dict, other_user: User, user: User
) -> None:
    response = await client.get(
        TASKS, headers=auth_headers, params={"owner_id": str(other_user.id)}
    )
    assert response.status_code == 403
    own = await client.get(TASKS, headers=auth_headers, params={"owner_id": str(user.id)})
    assert own.status_code == 200


async def test_admin_can_access_all_tasks(
    client: AsyncClient,
    auth_headers: dict,
    other_headers: dict,
    admin_headers: dict,
    other_user: User,
) -> None:
    alice_task = await create_task(client, auth_headers, title="A")
    await create_task(client, other_headers, title="B")

    all_tasks = await client.get(TASKS, headers=admin_headers)
    assert all_tasks.json()["meta"]["total"] == 2

    bobs = await client.get(TASKS, headers=admin_headers, params={"owner_id": str(other_user.id)})
    assert [t["title"] for t in bobs.json()["items"]] == ["B"]

    url = f"{TASKS}/{alice_task['id']}"
    assert (await client.get(url, headers=admin_headers)).status_code == 200
    updated = await client.patch(url, headers=admin_headers, json={"priority": "high"})
    assert updated.json()["priority"] == "high"
    assert (await client.delete(url, headers=admin_headers)).status_code == 204


# --------------------------------------------------------------------------- list features
async def test_pagination(client: AsyncClient, auth_headers: dict) -> None:
    for i in range(7):
        await create_task(client, auth_headers, title=f"Task {i}")

    page1 = (await client.get(TASKS, headers=auth_headers, params={"page_size": 3})).json()
    assert page1["meta"] == {"page": 1, "page_size": 3, "total": 7, "pages": 3}
    assert len(page1["items"]) == 3

    page3 = (
        await client.get(TASKS, headers=auth_headers, params={"page_size": 3, "page": 3})
    ).json()
    assert len(page3["items"]) == 1

    beyond = (
        await client.get(TASKS, headers=auth_headers, params={"page_size": 3, "page": 9})
    ).json()
    assert beyond["items"] == []
    assert beyond["meta"]["total"] == 7

    ids = set()
    for page in (1, 2, 3):
        data = (
            await client.get(TASKS, headers=auth_headers, params={"page_size": 3, "page": page})
        ).json()
        ids.update(t["id"] for t in data["items"])
    assert len(ids) == 7  # stable ordering: no duplicates/missing rows across pages


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"page_size": 0},
        {"page_size": 101},
        {"status": "nope"},
        {"priority": "nope"},
        {"due_before": "not-a-date"},
        {"q": ""},
        {"owner_id": "abc"},
    ],
)
async def test_list_query_validation(client: AsyncClient, auth_headers: dict, params: dict) -> None:
    response = await client.get(TASKS, headers=auth_headers, params=params)
    assert response.status_code == 422


async def test_filter_by_status_and_priority(client: AsyncClient, auth_headers: dict) -> None:
    await create_task(client, auth_headers, title="a", status="todo", priority="low")
    await create_task(client, auth_headers, title="b", status="in_progress", priority="high")
    await create_task(client, auth_headers, title="c", status="done", priority="high")

    in_progress = (
        await client.get(TASKS, headers=auth_headers, params={"status": "in_progress"})
    ).json()
    assert [t["title"] for t in in_progress["items"]] == ["b"]

    multi = (
        await client.get(
            TASKS,
            headers=auth_headers,
            params=[("status", "todo"), ("status", "done"), ("sort", "title")],
        )
    ).json()
    assert [t["title"] for t in multi["items"]] == ["a", "c"]

    combined = (
        await client.get(TASKS, headers=auth_headers, params={"priority": "high", "status": "done"})
    ).json()
    assert [t["title"] for t in combined["items"]] == ["c"]


async def test_filter_by_due_date_range(client: AsyncClient, auth_headers: dict) -> None:
    await create_task(client, auth_headers, title="jan", due_date="2030-01-15T00:00:00Z")
    await create_task(client, auth_headers, title="feb", due_date="2030-02-15T00:00:00Z")
    await create_task(client, auth_headers, title="none")

    response = await client.get(
        TASKS,
        headers=auth_headers,
        params={"due_after": "2030-02-01T00:00:00Z", "due_before": "2030-03-01T00:00:00+00:00"},
    )
    assert [t["title"] for t in response.json()["items"]] == ["feb"]

    bad_range = await client.get(
        TASKS,
        headers=auth_headers,
        params={"due_after": "2030-03-01T00:00:00Z", "due_before": "2030-01-01T00:00:00Z"},
    )
    assert bad_range.status_code == 400
    assert bad_range.json()["error"]["code"] == "validation_error"


@pytest.mark.security
async def test_search(client: AsyncClient, auth_headers: dict) -> None:
    await create_task(client, auth_headers, title="Buy milk")
    await create_task(client, auth_headers, title="Write code", description="MILKshake API")
    await create_task(client, auth_headers, title="100% done_ish")
    await create_task(client, auth_headers, title="Other")

    milk = (await client.get(TASKS, headers=auth_headers, params={"q": "milk"})).json()
    assert {t["title"] for t in milk["items"]} == {"Buy milk", "Write code"}

    # LIKE wildcards in user input are matched literally.
    percent = (await client.get(TASKS, headers=auth_headers, params={"q": "%"})).json()
    assert [t["title"] for t in percent["items"]] == ["100% done_ish"]
    underscore = (await client.get(TASKS, headers=auth_headers, params={"q": "_"})).json()
    assert [t["title"] for t in underscore["items"]] == ["100% done_ish"]


async def test_sorting(client: AsyncClient, auth_headers: dict) -> None:
    await create_task(
        client, auth_headers, title="b", priority="low", due_date="2030-01-02T00:00:00Z"
    )
    await create_task(client, auth_headers, title="a", priority="urgent")
    await create_task(
        client, auth_headers, title="c", priority="high", due_date="2030-01-01T00:00:00Z"
    )

    async def titles(sort: str) -> list[str]:
        response = await client.get(TASKS, headers=auth_headers, params={"sort": sort})
        assert response.status_code == 200, response.text
        return [t["title"] for t in response.json()["items"]]

    assert await titles("title") == ["a", "b", "c"]
    assert await titles("-title") == ["c", "b", "a"]
    # Priority sorts by severity (enum order), not alphabetically.
    assert await titles("-priority") == ["a", "c", "b"]
    assert await titles("priority") == ["b", "c", "a"]
    # NULL due dates always last.
    assert await titles("due_date") == ["c", "b", "a"]
    assert await titles("-due_date") == ["b", "c", "a"]
    assert await titles("created_at") == ["b", "a", "c"]
    assert await titles("-created_at,title") == ["c", "a", "b"]


@pytest.mark.parametrize("sort", ["password", "title,title", "a,b,c,d", "owner_id"])
async def test_invalid_sort(client: AsyncClient, auth_headers: dict, sort: str) -> None:
    response = await client.get(TASKS, headers=auth_headers, params={"sort": sort})
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["field"] == "sort"
