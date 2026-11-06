"""`/ready` y `/metrics` (7.1) con PostgreSQL y Redis reales (base 15)."""

import re
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
from app.core.redis import STATUS_KEY, create_redis
from app.main import create_app
from app.repositories.ais import AisRepository, VesselRow
from app.repositories.anchorages import AnchorageRepository, OpenVisitRow
from app.repositories.transits import OpenTransitRow, TransitRepository
from app.routers import infrastructure
from app.workers.ais_consumer import ConsumerStats
from app.workers.ais_publisher import AisPublisher, worker_status
from app.workers.ais_writer import WriterStats

TOKEN = "t" * 40
NOW = datetime.now(UTC).replace(microsecond=0)


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
async def app(migrated: AsyncEngine, db_settings: Settings, redis: Redis) -> AsyncIterator[FastAPI]:
    app = create_app(db_settings.model_copy(update={"metrics_token": SecretStr(TOKEN)}))
    app.dependency_overrides[infrastructure._redis] = lambda: redis  # la base 15
    yield app
    app.dependency_overrides.clear()
    await app.state.engine.dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        yield c


def bearer(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def publish(redis: Redis, *, last_message_seconds_ago: int | None = 42) -> None:
    consumer = ConsumerStats(connections=1, connected=True, subscribed=True, received=500)
    consumer.dropped = 3
    if last_message_seconds_ago is not None:
        consumer.last_message_at = datetime.now(UTC) - timedelta(seconds=last_message_seconds_ago)
    status = worker_status(
        consumer=consumer,
        writer=WriterStats(batches=10, positions_written=480),
        queue_size=4,
    )
    await AisPublisher(redis).publish_status(status)


def parse(text: str) -> dict[str, float]:
    """Las muestras del texto de Prometheus, con sus etiquetas en la clave."""
    return {
        line.rsplit(" ", 1)[0]: float(line.rsplit(" ", 1)[1])
        for line in text.splitlines()
        if line and not line.startswith("#")
    }


# --- /ready ---------------------------------------------------------------------------------


async def test_ready_when_database_and_redis_respond(client: AsyncClient) -> None:
    response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok", "redis": "ok"},
    }


async def test_ready_needs_no_token(client: AsyncClient) -> None:
    assert (await client.get("/ready")).status_code == 200  # sin Authorization


async def test_ready_is_503_and_names_redis_when_it_is_down(
    client: AsyncClient, app: FastAPI
) -> None:
    class DownRedis:
        async def ping(self) -> bool:
            raise ConnectionError("redis caído, y no debe salir en la respuesta")

    app.dependency_overrides[infrastructure._redis] = lambda: DownRedis()

    response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"database": "ok", "redis": "failed"},
    }
    assert "caído" not in response.text


async def test_ready_is_503_and_names_the_database_when_it_is_down(
    client: AsyncClient, app: FastAPI
) -> None:
    class BrokenSession:
        async def __aenter__(self) -> "BrokenSession":
            raise OSError("base caída, y no debe salir en la respuesta")

        async def __aexit__(self, *_: object) -> None:
            return None

    app.dependency_overrides[infrastructure._session_factory] = lambda: BrokenSession
    response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "failed", "redis": "ok"}
    assert "caída" not in response.text


async def test_ready_is_503_when_both_are_down(client: AsyncClient, app: FastAPI) -> None:
    class DownRedis:
        async def ping(self) -> bool:
            raise ConnectionError

    class BrokenSession:
        async def __aenter__(self) -> "BrokenSession":
            raise OSError

        async def __aexit__(self, *_: object) -> None:
            return None

    app.dependency_overrides[infrastructure._redis] = lambda: DownRedis()
    app.dependency_overrides[infrastructure._session_factory] = lambda: BrokenSession

    response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "failed", "redis": "failed"}


