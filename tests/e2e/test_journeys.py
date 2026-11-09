"""End-to-end user journeys through the full ASGI app (middleware, routing, services, DB).

Each test is one realistic multi-step scenario that only uses the public HTTP API, the
way a client application would.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.models import User

API = "/api/v1"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.smoke
async def test_user_journey(client: AsyncClient) -> None:
    """register -> login -> CRUD -> filter/sort -> rotate -> reuse detected -> logout."""
    # 1. Register and log in.
    creds = {"email": "journey@example.com", "password": "Journey-pass1"}
    registered = await client.post(f"{API}/auth/register", json={**creds, "full_name": "J"})
    assert registered.status_code == 201
    login = await client.post(f"{API}/auth/login", json=creds)
    assert login.status_code == 200
    tokens = login.json()
    me = await client.get(f"{API}/users/me", headers=auth(tokens["access_token"]))
    assert me.json()["email"] == creds["email"]

    # 2. Create a small backlog.
    headers = auth(tokens["access_token"])
    specs = [
        ("Write spec", "high", "2030-01-10T09:00:00Z"),
        ("Fix login bug", "urgent", "2030-01-05T09:00:00Z"),
        ("Update docs", "low", None),
        ("Release notes", "medium", "2030-01-20T09:00:00Z"),
    ]
    ids = {}
    for title, priority, due in specs:
        response = await client.post(
            f"{API}/tasks",
            headers=headers,
            json={"title": title, "priority": priority, "due_date": due},
        )
        assert response.status_code == 201
        ids[title] = response.json()["id"]

    # 3. Work on tasks: start one, finish one, edit one.
    started = await client.patch(
        f"{API}/tasks/{ids['Write spec']}", headers=headers, json={"status": "in_progress"}
    )
    assert started.json()["status"] == "in_progress"
    done = await client.patch(
        f"{API}/tasks/{ids['Fix login bug']}", headers=headers, json={"status": "done"}
    )
    assert done.json()["completed_at"] is not None
    edited = await client.patch(
        f"{API}/tasks/{ids['Update docs']}",
        headers=headers,
        json={"description": "README + API.md", "due_date": "2030-02-01T00:00:00Z"},
    )
    assert edited.json()["description"] == "README + API.md"

    # 4. Filter + sort + paginate: open work, most urgent first.
    open_work = await client.get(
        f"{API}/tasks",
        headers=headers,
        params=[("status", "todo"), ("status", "in_progress"), ("sort", "-priority,due_date")],
    )
    assert [t["title"] for t in open_work.json()["items"]] == [
        "Write spec",
        "Release notes",
        "Update docs",
    ]
    page2 = await client.get(
        f"{API}/tasks", headers=headers, params={"page": 2, "page_size": 3, "sort": "title"}
    )
    assert page2.json()["meta"] == {"page": 2, "page_size": 3, "total": 4, "pages": 2}
    assert [t["title"] for t in page2.json()["items"]] == ["Write spec"]
    found = await client.get(f"{API}/tasks", headers=headers, params={"q": "readme"})
    assert [t["title"] for t in found.json()["items"]] == ["Update docs"]

    # 5. Delete one.
    deleted = await client.delete(f"{API}/tasks/{ids['Release notes']}", headers=headers)
    assert deleted.status_code == 204

    # 6. Refresh rotation: the new pair works.
    rotated = await client.post(
        f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert rotated.status_code == 200
    new_tokens = rotated.json()
    listing = await client.get(f"{API}/tasks", headers=auth(new_tokens["access_token"]))
    assert listing.json()["meta"]["total"] == 3

    # 7. A stolen old refresh token is replayed -> the whole session dies.
    replay = await client.post(
        f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert replay.json()["error"]["code"] == "refresh_token_reused"
    revoked = await client.get(f"{API}/users/me", headers=auth(new_tokens["access_token"]))
    assert revoked.json()["error"]["code"] == "session_revoked"

    # 8. Log in again, log out, and the token is rejected afterwards.
    fresh = (await client.post(f"{API}/auth/login", json=creds)).json()
    logout = await client.post(f"{API}/auth/logout", headers=auth(fresh["access_token"]))
    assert logout.status_code == 204
    after = await client.get(f"{API}/tasks", headers=auth(fresh["access_token"]))
    assert after.status_code == 401
    after_refresh = await client.post(
        f"{API}/auth/refresh", json={"refresh_token": fresh["refresh_token"]}
    )
    assert after_refresh.status_code == 401


async def test_admin_journey(client: AsyncClient, admin: User) -> None:
    """Admin moderates a user: sees their tasks, deactivates, reactivates, promotes."""
    admin_tokens = (
        await client.post(
            f"{API}/auth/login", json={"email": admin.email, "password": "Sup3r-Secret-pw"}
        )
    ).json()
    admin_headers = auth(admin_tokens["access_token"])

    creds = {"email": "member@example.com", "password": "Member-pass1"}
    member = (await client.post(f"{API}/auth/register", json=creds)).json()
    member_tokens = (await client.post(f"{API}/auth/login", json=creds)).json()
    member_headers = auth(member_tokens["access_token"])
    task = (
        await client.post(f"{API}/tasks", headers=member_headers, json={"title": "Member task"})
    ).json()

    # Admin finds the user and sees their tasks.
    search = await client.get(f"{API}/users", headers=admin_headers, params={"q": "member"})
    assert [u["id"] for u in search.json()["items"]] == [member["id"]]
    their_tasks = await client.get(
        f"{API}/tasks", headers=admin_headers, params={"owner_id": member["id"]}
    )
    assert [t["id"] for t in their_tasks.json()["items"]] == [task["id"]]
    reprioritised = await client.patch(
        f"{API}/tasks/{task['id']}", headers=admin_headers, json={"priority": "urgent"}
    )
    assert reprioritised.json()["priority"] == "urgent"

    # Deactivation: existing session dies, login refused.
    deactivated = await client.patch(
        f"{API}/users/{member['id']}", headers=admin_headers, json={"is_active": False}
    )
    assert deactivated.json()["is_active"] is False
    assert (await client.get(f"{API}/users/me", headers=member_headers)).status_code == 401
    assert (await client.post(f"{API}/auth/login", json=creds)).status_code == 403

    # Reactivation and promotion: the member can now use admin endpoints.
    await client.patch(
        f"{API}/users/{member['id']}", headers=admin_headers, json={"is_active": True}
    )
    await client.patch(f"{API}/users/{member['id']}", headers=admin_headers, json={"role": "admin"})
    promoted = (await client.post(f"{API}/auth/login", json=creds)).json()
    users = await client.get(f"{API}/users", headers=auth(promoted["access_token"]))
    assert users.status_code == 200
    assert users.json()["meta"]["total"] == 2

    # The original admin cannot lock themselves out.
    self_demote = await client.patch(
        f"{API}/users/{admin.id}", headers=admin_headers, json={"role": "user"}
    )
    assert self_demote.status_code == 400


async def test_password_change_journey(client: AsyncClient) -> None:
    """Change password on one device; other devices are signed out."""
    creds = {"email": "devices@example.com", "password": "Old-passw0rd"}
    await client.post(f"{API}/auth/register", json=creds)
    laptop = (await client.post(f"{API}/auth/login", json=creds)).json()
    phone = (await client.post(f"{API}/auth/login", json=creds)).json()

    changed = await client.patch(
        f"{API}/users/me",
        headers=auth(laptop["access_token"]),
        json={"current_password": creds["password"], "new_password": "New-passw0rd"},
    )
    assert changed.status_code == 200
    assert (
        await client.get(f"{API}/users/me", headers=auth(laptop["access_token"]))
    ).status_code == 200
    assert (
        await client.get(f"{API}/users/me", headers=auth(phone["access_token"]))
    ).status_code == 401
    assert (await client.post(f"{API}/auth/login", json=creds)).status_code == 401
    relogin = await client.post(
        f"{API}/auth/login", json={"email": creds["email"], "password": "New-passw0rd"}
    )
    assert relogin.status_code == 200
