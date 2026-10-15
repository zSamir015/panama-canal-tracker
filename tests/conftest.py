from collections.abc import Iterator

import pytest
from fastapi import FastAPI

from app.core.config import Settings


@pytest.fixture(autouse=True)
def isolate_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")


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
