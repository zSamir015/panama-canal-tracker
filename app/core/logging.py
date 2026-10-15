"""Logs estructurados en JSON con structlog (AGENTS.md §3).

Una línea JSON por evento, tanto para los logs propios (`structlog.get_logger()`) como para los de
librerías que usan `logging` (uvicorn, etc.). Los campos sensibles se redactan antes de escribirse:
nunca se loguean tokens, contraseñas ni API keys.
"""

import logging
import sys
from collections.abc import Mapping
from typing import Any, TextIO

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

REDACTED = "[REDACTED]"

# uvicorn configura estos loggers con sus propios handlers de texto y `propagate=False`.
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

# Se comparan en minúsculas y por substring: "refresh_token", "AISSTREAM_API_KEY", etc.
SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
)


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: REDACTED if isinstance(key, str) and _is_sensitive(key) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_redact(item) for item in value]
    return value


def redact_sensitive_fields(
    _logger: WrappedLogger, _method_name: str, event_dict: EventDict
) -> EventDict:
    """Reemplaza el valor de cualquier campo con nombre sensible, a cualquier profundidad."""
    for key, value in event_dict.items():
        event_dict[key] = REDACTED if _is_sensitive(key) else _redact(value)
    return event_dict


def configure_logging(level: str, *, stream: TextIO | None = None) -> None:
    """Configura structlog y `logging` para escribir JSON en `stream` (stdout por defecto).

    Se llama una vez al arrancar el proceso (API o worker) con el `LOG_LEVEL` de la configuración.
    """
    numeric_level = logging.getLevelNamesMapping().get(level.upper())
    if numeric_level is None:
        raise ValueError(f"LOG_LEVEL desconocido: {level!r}")

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        # Traceback como JSON, sin variables locales: pueden contener contraseñas o tokens.
        structlog.processors.ExceptionRenderer(
            structlog.tracebacks.ExceptionDictTransformer(show_locals=False)
        ),
        redact_sensitive_fields,
    ]

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        # Los registros de `logging` (uvicorn...) pasan por los mismos procesadores.
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(numeric_level)

    # Con `uvicorn app.main:app` la CLI ya configuró sus loggers al importar la app: se les
    # quitan los handlers para que sus mensajes suban al root y salgan en JSON.
    for name in UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
