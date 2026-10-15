import logging
from collections.abc import Iterator

import pytest
import structlog
from fastapi import FastAPI

from app.core.config import Settings
from app.core.logging import UVICORN_LOGGERS


@pytest.fixture(autouse=True)
def isolate_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")


@pytest.fixture(autouse=True)
def reset_logging() -> Iterator[None]:
    """Cada test configura los logs desde cero y deja el estado global como estaba.

    `create_app()` llama a `configure_logging()`, así que también lo necesitan los tests de la app.
    """
    loggers = [logging.getLogger(name) for name in ("", *UVICORN_LOGGERS)]
    saved = [(lg, lg.handlers[:], lg.level, lg.propagate) for lg in loggers]
    yield
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()
    for lg, handlers, level, propagate in saved:
        lg.handlers[:] = handlers
        lg.setLevel(level)
        lg.propagate = propagate


@pytest.fixture
def app_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        cors_origins=["https://tracker.example.com"],
    )


@pytest.fixture
def app(app_settings: Settings) -> Iterator[FastAPI]:
    from app.main import create_app

    yield create_app(app_settings)
