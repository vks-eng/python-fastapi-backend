from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import InputModel, SafeStr


class LoginRequest(InputModel):
    email: EmailStr
    password: SafeStr = Field(
        min_length=1, max_length=128, json_schema_extra={"format": "password"}
    )


class RefreshRequest(InputModel):
    refresh_token: SafeStr = Field(min_length=16, max_length=256)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - not a secret
    expires_in: int = Field(description="Access token lifetime in seconds")
    refresh_expires_in: int = Field(description="Refresh token lifetime in seconds")
