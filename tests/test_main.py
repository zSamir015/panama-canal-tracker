import httpx
from fastapi import FastAPI


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
