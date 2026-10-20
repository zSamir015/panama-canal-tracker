import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from app.core.config import Settings
from app.core.middleware import MAX_BODY_BYTES
from app.main import create_app

PROBLEM_JSON = "application/problem+json"


class Payload(BaseModel):
    name: str
    password: str


def add_test_routes(app: FastAPI) -> FastAPI:
    @app.post("/test/echo")
    async def echo(payload: Payload) -> dict[str, str]:
        return {"name": payload.name}

    @app.post("/test/size")
    async def size(body: dict[str, Any]) -> dict[str, int]:
        return {"keys": len(body)}

    @app.get("/test/boom")
    async def boom() -> None:
        raise RuntimeError("consulta fallida en db-interna:5432")

    return app


def client_for(app: FastAPI) -> httpx.AsyncClient:
    # Sin `raise_app_exceptions` httpx relanza la excepción del 500 en vez de devolver la respuesta.
    transport = httpx.ASGITransport(app=add_test_routes(app), raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def log_lines(output: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in output.splitlines() if line.startswith("{")]


async def test_unknown_route_returns_problem_json(app: FastAPI) -> None:
    async with client_for(app) as client:
        response = await client.get("/no-existe")

    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM_JSON
    body = response.json()
    assert body["type"] == "about:blank"
    assert body["title"] == "Not Found"
    assert body["status"] == 404
    assert body["detail"] == "Recurso no encontrado"
    assert body["instance"] == "/no-existe"
    assert body["request_id"] == response.headers["x-request-id"]


async def test_method_not_allowed_keeps_allow_header(app: FastAPI) -> None:
    async with client_for(app) as client:
        response = await client.delete("/health")

    assert response.status_code == 405
    assert response.headers["content-type"] == PROBLEM_JSON
    assert response.headers["allow"] == "GET"
    assert response.json()["detail"] == "Método no permitido"


async def test_validation_error_lists_fields_without_echoing_input(app: FastAPI) -> None:
    async with client_for(app) as client:
        response = await client.post("/test/echo", json={"password": "hunter2"})

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM_JSON
    body = response.json()
    assert body["detail"] == "La petición contiene datos inválidos"
    assert body["errors"] == [{"loc": ["body", "name"], "msg": "Field required", "type": "missing"}]
    # El input puede traer contraseñas: no se devuelve en la respuesta.
    assert "hunter2" not in response.text


async def test_each_request_gets_a_distinct_request_id(app: FastAPI) -> None:
    async with client_for(app) as client:
        first = await client.get("/health")
        second = await client.get("/health")

    assert len(first.headers["x-request-id"]) == 32
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


async def test_client_supplied_request_id_is_ignored(app: FastAPI) -> None:
    # Aceptarlo permitiría inyectar valores arbitrarios en los logs.
    async with client_for(app) as client:
        response = await client.get("/health", headers={"X-Request-ID": "forged\nlevel=error"})

    assert response.headers["x-request-id"] != "forged\nlevel=error"


@pytest.fixture
def production_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="production",
        cors_origins=["https://tracker.example.com"],
        redis_url="redis://:pw-redis-falsa@redis:6379/0",
        jwt_secret_key="x" * 32,
        database_url="postgresql+asyncpg://canal_app:pw-falsa-de-prueba@db:5432/canal_tracker",
    )


async def test_unhandled_error_in_production_hides_internal_details(
    capsys: pytest.CaptureFixture[str], production_settings: Settings
) -> None:
    async with client_for(create_app(production_settings)) as client:
        response = await client.get("/test/boom")

    assert response.status_code == 500
    assert response.headers["content-type"] == PROBLEM_JSON
    body = response.json()
    assert body == {
        "type": "about:blank",
        "title": "Internal Server Error",
        "status": 500,
        "detail": "Error interno del servidor",
        "instance": "/test/boom",
        "request_id": response.headers["x-request-id"],
    }
    for leak in ("RuntimeError", "db-interna", "5432", "Traceback", "app/"):
        assert leak not in response.text

    # Los detalles van al log, con el mismo request_id para poder buscarlos.
    [record] = [r for r in log_lines(capsys.readouterr().out) if r["event"] == "unhandled_error"]
    assert record["request_id"] == body["request_id"]
    assert record["level"] == "error"
    assert record["exception"][0]["exc_type"] == "RuntimeError"


async def test_body_over_limit_by_content_length_is_rejected(app: FastAPI) -> None:
    async with client_for(app) as client:
        response = await client.post(
            "/test/size",
            content=b"{" + b" " * MAX_BODY_BYTES + b"}",
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 413
    assert response.headers["content-type"] == PROBLEM_JSON
    body = response.json()
    assert body["detail"] == f"El cuerpo de la petición supera el límite de {MAX_BODY_BYTES} bytes"
    assert body["request_id"] == response.headers["x-request-id"]


async def test_declared_size_over_limit_is_rejected_before_reading(app: FastAPI) -> None:
    # /health no lee el body: solo la comprobación previa de Content-Length lo rechaza.
    async with client_for(app) as client:
        response = await client.request("GET", "/health", content=b" " * (MAX_BODY_BYTES + 1))

    assert response.status_code == 413


async def test_chunked_body_over_limit_is_rejected(app: FastAPI) -> None:
    # Sin Content-Length (transfer-encoding chunked) el límite se comprueba mientras se lee.
    async def chunks() -> AsyncIterator[bytes]:
        yield b"{"
        for _ in range(MAX_BODY_BYTES // 1024 + 1):
            yield b" " * 1024
        yield b"}"

    async with client_for(app) as client:
        response = await client.post(
            "/test/size", content=chunks(), headers={"Content-Type": "application/json"}
        )

    assert response.status_code == 413
    assert response.headers["content-type"] == PROBLEM_JSON


async def test_body_at_limit_is_accepted(app: FastAPI) -> None:
    content = b"{" + b" " * (MAX_BODY_BYTES - 2) + b"}"
    assert len(content) == MAX_BODY_BYTES

    async with client_for(app) as client:
        response = await client.post(
            "/test/size", content=content, headers={"Content-Type": "application/json"}
        )

    assert response.status_code == 200
    assert response.json() == {"keys": 0}


async def test_invalid_content_length_is_rejected(app: FastAPI) -> None:
    async with client_for(app) as client:
        response = await client.post(
            "/test/size",
            content=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": "abc"},
        )

    assert response.status_code == 400
    assert response.headers["content-type"] == PROBLEM_JSON
