"""Unit tests: structured logging."""

from __future__ import annotations

import json
import logging

from app.core.logging import JsonFormatter, RequestIdFilter, TextFormatter, request_id_ctx


def _record(msg: str = "hello %s", args: tuple = ("x",)) -> logging.LogRecord:
    return logging.LogRecord("app.test", logging.INFO, __file__, 1, msg, args, None)


def test_json_formatter_includes_request_id_and_extras() -> None:
    token = request_id_ctx.set("rid-1")
    try:
        record = _record()
        RequestIdFilter().filter(record)
        record.user_id = "u-1"
        payload = json.loads(JsonFormatter().format(record))
    finally:
        request_id_ctx.reset(token)
    assert payload["message"] == "hello x"
    assert payload["request_id"] == "rid-1"
    assert payload["user_id"] == "u-1"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"


def test_explicit_request_id_wins_over_context() -> None:
    record = _record()
    record.request_id = "explicit"
    RequestIdFilter().filter(record)
    assert record.request_id == "explicit"


def test_json_formatter_serialises_exceptions() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord(
            "app.test", logging.ERROR, __file__, 1, "failed", (), sys.exc_info()
        )
    payload = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in payload["exc_info"]


def test_text_formatter() -> None:
    record = _record()
    RequestIdFilter().filter(record)
    assert "hello x" in TextFormatter().format(record)
