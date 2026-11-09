"""Contract test: the published OpenAPI document must not change unintentionally.

When an API change is intended, regenerate the snapshot and commit it with the change:

    UPDATE_OPENAPI_SNAPSHOT=1 pytest tests/contract/test_openapi_snapshot.py
    # or: make openapi-snapshot

Reviewers then see the exact contract diff in the pull request.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.main import create_app
from tests.conftest import make_settings

SNAPSHOT = Path(__file__).with_name("openapi_snapshot.json")


def _current_schema() -> dict:
    # No database access needed: building the schema only inspects routes and models.
    app = create_app(make_settings("postgresql+asyncpg://unused@localhost/unused"))
    return app.openapi()


def test_openapi_matches_snapshot() -> None:
    current = _current_schema()
    rendered = json.dumps(current, indent=2, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_OPENAPI_SNAPSHOT") == "1" or not SNAPSHOT.exists():
        SNAPSHOT.write_text(rendered, encoding="utf-8", newline="\n")
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert current == expected, (
        "OpenAPI contract changed. If intended, run "
        "`UPDATE_OPENAPI_SNAPSHOT=1 pytest tests/contract/test_openapi_snapshot.py` "
        "and commit tests/contract/openapi_snapshot.json."
    )


def test_contract_invariants() -> None:
    """Properties clients rely on, independent of the snapshot."""
    schema = _current_schema()
    paths = schema["paths"]
    expected_operations = {
        ("/api/v1/auth/register", "post"),
        ("/api/v1/auth/login", "post"),
        ("/api/v1/auth/refresh", "post"),
        ("/api/v1/auth/logout", "post"),
        ("/api/v1/users/me", "get"),
        ("/api/v1/users/me", "patch"),
        ("/api/v1/users", "get"),
        ("/api/v1/users/{user_id}", "get"),
        ("/api/v1/users/{user_id}", "patch"),
        ("/api/v1/tasks", "post"),
        ("/api/v1/tasks", "get"),
        ("/api/v1/tasks/{task_id}", "get"),
        ("/api/v1/tasks/{task_id}", "patch"),
        ("/api/v1/tasks/{task_id}", "delete"),
        ("/health", "get"),
        ("/ready", "get"),
    }
    actual = {(p, m) for p, ops in paths.items() for m in ops}
    assert actual == expected_operations

    components = schema["components"]["schemas"]
    # Secrets are never part of any response model.
    for name in ("UserRead", "TaskRead"):
        assert "password_hash" not in components[name]["properties"]
    # Every documented 422 uses the shared error envelope.
    for path, ops in paths.items():
        for method, op in ops.items():
            if "422" in op.get("responses", {}):
                ref = op["responses"]["422"]["content"]["application/json"]["schema"]["$ref"]
                assert ref.endswith("/ErrorResponse"), (path, method)
    # Protected operations declare bearer security.
    assert paths["/api/v1/tasks"]["get"]["security"] == [{"HTTPBearer": []}]
    assert "security" not in paths["/health"]["get"]
