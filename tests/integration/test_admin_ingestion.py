"""`GET /api/v1/admin/ingestion/status` con PostgreSQL y Redis reales (base 15).

El estado lo escribe el publisher real del worker: prueba también el contrato entre los dos.
"""

import io
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.db import SessionFactory
from app.core.logging import configure_logging
from app.core.redis import STATUS_KEY, create_redis
from app.core.security import create_access_token, hash_password
from app.models.user import UserRole
from app.repositories.user import UserRepository
from app.routers.admin import get_redis
from app.workers.ais_consumer import ConsumerStats
from app.workers.ais_publisher import AisPublisher, worker_status
from app.workers.ais_writer import WriterStats

STATUS = "/api/v1/admin/ingestion/status"


@pytest.fixture
async def redis(redis_url: SecretStr, redis_storage: Any) -> AsyncIterator[Redis]:
    client = create_redis(Settings(app_env="test", redis_url=redis_url))
    await client.delete(STATUS_KEY)
    try:
        yield client
    finally:
        await client.delete(STATUS_KEY)
        await client.aclose()


@pytest.fixture
async def app(migrated: AsyncEngine, db_app: FastAPI, redis: Redis) -> AsyncIterator[FastAPI]:
    db_app.dependency_overrides[get_redis] = lambda: redis  # la base 15, no la de desarrollo
    yield db_app
    db_app.dependency_overrides.clear()


async def client_as(app: FastAPI, role: UserRole | None) -> AsyncClient:
    headers = {}
    if role is not None:
        factory: SessionFactory = app.state.session_factory
        async with factory() as session:
            user = await UserRepository(session).add(
                email=f"{role.value}@example.com",
                hashed_password=hash_password("una frase larga de prueba"),
                role=role,
            )
            await session.commit()
        token, _ = create_access_token(user.id, app.state.settings)
        headers["Authorization"] = f"Bearer {token}"
    return AsyncClient(transport=ASGITransport(app=app), base_url="https://test", headers=headers)


@pytest.fixture
async def admin(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with await client_as(app, UserRole.ADMIN) as c:
        yield c


async def publish(redis: Redis, *, updated_at: datetime | None = None) -> None:
    consumer = ConsumerStats(connections=2, connected=True, subscribed=True, received=500)
    consumer.rejected["invalid_mmsi"] = 3
    status = worker_status(
        consumer=consumer,
        writer=WriterStats(batches=10, positions_written=480),
        queue_size=4,
        now=updated_at,
    )
    await AisPublisher(redis).publish_status(status)


# --- Autorización ---------------------------------------------------------------------------


async def test_without_token_is_401(app: FastAPI) -> None:
    async with await client_as(app, None) as anonymous:
        assert (await anonymous.get(STATUS)).status_code == 401


async def test_normal_user_is_403(app: FastAPI) -> None:
    async with await client_as(app, UserRole.USER) as user:
        response = await user.get(STATUS)

    assert response.status_code == 403
    assert response.headers["content-type"] == "application/problem+json"


# --- Estado ---------------------------------------------------------------------------------


async def test_admin_sees_what_the_worker_published(admin: AsyncClient, redis: Redis) -> None:
    await publish(redis)

    response = await admin.get(STATUS)

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["stale"] is False
    assert 0 <= body["age_seconds"] < 5
    status = body["status"]
    assert (status["connected"], status["connections"], status["received"]) == (True, 2, 500)
    assert status["rejected"] == {"invalid_mmsi": 3}
    assert (status["positions_written"], status["queue_size"]) == (480, 4)


async def test_no_status_means_no_data_not_an_error(admin: AsyncClient) -> None:
    # La clave caducó (worker parado) o nunca existió.
    response = await admin.get(STATUS)

    assert response.status_code == 200
    assert response.json() == {
        "available": False,
        "stale": False,
        "age_seconds": None,
        "status": None,
    }


async def test_an_old_status_is_flagged_as_stale(admin: AsyncClient, redis: Redis) -> None:
    await publish(redis, updated_at=datetime.now(UTC) - timedelta(minutes=2))

    body = (await admin.get(STATUS)).json()

    assert body["available"] is True
    assert body["stale"] is True
    assert body["age_seconds"] >= 120


async def test_a_corrupt_status_is_not_returned(admin: AsyncClient, redis: Redis) -> None:
    await redis.set(STATUS_KEY, b'{"connected": "<script>", "extra": 1}', ex=15)

    body = (await admin.get(STATUS)).json()

    assert body["available"] is False
    assert body["status"] is None


async def test_redis_down_is_503(app: FastAPI, admin: AsyncClient) -> None:
    down = create_redis(
        Settings(app_env="test", redis_url="redis://:pw-falsa@127.0.0.1:1/15")  # type: ignore[arg-type]
    )
    app.dependency_overrides[get_redis] = lambda: down

    response = await admin.get(STATUS)
    await down.aclose()

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["detail"] == "El estado de la ingesta no está disponible"
    assert "pw-falsa" not in response.text


# --- Auditoría ------------------------------------------------------------------------------


async def test_every_view_is_audited_without_the_token(app: FastAPI, admin: AsyncClient) -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)

    await admin.get(STATUS)

    [event] = [
        json.loads(line)
        for line in stream.getvalue().splitlines()
        if json.loads(line)["event"] == "admin_action"
    ]
    assert event["action"] == "ingestion_status_viewed"
    assert event["logger"] == "audit"
    assert event["user_id"]
    assert admin.headers["Authorization"].removeprefix("Bearer ") not in stream.getvalue()


async def test_a_status_with_unknown_fields_is_not_returned(
    admin: AsyncClient, redis: Redis
) -> None:
    # Worker y API se despliegan juntos: un campo que la API no conoce es un estado que no
    # debería existir, no algo que reenviar a ciegas.
    await publish(redis)
    stored = json.loads(await redis.get(STATUS_KEY))
    await redis.set(STATUS_KEY, json.dumps(stored | {"debug_dump": "..."}).encode(), ex=15)

    assert (await admin.get(STATUS)).json()["available"] is False


def test_redis_names_are_the_documented_ones() -> None:
    # docs/ARCHITECTURE.md, la Fase 4 (/ws/live) y quien depure con redis-cli usan estos nombres.
    from app.core.redis import LIVE_CHANNEL

    assert LIVE_CHANNEL == "canal:vessels.live"
    assert STATUS_KEY == "canal:ais:worker:status"
