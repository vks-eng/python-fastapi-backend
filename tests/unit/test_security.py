"""Unit tests: password hashing and JWT creation/validation (no database)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import Settings
from app.core.exceptions import AuthenticationError
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    password_needs_rehash,
    verify_password,
)

SECRET = "unit-test-secret-key-that-is-long-enough-123"


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, jwt_secret_key=SECRET)  # type: ignore[call-arg]


def _token(settings: Settings, **kwargs) -> str:
    token, _ = create_access_token(
        settings, user_id=uuid.uuid4(), session_id=uuid.uuid4(), role="user", **kwargs
    )
    return token


def test_password_hashing_roundtrip() -> None:
    hashed = hash_password("Correct-h0rse")
    assert hashed.startswith("$argon2id$")
    assert hashed != hash_password("Correct-h0rse")  # salted
    assert verify_password("Correct-h0rse", hashed)
    assert not password_needs_rehash(hashed)


@pytest.mark.parametrize(
    ("password", "stored"),
    [("wrong", "VALID"), ("Correct-h0rse", None), ("Correct-h0rse", "not-a-hash"), ("", "VALID")],
)
def test_verify_password_rejects(password: str, stored: str | None) -> None:
    valid = hash_password("Correct-h0rse")
    assert not verify_password(password, valid if stored == "VALID" else stored)


def test_refresh_tokens_are_random_and_hashed() -> None:
    a, b = generate_refresh_token(), generate_refresh_token()
    assert a != b
    assert len(a) >= 64
    assert hash_refresh_token(a) == hash_refresh_token(a)
    assert len(hash_refresh_token(a)) == 64
    assert hash_refresh_token(a) != a


def test_access_token_roundtrip(settings: Settings) -> None:
    user_id, session_id = uuid.uuid4(), uuid.uuid4()
    token, expires_in = create_access_token(
        settings, user_id=user_id, session_id=session_id, role="admin"
    )
    claims = decode_access_token(settings, token)
    assert claims.subject == user_id
    assert claims.session_id == session_id
    assert claims.role == "admin"
    assert expires_in == settings.access_token_expire_minutes * 60
    assert claims.expires_at - claims.issued_at == timedelta(seconds=expires_in)


def test_expired_token(settings: Settings) -> None:
    token = _token(settings, now=datetime.now(UTC) - timedelta(hours=2))
    with pytest.raises(AuthenticationError) as exc:
        decode_access_token(settings, token)
    assert exc.value.code == "token_expired"


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda c: {**c, "iss": "evil"}, id="wrong-issuer"),
        pytest.param(lambda c: {**c, "aud": "evil"}, id="wrong-audience"),
        pytest.param(lambda c: {**c, "type": "refresh"}, id="wrong-type"),
        pytest.param(lambda c: {k: v for k, v in c.items() if k != "sid"}, id="missing-sid"),
        pytest.param(lambda c: {k: v for k, v in c.items() if k != "exp"}, id="missing-exp"),
        pytest.param(lambda c: {**c, "sub": "not-a-uuid"}, id="malformed-sub"),
        pytest.param(lambda c: {**c, "nbf": c["nbf"] + 3600}, id="not-yet-valid"),
    ],
)
def test_tampered_claims_rejected(settings: Settings, mutate) -> None:
    claims = jwt.decode(_token(settings), options={"verify_signature": False})
    forged = jwt.encode(mutate(claims), SECRET, algorithm="HS256")
    with pytest.raises(AuthenticationError) as exc:
        decode_access_token(settings, forged)
    assert exc.value.code == "invalid_token"


@pytest.mark.filterwarnings("ignore:The HMAC key")
@pytest.mark.parametrize(
    ("key", "algorithm"),
    [("another-secret-key-of-sufficient-length-xx", "HS256"), (SECRET, "HS512"), (None, "none")],
    ids=["bad-signature", "other-algorithm", "alg-none"],
)
def test_signature_and_algorithm_pinned(settings: Settings, key, algorithm: str) -> None:
    claims = jwt.decode(_token(settings), options={"verify_signature": False})
    forged = jwt.encode(claims, key, algorithm=algorithm)
    with pytest.raises(AuthenticationError):
        decode_access_token(settings, forged)


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "Bearer x"])
def test_garbage_tokens_rejected(settings: Settings, garbage: str) -> None:
    with pytest.raises(AuthenticationError):
        decode_access_token(settings, garbage)
