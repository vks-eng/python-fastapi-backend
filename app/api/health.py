"""Liveness and readiness probes (unversioned, unauthenticated)."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import SettingsDep, get_database
from app.db.session import Database

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)

READINESS_TIMEOUT_SECONDS = 3.0


@router.get("/health", summary="Liveness probe")
async def health(settings: SettingsDep) -> dict[str, str]:
    return {"status": "ok", "version": settings.app_version}


@router.get(
    "/ready",
    summary="Readiness probe (checks database connectivity)",
    responses={503: {"description": "A required dependency is unavailable"}},
)
async def ready(db: Annotated[Database, Depends(get_database)]) -> JSONResponse:
    checks: dict[str, Any] = {}
    try:
        await asyncio.wait_for(db.ping(), timeout=READINESS_TIMEOUT_SECONDS)
        checks["database"] = "ok"
    except Exception as exc:  # any failure means "not ready"; details stay in the logs
        logger.warning("readiness check failed", extra={"error": type(exc).__name__})
        checks["database"] = "unavailable"
    is_ready = all(value == "ok" for value in checks.values())
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={"status": "ready" if is_ready else "not_ready", "checks": checks},
    )
