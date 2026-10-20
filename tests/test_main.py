from collections.abc import Iterator

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from starlette.routing import Route

from app.core.config import Settings, get_settings
from app.main import create_app


async def test_health_is_public(app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_is_outside_api_prefix(app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 404


async def test_cors_uses_injected_settings_instead_of_environment(app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        injected_origin_response = await client.get(
            "/health",
            headers={"Origin": "https://tracker.example.com"},
        )
        environment_origin_response = await client.get(
            "/health",
            headers={"Origin": "http://localhost:5173"},
        )

    assert injected_origin_response.status_code == 200
    assert (
        injected_origin_response.headers["access-control-allow-origin"]
        == "https://tracker.example.com"
    )
    assert injected_origin_response.headers["access-control-allow-credentials"] == "true"
    assert "access-control-allow-origin" not in environment_origin_response.headers


async def test_cors_rejects_unlisted_origin(app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/health",
            headers={"Origin": "https://malicious.example"},
        )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


# Rutas que responden sin autenticación (AGENTS.md §8.9). Cualquier ruta nueva hace fallar este
# test hasta que se decida: o se añade aquí justificándolo, o a la lista de protegidas. La 2.7
# completa esto comprobando que las protegidas responden 401 sin token.
PUBLIC_PATHS = {
    "/health",
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/api/v1/auth/register",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
}
PROTECTED_PATHS = {"/api/v1/auth/logout", "/api/v1/auth/me"}


def exposed_paths(app: FastAPI) -> set[str]:
    # Desde FastAPI 0.143 `app.routes` guarda cada router incluido como un solo objeto (sin
    # `path`); sus rutas se ven en el esquema OpenAPI. Las de nivel superior, en `app.routes`.
    top_level = {route.path for route in app.routes if isinstance(route, Route)}
    return top_level | set(app.openapi()["paths"])


def test_only_whitelisted_routes_are_exposed(app: FastAPI) -> None:
    paths = exposed_paths(app)

    assert paths == PUBLIC_PATHS | PROTECTED_PATHS


@pytest.mark.parametrize("app_env", ["development", "test", "production"])
def test_app_never_runs_in_debug_mode(app_env: str) -> None:
    # Con debug=True Starlette responde los 500 con la traza completa en HTML (AGENTS.md §8.12).
    settings = Settings(
        _env_file=None,
        app_env=app_env,  # type: ignore[arg-type]
        cors_origins=["https://tracker.example.com"],
        jwt_secret_key="x" * 32,
        database_url="postgresql+asyncpg://canal_app:pw-falsa-de-prueba@db:5432/canal_tracker",
        redis_url="redis://:pw-redis-falsa-de-prueba@redis:6379/0",
    )

    assert create_app(settings).debug is False


@pytest.fixture
def fresh_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.usefixtures("fresh_settings_cache")
def test_app_refuses_to_start_with_insecure_production_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Sin settings inyectadas, create_app() lee el entorno: así arranca `uvicorn app.main:app`.
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CORS_ORIGINS", "https://tracker.example.com")
    monkeypatch.setenv("JWT_SECRET_KEY", "corto")

    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        create_app()
