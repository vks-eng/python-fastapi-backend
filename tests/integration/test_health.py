"""Health/readiness probes, request IDs, security headers and global error handling."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.api.deps import get_database
from tests.conftest import AppFactory


@pytest.mark.smoke
async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.smoke
async def test_ready_checks_database(client: AsyncClient) -> None:
    response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}


async def test_ready_returns_503_when_database_down(client_factory: AppFactory) -> None:
    client = await client_factory()

    class BrokenDatabase:
        async def ping(self) -> None:
            raise ConnectionError("db down")

    client._transport.app.dependency_overrides[get_database] = BrokenDatabase  # type: ignore[attr-defined]
    response = await client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"] == "unavailable"
    assert "db down" not in response.text


async def test_request_id_generated_and_security_headers(client: AsyncClient) -> None:
    response = await client.get("/health")
    request_id = response.headers.get("x-request-id")
    assert request_id
    assert len(request_id) == 32
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


async def test_request_id_propagated_when_valid(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert response.headers["x-request-id"] == "abc-123"


async def test_request_id_replaced_when_unsafe(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "bad id<script>"})
    assert response.headers["x-request-id"] != "bad id<script>"


async def test_unknown_route_uses_error_schema(client: AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist", headers={"X-Request-ID": "req-1"})
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["request_id"] == "req-1"


async def test_method_not_allowed_uses_error_schema(client: AsyncClient) -> None:
    response = await client.put("/health")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


@pytest.mark.security
async def test_unhandled_exception_does_not_leak_details(client_factory: AppFactory) -> None:
    client = await client_factory(raise_app_exceptions=False)
    app = client._transport.app  # type: ignore[attr-defined]

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    response = await client.get("/boom", headers={"X-Request-ID": "boom-1"})
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["request_id"] == "boom-1"
    assert "secret internal detail" not in response.text
    assert "Traceback" not in response.text
    assert response.headers["x-request-id"] == "boom-1"


async def test_openapi_docs_available(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/tasks/{task_id}" in paths
    assert (await client.get("/docs")).status_code == 200


async def test_docs_can_be_disabled(client_factory: AppFactory) -> None:
    client = await client_factory(docs_enabled=False)
    assert (await client.get("/docs")).status_code == 404
    assert (await client.get("/openapi.json")).status_code == 404


async def test_cors_preflight(client_factory: AppFactory) -> None:
    client = await client_factory(cors_origins="https://app.example.com")
    response = await client.options(
        "/api/v1/tasks",
        headers={
            "Origin": "https://app.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.example.com"

    denied = await client.options(
        "/api/v1/tasks",
        headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in denied.headers


async def test_database_outage_maps_to_503(client_factory: AppFactory) -> None:
    client = await client_factory(raise_app_exceptions=False)
    app = client._transport.app  # type: ignore[attr-defined]

    @app.get("/db-down")
    async def db_down() -> None:
        raise ConnectionRefusedError("connection refused by 10.0.0.5:5432")

    response = await client.get("/db-down")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert response.headers["retry-after"] == "5"
    assert "10.0.0.5" not in response.text
