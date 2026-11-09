"""Property-based API fuzzing with Schemathesis against the live OpenAPI schema.

A real uvicorn server (in a background thread) serves the app against the test
database; Schemathesis generates valid and invalid requests for every operation and
checks that responses never 5xx and conform to the documented status codes, headers and
schemas.

Known, documented exclusions:
* ``POST /api/v1/auth/logout`` is not fuzzed: it would revoke the shared session that
  authenticates every other generated request. It is covered by integration/e2e tests.
* Rate limits are raised for this server so fuzzing is not throttled.

These tests commit data (the server uses its own connections), so all tables are
truncated afterwards to keep other suites isolated.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import schemathesis
import uvicorn
from hypothesis import HealthCheck, settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.main import create_app
from tests.conftest import make_settings

FUZZ_PASSWORD = "Fuzz-passw0rd"
EXCLUDED_OPERATIONS = {("POST", "/api/v1/auth/logout")}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
async def _truncate_after(engine: AsyncEngine) -> AsyncIterator[None]:
    yield
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE users, auth_sessions, refresh_tokens, tasks CASCADE"))


@pytest.fixture(scope="module")
def live_server(migrated_database: str, _truncate_after: None) -> Iterator[str]:
    app = create_app(
        make_settings(
            migrated_database,
            login_rate_limit=100_000,
            register_rate_limit=100_000,
            refresh_rate_limit=100_000,
            log_level="ERROR",
        )
    )
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="on")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{base_url}/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:  # pragma: no cover
        pytest.fail("test server did not start")
    yield base_url
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="module")
def access_token(live_server: str) -> str:
    creds = {"email": "fuzzer@example.com", "password": FUZZ_PASSWORD}
    httpx.post(f"{live_server}/api/v1/auth/register", json=creds, timeout=10)
    response = httpx.post(f"{live_server}/api/v1/auth/login", json=creds, timeout=10)
    response.raise_for_status()
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def api_schema(live_server: str):
    return schemathesis.openapi.from_url(f"{live_server}/openapi.json")


schema = schemathesis.pytest.from_fixture("api_schema")


@schema.parametrize()
@settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=list(HealthCheck),
)
def test_api_conforms_to_schema(case, live_server: str, access_token: str) -> None:
    if (case.method.upper(), case.path) in EXCLUDED_OPERATIONS:
        pytest.skip("excluded: would revoke the shared fuzzing session")
    case.call_and_validate(
        base_url=live_server,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
