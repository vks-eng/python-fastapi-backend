"""Domain exceptions and the global handlers that map them to a consistent error schema.

Every error response has the shape::

    {"error": {"code": "...", "message": "...", "details": [...] | null, "request_id": "..."}}

Unexpected exceptions are logged with a traceback server-side and returned as a generic
500 without leaking internals.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import exc as sa_exc
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "bad_request"
    message: str = "Bad request"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details
        self.headers = headers
        super().__init__(self.message)


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "not_authenticated"
    message = "Could not validate credentials"

    def __init__(self, message: str | None = None, *, code: str | None = None) -> None:
        super().__init__(message, code=code, headers={"WWW-Authenticate": "Bearer"})


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "permission_denied"
    message = "You do not have permission to perform this action"


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "Resource not found"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    message = "Resource conflict"


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"
    message = "Request body is too large"


class RateLimitExceededError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"
    message = "Too many requests, please try again later"

    def __init__(self, retry_after: int) -> None:
        super().__init__(headers={"Retry-After": str(max(retry_after, 1))})


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = _request_id(request)
    response_headers = dict(headers or {})
    if request_id:
        response_headers["X-Request-ID"] = request_id
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "request_id": request_id,
            }
        },
        headers=response_headers,
    )


_HTTP_CODES: dict[int, str] = {
    400: "bad_request",
    401: "not_authenticated",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    429: "rate_limited",
}


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)  # noqa: S101 - narrowed for the type checker
    if exc.status_code >= 500:
        logger.error("application error", extra={"code": exc.code})
    return error_response(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
        headers=exc.headers,
    )


_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})


def _allowed_methods(request: Request) -> str | None:
    """Every method served at this path, across all routes.

    Starlette builds ``Allow`` from the first route whose path matched, so a path served by
    separate GET and PATCH routes would advertise only ``GET``. RFC 9110 requires the full set.
    """
    # Derived from the OpenAPI document: it is the public contract and is independent of
    # FastAPI's internal router structure.
    path = request.url.path
    methods: set[str] = set()
    for template, operations in request.app.openapi().get("paths", {}).items():
        pattern = "^" + re.sub(r"\\\{[^/]+?\\\}", "[^/]+", re.escape(template)) + "$"
        if re.match(pattern, path):
            methods.update(m.upper() for m in operations if m.upper() in _HTTP_METHODS)
    return ", ".join(sorted(methods)) if methods else None


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    message = exc.detail if isinstance(exc.detail, str) else "HTTP error"
    headers = dict(getattr(exc, "headers", None) or {})
    if exc.status_code == status.HTTP_405_METHOD_NOT_ALLOWED:
        allow = _allowed_methods(request)
        if allow:
            headers["Allow"] = allow
    return error_response(
        request,
        status_code=exc.status_code,
        code=_HTTP_CODES.get(exc.status_code, "http_error"),
        message=message,
        headers=headers or None,
    )


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    details = []
    for err in exc.errors():
        loc = [str(part) for part in err.get("loc", ())]
        details.append(
            {
                "field": ".".join(loc[1:]) if len(loc) > 1 else ".".join(loc),
                "location": loc[0] if loc else None,
                "message": err.get("msg", "Invalid value"),
                "type": err.get("type", "value_error"),
            }
        )
    return error_response(
        request,
        status_code=422,
        code="validation_error",
        message="Request validation failed",
        details=details,
    )


# Infrastructure failures (DB down, pool exhausted) are reported as 503 so that clients and
# load balancers can retry, instead of a generic 500.
DATABASE_UNAVAILABLE_ERRORS: tuple[type[Exception], ...] = (
    sa_exc.OperationalError,
    sa_exc.InterfaceError,
    sa_exc.TimeoutError,
    ConnectionError,
)


async def database_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "database unavailable",
        extra={"error": type(exc).__name__, "request_id": _request_id(request)},
    )
    return error_response(
        request,
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        code="service_unavailable",
        message="Service temporarily unavailable, please retry later",
        headers={"Retry-After": "5"},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "unhandled exception",
        extra={
            "path": request.url.path,
            "method": request.method,
            "request_id": _request_id(request),
        },
        exc_info=exc,
    )
    return error_response(
        request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="internal_error",
        message="An unexpected error occurred",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    for exc_type in DATABASE_UNAVAILABLE_ERRORS:
        app.add_exception_handler(exc_type, database_unavailable_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
