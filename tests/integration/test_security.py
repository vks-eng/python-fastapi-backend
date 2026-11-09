"""Security tests: token tampering, IDOR, privilege escalation, injection, data exposure."""

from __future__ import annotations

import uuid

import jwt
import pytest
from httpx import AsyncClient

from app.models import User
from tests.conftest import DEFAULT_PASSWORD, TEST_JWT_SECRET, AppFactory, bearer, login

pytestmark = pytest.mark.security

ME = "/api/v1/users/me"
TASKS = "/api/v1/tasks"


def _claims(tokens: dict) -> dict:
    return jwt.decode(tokens["access_token"], options={"verify_signature": False})


# --------------------------------------------------------------------------- JWT tampering
@pytest.mark.parametrize(
    ("label", "forge"),
    [
        ("bad-signature", lambda c: jwt.encode(c, "x" * 48, algorithm="HS256")),
        ("alg-none", lambda c: jwt.encode(c, None, algorithm="none")),
        ("wrong-iss", lambda c: jwt.encode({**c, "iss": "evil"}, TEST_JWT_SECRET, "HS256")),
        ("wrong-aud", lambda c: jwt.encode({**c, "aud": "evil"}, TEST_JWT_SECRET, "HS256")),
        ("expired", lambda c: jwt.encode({**c, "exp": c["iat"] - 1}, TEST_JWT_SECRET, "HS256")),
        (
            "missing-sid",
            lambda c: jwt.encode(
                {k: v for k, v in c.items() if k != "sid"}, TEST_JWT_SECRET, "HS256"
            ),
        ),
        (
            "escalated-role-claim",
            # Signed with the real key, but role is ignored: authorization uses the DB role.
            None,
        ),
    ],
)
async def test_jwt_tampering(client: AsyncClient, user_tokens: dict, label: str, forge) -> None:
    claims = _claims(user_tokens)
    if label == "escalated-role-claim":
        token = jwt.encode({**claims, "role": "admin"}, TEST_JWT_SECRET, "HS256")
        response = await client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403
        return
    token = forge(claims)
    response = await client.get(ME, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401, label
    assert response.headers["www-authenticate"] == "Bearer"


async def test_revoked_session_token_rejected(client: AsyncClient, user_tokens: dict) -> None:
    headers = bearer(user_tokens)
    assert (await client.post("/api/v1/auth/logout", headers=headers)).status_code == 204
    response = await client.get(ME, headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_revoked"


async def test_token_from_other_users_session_rejected(
    client: AsyncClient, user_tokens: dict, other_user: User
) -> None:
    claims = _claims(user_tokens)
    forged = jwt.encode({**claims, "sub": str(other_user.id)}, TEST_JWT_SECRET, "HS256")
    response = await client.get(ME, headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


# --------------------------------------------------------------------------- IDOR
@pytest.mark.parametrize(
    ("method", "payload"),
    [("GET", None), ("PATCH", {"title": "pwned"}), ("DELETE", None)],
)
async def test_idor_on_task_endpoints(
    client: AsyncClient,
    auth_headers: dict,
    other_headers: dict,
    method: str,
    payload: dict | None,
) -> None:
    task = (
        await client.post(TASKS, headers=auth_headers, json={"title": "private", "priority": "low"})
    ).json()
    response = await client.request(
        method, f"{TASKS}/{task['id']}", headers=other_headers, json=payload
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "task_not_found"
    # Unchanged and still present for the owner.
    owner_view = await client.get(f"{TASKS}/{task['id']}", headers=auth_headers)
    assert owner_view.status_code == 200
    assert owner_view.json()["title"] == "private"


async def test_idor_on_task_listing(
    client: AsyncClient, auth_headers: dict, other_headers: dict, user: User
) -> None:
    await client.post(TASKS, headers=auth_headers, json={"title": "private"})
    listing = await client.get(TASKS, headers=other_headers)
    assert listing.json()["meta"]["total"] == 0
    probe = await client.get(TASKS, headers=other_headers, params={"owner_id": str(user.id)})
    assert probe.status_code == 403
    search = await client.get(TASKS, headers=other_headers, params={"q": "private"})
    assert search.json()["items"] == []


async def test_idor_cannot_reassign_task_owner(
    client: AsyncClient, auth_headers: dict, other_user: User
) -> None:
    task = (await client.post(TASKS, headers=auth_headers, json={"title": "mine"})).json()
    response = await client.patch(
        f"{TASKS}/{task['id']}", headers=auth_headers, json={"owner_id": str(other_user.id)}
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------- privilege escalation
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/api/v1/users", None),
        ("GET", "/api/v1/users/{other}", None),
        ("PATCH", "/api/v1/users/{other}", {"is_active": False}),
        ("PATCH", "/api/v1/users/{self}", {"role": "admin"}),
    ],
)
async def test_user_cannot_call_admin_endpoints(
    client: AsyncClient,
    user: User,
    other_user: User,
    auth_headers: dict,
    method: str,
    path: str,
    payload: dict | None,
) -> None:
    url = path.format(other=other_user.id, self=user.id)
    response = await client.request(method, url, headers=auth_headers, json=payload)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


async def test_user_cannot_set_own_role_or_activation(
    client: AsyncClient, auth_headers: dict
) -> None:
    for payload in ({"role": "admin"}, {"is_active": True}, {"full_name": "x", "role": "admin"}):
        assert (await client.patch(ME, headers=auth_headers, json=payload)).status_code == 422
    assert (await client.get(ME, headers=auth_headers)).json()["role"] == "user"


async def test_registration_cannot_create_admin(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "x@example.com", "password": DEFAULT_PASSWORD, "role": "admin"},
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------- injection
INJECTION_STRINGS = [
    "' OR '1'='1",
    "'; DROP TABLE tasks; --",
    '" OR ""="',
    "%",
    "_",
    "\\",
    "%%%%",
    "admin'--",
    "1; SELECT pg_sleep(5)",
    "$(whoami)",
    "<script>alert(1)</script>",
]


@pytest.mark.parametrize("payload", INJECTION_STRINGS)
async def test_search_is_injection_safe(
    client: AsyncClient, auth_headers: dict, other_headers: dict, payload: str
) -> None:
    await client.post(TASKS, headers=other_headers, json={"title": "someone else's"})
    await client.post(TASKS, headers=auth_headers, json={"title": "ordinary task"})
    response = await client.get(TASKS, headers=auth_headers, params={"q": payload})
    assert response.status_code == 200
    titles = [t["title"] for t in response.json()["items"]]
    # Wildcards/quotes are literal: nothing matches, and never another user's data.
    assert "someone else's" not in titles
    assert titles == []


async def test_injection_payload_stored_verbatim(client: AsyncClient, auth_headers: dict) -> None:
    payload = "'; DROP TABLE tasks; -- <script>alert(1)</script>"
    created = await client.post(TASKS, headers=auth_headers, json={"title": payload})
    assert created.status_code == 201
    assert created.json()["title"] == payload  # stored as data, returned JSON-encoded
    found = await client.get(TASKS, headers=auth_headers, params={"q": "DROP TABLE"})
    assert [t["title"] for t in found.json()["items"]] == [payload]


@pytest.mark.parametrize(
    "sort",
    ["title; DROP TABLE tasks", "(SELECT 1)", "title desc", "-title,1=1", "pg_sleep(5)"],
)
async def test_sort_is_injection_safe(client: AsyncClient, auth_headers: dict, sort: str) -> None:
    response = await client.get(TASKS, headers=auth_headers, params={"sort": sort})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


async def test_login_injection_strings(client: AsyncClient, user: User) -> None:
    for email in ("' OR 1=1 --@example.com", "alice@example.com' --"):
        response = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "' OR '1'='1"}
        )
        assert response.status_code in (401, 422)


# --------------------------------------------------------------------------- rate limiting
@pytest.mark.parametrize(
    ("endpoint", "setting", "payload"),
    [
        (
            "/api/v1/auth/login",
            "login_rate_limit",
            {"email": "alice@example.com", "password": "Wrong-pass1"},
        ),
        (
            "/api/v1/auth/register",
            "register_rate_limit",
            {"email": "not-an-email", "password": "x"},
        ),
        ("/api/v1/auth/refresh", "refresh_rate_limit", {"refresh_token": "x" * 32}),
    ],
)
async def test_auth_endpoints_rate_limited(
    client_factory: AppFactory, user: User, endpoint: str, setting: str, payload: dict
) -> None:
    client = await client_factory(**{setting: 2})
    for _ in range(2):
        assert (await client.post(endpoint, json=payload)).status_code != 429
    response = await client.post(endpoint, json=payload)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert int(response.headers["retry-after"]) >= 1


# --------------------------------------------------------------------------- data exposure
SENSITIVE = ("password_hash", "$argon2", DEFAULT_PASSWORD, TEST_JWT_SECRET, "token_hash")


async def test_no_secrets_in_any_response(
    client: AsyncClient, user: User, admin_headers: dict
) -> None:
    responses = []
    responses.append(
        await client.post(
            "/api/v1/auth/register",
            json={"email": "new@example.com", "password": DEFAULT_PASSWORD},
        )
    )
    tokens = await login(client, user.email)
    headers = bearer(tokens)
    responses.append(await client.get(ME, headers=headers))
    responses.append(await client.patch(ME, headers=headers, json={"full_name": "A"}))
    task = await client.post(TASKS, headers=headers, json={"title": "t"})
    responses.append(task)
    responses.append(await client.get(TASKS, headers=headers))
    responses.append(await client.get("/api/v1/users", headers=admin_headers))
    responses.append(await client.get(f"/api/v1/users/{user.id}", headers=admin_headers))
    responses.append(
        await client.post("/api/v1/auth/login", json={"email": user.email, "password": "bad1"})
    )
    responses.append(await client.get("/openapi.json"))
    refreshed = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200

    for response in responses:
        for secret in SENSITIVE:
            assert secret not in response.text, (response.request.url, secret)
    # The only place a refresh token appears is the token endpoint body itself.
    assert tokens["refresh_token"] not in "".join(r.text for r in responses)


async def test_error_responses_hide_internals(client: AsyncClient) -> None:
    response = await client.get(f"{TASKS}/{uuid.uuid4()}")  # unauthenticated
    assert response.status_code == 401
    for leak in ("Traceback", "sqlalchemy", "asyncpg", 'File "'):
        assert leak not in response.text
