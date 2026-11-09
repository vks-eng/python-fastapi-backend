"""Application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.router import api_v1_router
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.rate_limit import build_rate_limiter
from app.db.session import Database
from app.middleware.body_limit import MaxBodySizeMiddleware
from app.middleware.request_context import RequestContextMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    logger.info(
        "application startup",
        extra={"environment": settings.environment.value, "version": settings.app_version},
    )
    try:
        yield
    finally:
        await app.state.rate_limiter.close()
        await app.state.db.dispose()
        logger.info("application shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    docs = settings.docs_enabled
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        summary="Production-Ready FastAPI Task Management Backend",
        description="TaskForge API is a task management REST API with JWT authentication, "
        "refresh-token rotation with reuse detection, role-based access control, and task "
        "CRUD with filtering, sorting, search and pagination.",
        license_info={"name": "MIT", "identifier": "MIT"},
        contact={"name": "vks-eng", "url": "https://github.com/vks-eng"},
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    # Created eagerly (engines connect lazily) so the app is usable without lifespan events.
    app.state.settings = settings
    app.state.db = Database(settings)
    app.state.rate_limiter = build_rate_limiter(settings.redis_url)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=settings.cors_allow_credentials,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID", "Retry-After"],
            max_age=600,
        )
    app.add_middleware(MaxBodySizeMiddleware, max_bytes=settings.max_request_body_bytes)
    # Added last => outermost: every response (incl. CORS preflight) gets a request id.
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(api_v1_router, prefix=settings.api_v1_prefix)
    return app


def __getattr__(name: str) -> FastAPI:
    # Lazily build the ASGI app for `uvicorn app.main:app` so importing this module
    # (e.g. in tests) does not require a fully configured environment.
    if name == "app":
        application = create_app()
        globals()["app"] = application
        return application
    raise AttributeError(name)