# --- /metrics: acceso -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [{}, bearer("otro" * 12), {"Authorization": "Basic " + TOKEN}, {"Authorization": "Bearer "}],
    ids=["sin_token", "token_distinto", "esquema_basic", "token_vacio"],
)
async def test_metrics_rejects_a_missing_or_wrong_token(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    response = await client.get("/metrics", headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["content-type"] == "application/problem+json"
    assert "canal_up" not in response.text


async def test_a_user_jwt_is_not_a_metrics_token(app: FastAPI, client: AsyncClient) -> None:
    from app.core.security import create_access_token, hash_password
    from app.models.user import UserRole
    from app.repositories.user import UserRepository

    factory: SessionFactory = app.state.session_factory
    async with factory() as session:
        user = await UserRepository(session).add(
            email="admin@example.com",
            hashed_password=hash_password("una frase larga de prueba"),
            role=UserRole.ADMIN,
        )
        await session.commit()
    jwt, _ = create_access_token(user.id, app.state.settings)

    response = await client.get("/metrics", headers=bearer(jwt))

    assert response.status_code == 401


async def test_metrics_is_closed_when_no_token_is_configured(
    db_settings: Settings, migrated: AsyncEngine, redis: Redis
) -> None:
    app = create_app(db_settings)  # sin METRICS_TOKEN
    app.dependency_overrides[infrastructure._redis] = lambda: redis
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        for headers in ({}, bearer(), bearer("")):
            assert (await c.get("/metrics", headers=headers)).status_code == 401
    await app.state.engine.dispose()


# --- /metrics: contenido --------------------------------------------------------------------


async def test_metrics_report_the_worker_and_the_counts(
    client: AsyncClient, redis: Redis, app: FastAPI
) -> None:
    await publish(redis)
    factory: SessionFactory = app.state.session_factory
    async with factory() as session:
        await AisRepository(session).upsert_vessels(
            [VesselRow(mmsi=352000001), VesselRow(mmsi=352000002), VesselRow(mmsi=352000003)]
        )
        transits = TransitRepository(session)
        await transits.open_transit(OpenTransitRow(352000001, "southbound", NOW))
        await transits.open_transit(OpenTransitRow(352000002, "northbound", NOW))
        await AnchorageRepository(session).open_visit(
            OpenVisitRow(352000003, "atlantic", NOW - timedelta(hours=3))
        )
        await session.commit()

    response = await client.get("/metrics", headers=bearer())

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; version=0.0.4; charset=utf-8"
    values = parse(response.text)
    assert values["canal_up"] == 1
    assert values['canal_dependency_up{name="database"}'] == 1
    assert values['canal_dependency_up{name="redis"}'] == 1
    assert values["canal_ais_worker_available"] == 1
    assert values["canal_ais_worker_connected"] == 1
    assert values["canal_ais_messages_received_total"] == 500
    assert values["canal_ais_messages_dropped_total"] == 3
    assert values["canal_ais_positions_written_total"] == 480
    assert values["canal_ais_queue_size"] == 4
    assert 40 <= values["canal_ais_last_message_age_seconds"] < 50
    assert values["canal_transits_in_progress"] == 2
    assert values["canal_anchorage_visits_open"] == 1


async def test_metrics_say_the_worker_is_gone_when_it_published_nothing(
    client: AsyncClient,
) -> None:
    values = parse((await client.get("/metrics", headers=bearer())).text)

    assert values["canal_ais_worker_available"] == 0
    assert "canal_ais_last_message_age_seconds" not in values
    assert "canal_ais_messages_received_total" not in values


async def test_metrics_without_any_message_have_no_age(client: AsyncClient, redis: Redis) -> None:
    await publish(redis, last_message_seconds_ago=None)

    values = parse((await client.get("/metrics", headers=bearer())).text)

    assert values["canal_ais_worker_available"] == 1
    assert "canal_ais_last_message_age_seconds" not in values


async def test_a_scrape_survives_redis_down_and_reports_it(
    client: AsyncClient, app: FastAPI
) -> None:
    class DownRedis:
        async def get(self, _key: str) -> bytes:
            from redis.exceptions import ConnectionError as RedisConnectionError

            raise RedisConnectionError("caído")

    app.dependency_overrides[infrastructure._redis] = lambda: DownRedis()

    response = await client.get("/metrics", headers=bearer())

    assert response.status_code == 200
    values = parse(response.text)
    assert values['canal_dependency_up{name="redis"}'] == 0
    assert values['canal_dependency_up{name="database"}'] == 1
    assert values["canal_transits_in_progress"] == 0
    assert "canal_ais_worker_available" not in values


async def test_a_scrape_survives_the_database_down_and_reports_it(
    client: AsyncClient, app: FastAPI
) -> None:
    class BrokenSession:
        async def __aenter__(self) -> "BrokenSession":
            raise OSError("base caída")

        async def __aexit__(self, *_: object) -> None:
            return None

    app.dependency_overrides[infrastructure._session_factory] = lambda: BrokenSession

    response = await client.get("/metrics", headers=bearer())

    assert response.status_code == 200
    values = parse(response.text)
    assert values['canal_dependency_up{name="database"}'] == 0
    assert "canal_transits_in_progress" not in values
    assert values["canal_up"] == 1


async def test_the_exposition_never_carries_vessel_text(
    client: AsyncClient, redis: Redis, app: FastAPI
) -> None:
    await publish(redis)
    factory: SessionFactory = app.state.session_factory
    async with factory() as session:
        await AisRepository(session).upsert_vessels(
            [VesselRow(mmsi=352000001, name="<img src=x onerror=alert(1)>")]
        )
        await TransitRepository(session).open_transit(OpenTransitRow(352000001, "southbound", NOW))
        await session.commit()

    text = (await client.get("/metrics", headers=bearer())).text

    assert "img" not in text and "352000001" not in text
    for line in text.splitlines():
        assert line.startswith("# ") or re.match(r"^canal_[a-z_]+(\{.*\})? -?[0-9.]+$", line), line
