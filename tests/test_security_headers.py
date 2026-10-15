import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.main import create_app

ALLOWED_ORIGIN = "https://tracker.example.com"
SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "cross-origin-resource-policy": "same-site",
}


def add_test_routes(app: FastAPI) -> FastAPI:
    @app.post("/api/v1/auth/login")
    async def login() -> dict[str, str]:
        return {"access_token": "fake"}

    @app.get("/test/boom")
    async def boom() -> None:
        raise RuntimeError("fallo")

    return app


def client_for(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=add_test_routes(app), raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def assert_security_headers(response: httpx.Response) -> None:
    for name, value in SECURITY_HEADERS.items():
        assert response.headers.get(name) == value, name
    # Obsoleto y a veces dañino: los navegadores actuales lo ignoran (AGENTS.md §8.11).
    assert "x-xss-protection" not in response.headers


def preflight_headers(origin: str, method: str = "POST", headers: str = "") -> dict[str, str]:
    result = {"Origin": origin, "Access-Control-Request-Method": method}
    if headers:
        result["Access-Control-Request-Headers"] = headers
    return result


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [("GET", "/health", 200), ("GET", "/no-existe", 404), ("DELETE", "/health", 405)],
)
async def test_security_headers_on_every_response(
    app: FastAPI, method: str, path: str, status: int
) -> None:
    async with client_for(app) as client:
        response = await client.request(method, path)

    assert response.status_code == status
    assert_security_headers(response)


async def test_security_headers_on_body_limit_rejection(app: FastAPI) -> None:
    async with client_for(app) as client:
        response = await client.post("/health", content=b" " * (64 * 1024 + 1))

    assert response.status_code == 413
    assert_security_headers(response)


async def test_security_headers_on_unhandled_error() -> None:
    # Starlette envía el 500 por fuera de los middlewares: hay que ponerlas también ahí.
    settings = Settings(_env_file=None, app_env="test", cors_origins=[ALLOWED_ORIGIN])
    async with client_for(create_app(settings)) as client:
        response = await client.get("/test/boom")

    assert response.status_code == 500
    assert_security_headers(response)


async def test_auth_responses_are_not_cached(app: FastAPI) -> None:
    async with client_for(app) as client:
        auth_response = await client.post("/api/v1/auth/login")
        health_response = await client.get("/health")

    assert auth_response.headers["cache-control"] == "no-store"
    assert "cache-control" not in health_response.headers


async def test_cors_preflight_from_allowed_origin(app: FastAPI) -> None:
    async with client_for(app) as client:
        response = await client.options(
            "/api/v1/auth/login",
            headers=preflight_headers(ALLOWED_ORIGIN, headers="Authorization, Content-Type"),
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    assert response.headers["access-control-max-age"] == "600"
    assert_security_headers(response)


@pytest.mark.parametrize(
    "request_headers",
    [
        preflight_headers("https://malicious.example"),
        preflight_headers(ALLOWED_ORIGIN, method="PUT"),
        preflight_headers(ALLOWED_ORIGIN, headers="X-Custom"),
    ],
    ids=["origin", "method", "header"],
)
async def test_cors_preflight_rejection_is_problem_json_without_policy(
    app: FastAPI, request_headers: dict[str, str]
) -> None:
    async with client_for(app) as client:
        response = await client.options("/api/v1/auth/login", headers=request_headers)

    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["detail"] == "Petición CORS no permitida"
    assert body["request_id"] == response.headers["x-request-id"]
    # No se anuncia la política a quien no está autorizado.
    assert not [name for name in response.headers if name.startswith("access-control-")]
    assert "origin" in response.headers["vary"].lower()
    assert_security_headers(response)


async def test_frontend_can_read_request_id(app: FastAPI) -> None:
    async with client_for(app) as client:
        response = await client.get("/health", headers={"Origin": ALLOWED_ORIGIN})

    assert response.headers["access-control-expose-headers"] == "X-Request-ID"
