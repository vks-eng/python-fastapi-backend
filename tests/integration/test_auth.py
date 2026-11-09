"""Registration, login, access-token validation, refresh rotation, logout, rate limiting."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import create_access_token
from app.models import AuthSession, RefreshToken, User
from tests.conftest import DEFAULT_PASSWORD, TEST_JWT_SECRET, AppFactory, bearer, login

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/users/me"


# --------------------------------------------------------------------------- registration
@pytest.mark.smoke
async def test_register_success(client: AsyncClient) -> None:
    response = await client.post(
        REGISTER,
        json={"email": "New.User@Example.com", "password": DEFAULT_PASSWORD, "full_name": "  N  "},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "new.user@example.com"  # normalised
    assert body["full_name"] == "N"
    assert body["role"] == "user"
    assert body["is_active"] is True
    assert "password" not in body
    assert "password_hash" not in body


async def test_register_duplicate_email_is_case_insensitive(
    client: AsyncClient, user: User
) -> None:
    response = await client.post(
        REGISTER, json={"email": "ALICE@example.com", "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"email": "not-an-email", "password": DEFAULT_PASSWORD}, "email"),
        ({"email": "a@example.com", "password": "short1"}, "password"),
        ({"email": "a@example.com", "password": "onlyletters"}, "password"),
        ({"email": "a@example.com", "password": "12345678901"}, "password"),
        ({"email": "a@example.com", "password": "x1" * 65}, "password"),
        ({"email": "a@example.com"}, "password"),
    ],
)
async def test_register_validation(client: AsyncClient, payload: dict, field: str) -> None:
    response = await client.post(REGISTER, json=payload)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert any(d["field"] == field for d in error["details"])


@pytest.mark.security
async def test_register_rejects_mass_assignment_of_role(client: AsyncClient) -> None:
    response = await client.post(
        REGISTER,
        json={"email": "sneaky@example.com", "password": DEFAULT_PASSWORD, "role": "admin"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "role"


async def test_register_requires_activation_when_configured(
    client_factory: AppFactory,
) -> None:
    client = await client_factory(require_account_activation=True)
    response = await client.post(
        REGISTER, json={"email": "pending@example.com", "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 201
    assert response.json()["is_active"] is False

    login_response = await client.post(
        LOGIN, json={"email": "pending@example.com", "password": DEFAULT_PASSWORD}
    )
    assert login_response.status_code == 403
    assert login_response.json()["error"]["code"] == "account_inactive"


# --------------------------------------------------------------------------- login
@pytest.mark.smoke
async def test_login_success(client: AsyncClient, user: User, db_session: AsyncSession) -> None:
    tokens = await login(client, "Alice@Example.com")
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] == 15 * 60
    assert tokens["refresh_expires_in"] == 14 * 24 * 3600
    me = await client.get(ME, headers=bearer(tokens))
    assert me.status_code == 200
    assert me.json()["email"] == user.email

    await db_session.refresh(user)
    assert user.last_login_at is not None
    stored = (await db_session.execute(select(RefreshToken))).scalars().all()
    assert len(stored) == 1
    assert stored[0].token_hash != tokens["refresh_token"]  # only the hash is stored


@pytest.mark.parametrize(
    ("email", "password"),
    [("alice@example.com", "Wrong-passw0rd"), ("nobody@example.com", DEFAULT_PASSWORD)],
)
async def test_login_invalid_credentials(
    client: AsyncClient, user: User, email: str, password: str
) -> None:
    response = await client.post(LOGIN, json={"email": email, "password": password})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"
    assert response.headers["www-authenticate"] == "Bearer"


async def test_login_inactive_user(client: AsyncClient, user_factory) -> None:
    inactive = await user_factory(email="inactive@example.com", is_active=False)
    response = await client.post(
        LOGIN, json={"email": inactive.email, "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "account_inactive"


@pytest.mark.security
async def test_login_rate_limited(client_factory: AppFactory, user: User) -> None:
    client = await client_factory(login_rate_limit=3, login_rate_limit_window_seconds=60)
    payload = {"email": user.email, "password": "Wrong-passw0rd"}
    for _ in range(3):
        assert (await client.post(LOGIN, json=payload)).status_code == 401
    response = await client.post(LOGIN, json=payload)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert int(response.headers["retry-after"]) >= 1


async def test_rate_limit_can_be_disabled(client_factory: AppFactory, user: User) -> None:
    client = await client_factory(login_rate_limit=1, rate_limit_enabled=False)
    payload = {"email": user.email, "password": "Wrong-passw0rd"}
    for _ in range(3):
        assert (await client.post(LOGIN, json=payload)).status_code == 401


# --------------------------------------------------------------------------- access tokens
async def test_protected_route_requires_token(client: AsyncClient) -> None:
    response = await client.get(ME)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("header", ["Bearer not-a-jwt", "Basic dXNlcjpwYXNz", "Bearer "])
@pytest.mark.security
async def test_malformed_tokens_rejected(client: AsyncClient, header: str) -> None:
    response = await client.get(ME, headers={"Authorization": header})
    assert response.status_code == 401


@pytest.mark.security
async def test_expired_access_token_rejected(
    client: AsyncClient, settings: Settings, user_tokens: dict
) -> None:
    claims = jwt.decode(user_tokens["access_token"], options={"verify_signature": False})
    token, _ = create_access_token(
        settings,
        user_id=uuid.UUID(claims["sub"]),
        session_id=uuid.UUID(claims["sid"]),
        role="user",
        now=datetime.now(UTC) - timedelta(hours=1),
        expires_delta=timedelta(minutes=5),
    )
    response = await client.get(ME, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_expired"


def _forge(claims: dict, *, key: str = TEST_JWT_SECRET, algorithm: str = "HS256") -> str:
    return jwt.encode(claims, key, algorithm=algorithm)


@pytest.mark.security
async def test_tampered_tokens_rejected(client: AsyncClient, user_tokens: dict) -> None:
    claims = jwt.decode(user_tokens["access_token"], options={"verify_signature": False})

    wrong_key = _forge(claims, key="another-secret-key-of-sufficient-length-xx")
    wrong_audience = _forge({**claims, "aud": "someone-else"})
    wrong_type = _forge({**claims, "type": "refresh"})
    unknown_session = _forge({**claims, "sid": str(uuid.uuid4())})
    other_subject = _forge({**claims, "sub": str(uuid.uuid4())})
    unsigned = jwt.encode(claims, key=None, algorithm="none")  # type: ignore[arg-type]
    missing_claim = _forge({k: v for k, v in claims.items() if k != "jti"})

    for token in (
        wrong_key,
        wrong_audience,
        wrong_type,
        unknown_session,
        other_subject,
        unsigned,
        missing_claim,
    ):
        response = await client.get(ME, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401, token
        assert response.json()["error"]["code"] == "invalid_token"


# --------------------------------------------------------------------------- refresh rotation
@pytest.mark.smoke
async def test_refresh_rotates_tokens(client: AsyncClient, user_tokens: dict) -> None:
    response = await client.post(REFRESH, json={"refresh_token": user_tokens["refresh_token"]})
    assert response.status_code == 200, response.text
    new_tokens = response.json()
    assert new_tokens["refresh_token"] != user_tokens["refresh_token"]
    assert new_tokens["access_token"] != user_tokens["access_token"]
    assert (await client.get(ME, headers=bearer(new_tokens))).status_code == 200

    # A rotated token can be exchanged again normally.
    again = await client.post(REFRESH, json={"refresh_token": new_tokens["refresh_token"]})
    assert again.status_code == 200


@pytest.mark.security
async def test_refresh_token_reuse_revokes_family(
    client: AsyncClient, user_tokens: dict, db_session: AsyncSession
) -> None:
    first = user_tokens["refresh_token"]
    rotated = (await client.post(REFRESH, json={"refresh_token": first})).json()

    # Replaying the already-rotated token is treated as theft.
    reuse = await client.post(REFRESH, json={"refresh_token": first})
    assert reuse.status_code == 401
    assert reuse.json()["error"]["code"] == "refresh_token_reused"

    # The whole family is revoked: the legitimate newer token and access tokens die too.
    newer = await client.post(REFRESH, json={"refresh_token": rotated["refresh_token"]})
    assert newer.status_code == 401
    assert newer.json()["error"]["code"] == "session_revoked"
    me = await client.get(ME, headers=bearer(rotated))
    assert me.status_code == 401
    assert me.json()["error"]["code"] == "session_revoked"

    sessions = (await db_session.execute(select(AuthSession))).scalars().all()
    assert [s.revoked_reason for s in sessions] == ["refresh_token_reuse"]


async def test_refresh_with_unknown_token(client: AsyncClient) -> None:
    response = await client.post(REFRESH, json={"refresh_token": "x" * 64})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_refresh_token"


async def test_refresh_with_expired_token(
    client: AsyncClient, user_tokens: dict, db_session: AsyncSession
) -> None:
    await db_session.execute(
        update(RefreshToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    response = await client.post(REFRESH, json={"refresh_token": user_tokens["refresh_token"]})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "refresh_token_expired"


async def test_refresh_for_deactivated_user(
    client: AsyncClient, user: User, user_tokens: dict, db_session: AsyncSession
) -> None:
    user.is_active = False
    await db_session.flush()
    response = await client.post(REFRESH, json={"refresh_token": user_tokens["refresh_token"]})
    assert response.status_code == 403


async def test_refresh_validation(client: AsyncClient) -> None:
    response = await client.post(REFRESH, json={"refresh_token": "short"})
    assert response.status_code == 422


# --------------------------------------------------------------------------- logout
@pytest.mark.security
async def test_logout_revokes_access_and_refresh_tokens(
    client: AsyncClient, user_tokens: dict
) -> None:
    headers = bearer(user_tokens)
    assert (await client.post(LOGOUT, headers=headers)).status_code == 204

    me = await client.get(ME, headers=headers)
    assert me.status_code == 401
    assert me.json()["error"]["code"] == "session_revoked"
    refresh = await client.post(REFRESH, json={"refresh_token": user_tokens["refresh_token"]})
    assert refresh.status_code == 401


async def test_logout_only_affects_current_session(client: AsyncClient, user: User) -> None:
    session_a = await login(client, user.email)
    session_b = await login(client, user.email)
    assert (await client.post(LOGOUT, headers=bearer(session_a))).status_code == 204
    assert (await client.get(ME, headers=bearer(session_b))).status_code == 200


async def test_logout_all_sessions(client: AsyncClient, user: User) -> None:
    session_a = await login(client, user.email)
    session_b = await login(client, user.email)
    response = await client.post(f"{LOGOUT}?all_sessions=true", headers=bearer(session_a))
    assert response.status_code == 204
    assert (await client.get(ME, headers=bearer(session_b))).status_code == 401


async def test_logout_requires_authentication(client: AsyncClient) -> None:
    assert (await client.post(LOGOUT)).status_code == 401
