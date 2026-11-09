"""Profile management and admin user management (activation, roles, RBAC)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.models import User
from tests.conftest import DEFAULT_PASSWORD, bearer, login

ME = "/api/v1/users/me"
USERS = "/api/v1/users"


async def test_get_profile(client: AsyncClient, user: User, auth_headers: dict) -> None:
    response = await client.get(ME, headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(user.id)
    assert body["role"] == "user"


async def test_update_profile_name_and_email(client: AsyncClient, auth_headers: dict) -> None:
    response = await client.patch(
        ME, headers=auth_headers, json={"full_name": "Alice Liddell", "email": "ALICE2@example.com"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["full_name"] == "Alice Liddell"
    assert response.json()["email"] == "alice2@example.com"


async def test_update_profile_email_conflict(
    client: AsyncClient, auth_headers: dict, other_user: User
) -> None:
    response = await client.patch(ME, headers=auth_headers, json={"email": other_user.email})
    assert response.status_code == 409


async def test_update_profile_validation(client: AsyncClient, auth_headers: dict) -> None:
    assert (await client.patch(ME, headers=auth_headers, json={})).status_code == 422
    assert (await client.patch(ME, headers=auth_headers, json={"email": None})).status_code == 422
    assert (await client.patch(ME, headers=auth_headers, json={"role": "admin"})).status_code == 422
    assert (
        await client.patch(ME, headers=auth_headers, json={"full_name": "x" * 201})
    ).status_code == 422
    # new_password without current_password
    response = await client.patch(ME, headers=auth_headers, json={"new_password": "N3w-password"})
    assert response.status_code == 422


async def test_change_password(client: AsyncClient, user: User) -> None:
    current = await login(client, user.email)
    other_device = await login(client, user.email)

    wrong = await client.patch(
        ME,
        headers=bearer(current),
        json={"current_password": "Wrong-passw0rd", "new_password": "N3w-password"},
    )
    assert wrong.status_code == 400
    assert wrong.json()["error"]["code"] == "invalid_password"

    ok = await client.patch(
        ME,
        headers=bearer(current),
        json={"current_password": DEFAULT_PASSWORD, "new_password": "N3w-password"},
    )
    assert ok.status_code == 200
    # Current session survives, other sessions are revoked, new password works.
    assert (await client.get(ME, headers=bearer(current))).status_code == 200
    assert (await client.get(ME, headers=bearer(other_device))).status_code == 401
    await login(client, user.email, "N3w-password")
    old = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD}
    )
    assert old.status_code == 401


# --------------------------------------------------------------------------- admin / RBAC
@pytest.mark.security
async def test_non_admin_cannot_use_admin_endpoints(
    client: AsyncClient, auth_headers: dict, other_user: User
) -> None:
    for method, url in (
        ("GET", USERS),
        ("GET", f"{USERS}/{other_user.id}"),
        ("PATCH", f"{USERS}/{other_user.id}"),
    ):
        response = await client.request(
            method, url, headers=auth_headers, json={"is_active": False}
        )
        assert response.status_code == 403, (method, url)
        assert response.json()["error"]["code"] == "permission_denied"


async def test_admin_lists_and_filters_users(
    client: AsyncClient, admin_headers: dict, user: User, other_user: User
) -> None:
    response = await client.get(USERS, headers=admin_headers, params={"page_size": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["meta"] == {"page": 1, "page_size": 2, "total": 3, "pages": 2}

    admins = await client.get(USERS, headers=admin_headers, params={"role": "admin"})
    assert [u["email"] for u in admins.json()["items"]] == ["admin@example.com"]

    search = await client.get(USERS, headers=admin_headers, params={"q": "bob"})
    assert [u["email"] for u in search.json()["items"]] == ["bob@example.com"]


async def test_admin_get_user(client: AsyncClient, admin_headers: dict, user: User) -> None:
    response = await client.get(f"{USERS}/{user.id}", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["email"] == user.email
    missing = await client.get(f"{USERS}/{uuid.uuid4()}", headers=admin_headers)
    assert missing.status_code == 404


async def test_admin_deactivates_and_reactivates_user(
    client: AsyncClient, admin_headers: dict, user: User, user_tokens: dict
) -> None:
    response = await client.patch(
        f"{USERS}/{user.id}", headers=admin_headers, json={"is_active": False}
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    # Existing tokens stop working and login is refused.
    assert (await client.get(ME, headers=bearer(user_tokens))).status_code in (401, 403)
    denied = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD}
    )
    assert denied.status_code == 403

    reactivated = await client.patch(
        f"{USERS}/{user.id}", headers=admin_headers, json={"is_active": True}
    )
    assert reactivated.json()["is_active"] is True
    await login(client, user.email)


async def test_admin_promotes_user(client: AsyncClient, admin_headers: dict, user: User) -> None:
    response = await client.patch(
        f"{USERS}/{user.id}", headers=admin_headers, json={"role": "admin"}
    )
    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    tokens = await login(client, user.email)
    assert (await client.get(USERS, headers=bearer(tokens))).status_code == 200


@pytest.mark.security
async def test_admin_cannot_lock_themselves_out(
    client: AsyncClient, admin_headers: dict, admin: User
) -> None:
    for payload in ({"is_active": False}, {"role": "user"}):
        response = await client.patch(f"{USERS}/{admin.id}", headers=admin_headers, json=payload)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "self_modification"


async def test_admin_update_validation(
    client: AsyncClient, admin_headers: dict, user: User
) -> None:
    url = f"{USERS}/{user.id}"
    assert (await client.patch(url, headers=admin_headers, json={})).status_code == 422
    assert (
        await client.patch(url, headers=admin_headers, json={"is_active": None})
    ).status_code == 422
    assert (
        await client.patch(url, headers=admin_headers, json={"role": "superuser"})
    ).status_code == 422
    assert (
        await client.patch(f"{USERS}/not-a-uuid", headers=admin_headers, json={"role": "user"})
    ).status_code == 422
