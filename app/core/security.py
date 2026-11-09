"""Password hashing (Argon2id), JWT access tokens and opaque refresh tokens."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings
from app.core.exceptions import AuthenticationError

# argon2-cffi defaults follow RFC 9106 "low memory" recommendations (Argon2id).
_password_hasher = PasswordHasher()

# Pre-computed hash used to equalise timing when a login targets an unknown e-mail.
_DUMMY_HASH = _password_hasher.hash(secrets.token_urlsafe(16))

ACCESS_TOKEN_TYPE = "access"  # noqa: S105 - token *type* label, not a secret


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-ish time verification; always performs one Argon2 verification."""
    try:
        return _password_hasher.verify(password_hash or _DUMMY_HASH, password) and bool(
            password_hash
        )
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _password_hasher.check_needs_rehash(password_hash)


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    subject: uuid.UUID
    session_id: uuid.UUID
    role: str
    jti: str
    issued_at: datetime
    expires_at: datetime


def create_access_token(
    settings: Settings,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    role: str,
    now: datetime | None = None,
    expires_delta: timedelta | None = None,
) -> tuple[str, int]:
    """Return ``(token, expires_in_seconds)``."""
    issued_at = now or datetime.now(UTC)
    lifetime = expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "sid": str(session_id),
        "role": role,
        "type": ACCESS_TOKEN_TYPE,
        "jti": uuid.uuid4().hex,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": issued_at,
        "nbf": issued_at,
        "exp": issued_at + lifetime,
    }
    token = jwt.encode(
        payload, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm
    )
    return token, int(lifetime.total_seconds())


def decode_access_token(settings: Settings, token: str) -> AccessTokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],  # pin the algorithm: no "none"/alg confusion
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "nbf", "sub", "jti", "iss", "aud"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Access token has expired", code="token_expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid access token", code="invalid_token") from exc

    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise AuthenticationError("Invalid token type", code="invalid_token")
    try:
        return AccessTokenClaims(
            subject=uuid.UUID(payload["sub"]),
            session_id=uuid.UUID(payload["sid"]),
            role=str(payload.get("role", "")),
            jti=str(payload["jti"]),
            issued_at=datetime.fromtimestamp(payload["iat"], tz=UTC),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise AuthenticationError("Malformed access token", code="invalid_token") from exc


def generate_refresh_token() -> str:
    """Opaque, high-entropy refresh token. Only its SHA-256 digest is persisted."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
