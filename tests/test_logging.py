import io
import json
import logging
import logging.config
from datetime import datetime
from typing import Any

import pytest
import structlog
from uvicorn.config import LOGGING_CONFIG

from app.core.logging import REDACTED, UVICORN_LOGGERS, configure_logging


def lines(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_emits_one_json_object_per_line_with_standard_fields() -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)

    structlog.get_logger("tests").info("vessel_seen", mmsi=123456789)

    [record] = lines(stream)
    assert record["event"] == "vessel_seen"
    assert record["mmsi"] == 123456789
    assert record["level"] == "info"
    assert record["logger"] == "tests"
    assert datetime.fromisoformat(record["timestamp"]).utcoffset() is not None


def test_filters_messages_below_configured_level() -> None:
    stream = io.StringIO()
    configure_logging("WARNING", stream=stream)
    logger = structlog.get_logger()

    logger.info("ignored")
    logger.warning("kept")

    assert [record["event"] for record in lines(stream)] == ["kept"]


def test_stdlib_loggers_are_rendered_as_json() -> None:
    # uvicorn y otras librerías usan `logging`; sus mensajes también deben salir en JSON.
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)

    logging.getLogger("uvicorn.error").info("server started on port %d", 8000)

    [record] = lines(stream)
    assert record["event"] == "server started on port 8000"
    assert record["logger"] == "uvicorn.error"
    assert record["level"] == "info"


def test_redacts_sensitive_fields_at_any_depth() -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)

    structlog.get_logger().info(
        "login_attempt",
        email="demo@example.com",
        password="hunter2-hunter2",
        refresh_token="tok-123",
        headers={"Authorization": "Bearer abc", "Accept": "application/json"},
        AISSTREAM_API_KEY="key-456",
    )

    output = stream.getvalue()
    for secret in ("hunter2-hunter2", "tok-123", "Bearer abc", "key-456"):
        assert secret not in output
    [record] = lines(stream)
    assert record["password"] == REDACTED
    assert record["headers"] == {"Authorization": REDACTED, "Accept": "application/json"}
    assert record["email"] == "demo@example.com"


def test_exceptions_are_serialized_inside_the_json_line() -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        structlog.get_logger().exception("unexpected_error")

    [record] = lines(stream)
    [exception] = record["exception"]
    assert record["event"] == "unexpected_error"
    assert (exception["exc_type"], exception["exc_value"]) == ("RuntimeError", "boom")


def test_tracebacks_do_not_include_local_variables() -> None:
    # Las variables locales de cada frame pueden contener contraseñas o tokens.
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)

    def login(user_input: str) -> None:
        raise RuntimeError("login failed")

    try:
        login("hunter2-hunter2")
    except RuntimeError:
        structlog.get_logger().exception("unexpected_error")

    assert "hunter2-hunter2" not in stream.getvalue()


def test_includes_context_bound_with_contextvars() -> None:
    # Permite que todos los logs de una petición lleven el mismo request_id (AGENTS.md §8.9).
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    structlog.contextvars.bind_contextvars(request_id="req-1")

    structlog.get_logger().info("handled")

    [record] = lines(stream)
    assert record["request_id"] == "req-1"


def test_rejects_unknown_level() -> None:
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        configure_logging("VERBOSE")


@pytest.mark.parametrize("name", UVICORN_LOGGERS)
def test_uvicorn_cli_loggers_are_rendered_as_json(name: str) -> None:
    # `uvicorn app.main:app` instala sus handlers de texto antes de importar la app.
    logging.config.dictConfig(LOGGING_CONFIG)
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)

    logging.getLogger(name).info("request handled")

    [record] = lines(stream)
    assert record["event"] == "request handled"
    assert record["logger"] == name
