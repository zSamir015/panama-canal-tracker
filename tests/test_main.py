from collections.abc import Iterator

import httpx
import pytest
from fastapi import FastAPI

from app.main import create_app


@pytest.fixture
def application() -> Iterator[FastAPI]:
    yield create_app()


@pytest.mark.asyncio
async def test_health_is_public(application: FastAPI) -> None:
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_is_outside_api_prefix(application: FastAPI) -> None:
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cors_allows_configured_origin(application: FastAPI) -> None:
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/health",
            headers={"Origin": "http://localhost:5173"},
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"


@pytest.mark.asyncio
async def test_cors_rejects_unlisted_origin(application: FastAPI) -> None:
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/health",
            headers={"Origin": "https://malicious.example"},
        )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
