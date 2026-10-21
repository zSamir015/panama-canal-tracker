"""Publisher AIS contra Redis y PostgreSQL reales.

Las claves van a la base 15 de Redis (`redis_url` del conftest). El Pub/Sub de Redis no depende
de la base: el canal es el mismo que en desarrollo, pero en desarrollo nadie está suscrito aún.
"""

import asyncio
import io
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.db import SessionFactory
from app.core.logging import configure_logging
from app.core.redis import LIVE_CHANNEL, STATUS_KEY, create_redis
from app.models.position import Position
from app.repositories.ais import AisRepository
from app.services.ais_parser import PositionUpdate, VesselStatic
from app.workers.ais_consumer import run_worker
from app.workers.ais_publisher import AisPublisher
from app.workers.ais_writer import AisWriter
from tests.scripts_loader import load_script

T0 = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


def position(mmsi: int = 352000001, seconds: int = 0) -> PositionUpdate:
    return PositionUpdate(
        mmsi=mmsi,
        received_at=T0 + timedelta(seconds=seconds),
        lat=9.35,
        lon=-79.91,
        sog=7.8,
        cog=145.2,
        heading=146,
        nav_status=0,
    )


STATIC = VesselStatic(
    mmsi=352000001, name="PACIFIC STAR", imo=9100001, ship_type=70, length_m=225.0, beam_m=32.0
)


@pytest.fixture
async def sessions(migrated: AsyncEngine, db_app: FastAPI) -> AsyncIterator[SessionFactory]:
    factory: SessionFactory = db_app.state.session_factory
    yield factory


@pytest.fixture
async def redis(redis_url: SecretStr, redis_storage: Any) -> AsyncIterator[Redis]:
    # `redis_storage` deja la base 15 vacía antes y después del test.
    client = Redis.from_url(redis_url.get_secret_value())
    await client.delete(STATUS_KEY)
    try:
        yield client
    finally:
        await client.delete(STATUS_KEY)
        await client.aclose()


@pytest.fixture
def publisher(redis_url: SecretStr) -> AisPublisher:
    return AisPublisher(create_redis(Settings(app_env="test", redis_url=redis_url)))


async def next_live_message(subscriber: Any, wait_seconds: float = 3.0) -> dict[str, Any] | None:
    async with asyncio.timeout(wait_seconds):
        while True:
            message = await subscriber.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if message is not None:
                data: dict[str, Any] = json.loads(message["data"])
                return data


def writer_for(sessions: SessionFactory, publisher: AisPublisher) -> AisWriter:
    return AisWriter(
        queue=asyncio.Queue(),
        session_factory=sessions,
        on_committed=publisher.publish_batch,
        retry_base_seconds=0.001,
        retry_max_seconds=0.01,
        max_attempts=2,
    )


async def count_positions(sessions: SessionFactory) -> int:
    async with sessions() as session:
        return int((await session.execute(select(func.count()).select_from(Position))).scalar_one())


# --- Publicación tras el commit -------------------------------------------------------------


async def test_saved_batch_is_published_on_the_live_channel(
    sessions: SessionFactory, redis: Redis, publisher: AisPublisher
) -> None:
    subscriber = redis.pubsub()
    await subscriber.subscribe(LIVE_CHANNEL)
    try:
        await writer_for(sessions, publisher).flush([STATIC, position()])
        message = await next_live_message(subscriber)
    finally:
        await subscriber.aclose()
        await publisher.close()

    assert message is not None
    [vessel] = message["vessels"]
    assert (vessel["mmsi"], vessel["name"], vessel["lon"], vessel["lat"]) == (
        352000001,
        "PACIFIC STAR",
        -79.91,
        9.35,
    )


async def test_nothing_is_published_when_the_batch_is_not_saved(
    sessions: SessionFactory,
    redis: Redis,
    publisher: AisPublisher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken_insert(self: AisRepository, rows: Any) -> int:
        raise OSError("conexión perdida")

    monkeypatch.setattr(AisRepository, "insert_positions", broken_insert)
    subscriber = redis.pubsub()
    await subscriber.subscribe(LIVE_CHANNEL)
    try:
        await writer_for(sessions, publisher).flush([position()])
        with pytest.raises(TimeoutError):
            await next_live_message(subscriber, wait_seconds=0.5)
    finally:
        await subscriber.aclose()
        await publisher.close()

    assert publisher.stats.messages_published == 0


async def test_status_key_is_stored_with_an_expiry(redis: Redis, publisher: AisPublisher) -> None:
    from app.workers.ais_consumer import ConsumerStats
    from app.workers.ais_publisher import worker_status
    from app.workers.ais_writer import WriterStats

    status = worker_status(
        consumer=ConsumerStats(connected=True), writer=WriterStats(), queue_size=3
    )
    await publisher.publish_status(status)
    await publisher.close()

    stored = json.loads(await redis.get(STATUS_KEY))
    ttl = await redis.ttl(STATUS_KEY)
    assert stored["connected"] is True
    assert stored["queue_size"] == 3
    assert 0 < ttl <= 15


# --- Redis caído: la ingesta sigue ----------------------------------------------------------


async def test_positions_are_still_saved_when_redis_is_down(sessions: SessionFactory) -> None:
    down = AisPublisher(
        create_redis(
            Settings(app_env="test", redis_url="redis://:pw-falsa@127.0.0.1:1/15")  # type: ignore[arg-type]
        )
    )
    writer = writer_for(sessions, down)

    await writer.flush([position(seconds=0), position(seconds=10)])
    await writer.flush([position(seconds=20)])  # durante la pausa tras el fallo
    await down.close()

    assert await count_positions(sessions) == 3
    assert writer.stats.batches_dropped == 0
    assert down.stats.failures == 1
    assert down.stats.skipped == 1


async def test_redis_password_never_reaches_the_logs(
    sessions: SessionFactory, redis_url: SecretStr
) -> None:
    # Contraseña equivocada contra el Redis real: falla la autenticación.
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(redis_url.get_secret_value())
    wrong = urlunsplit(
        parts._replace(netloc=f":pw-incorrecta-secreta@{parts.hostname}:{parts.port}")
    )
    stream = io.StringIO()
    configure_logging("DEBUG", stream=stream)
    publisher = AisPublisher(create_redis(Settings(app_env="test", redis_url=wrong)))  # type: ignore[arg-type]

    await writer_for(sessions, publisher).flush([position()])
    await publisher.close()

    output = stream.getvalue()
    assert "redis_publish_failed" in output
    assert "pw-incorrecta-secreta" not in output
    assert redis_url.get_secret_value() not in output
    assert await count_positions(sessions) == 1


# --- Worker completo ------------------------------------------------------------------------


async def test_worker_publishes_live_traffic_and_its_status(
    migrated: AsyncEngine,
    db_settings: Settings,
    redis_url: SecretStr,
    redis: Redis,
    sessions: SessionFactory,
) -> None:
    sim = load_script("ais_simulator")
    server = await sim.start_server(
        sim.generate(start=T0, duration=timedelta(minutes=10), seed=1), port=0, speed=0
    )
    port = next(iter(server.sockets)).getsockname()[1]
    settings = db_settings.model_copy(
        update={
            "aisstream_url": f"ws://127.0.0.1:{port}",
            "aisstream_api_key": SecretStr("clave-de-pruebas"),
            "redis_url": redis_url,
            "ais_batch_flush_seconds": 0.05,
        }
    )
    subscriber = redis.pubsub()
    await subscriber.subscribe(LIVE_CHANNEL)
    stop = asyncio.Event()
    try:
        task = asyncio.create_task(run_worker(settings, stop, status_interval=0.05))
        message = await next_live_message(subscriber, wait_seconds=10)
        await asyncio.sleep(0.2)
        running = json.loads(await redis.get(STATUS_KEY))
        stop.set()
        await asyncio.wait_for(task, timeout=10)
    finally:
        await subscriber.aclose()
        server.close()
        await server.wait_closed()

    assert message is not None and message["type"] == "update"
    # Con speed=0 el simulador cierra al terminar: el worker puede estar entre dos conexiones.
    assert running["connections"] >= 1
    assert running["positions_written"] > 0
    updated = datetime.fromisoformat(running["updated_at"])
    assert datetime.now(UTC) - updated < timedelta(seconds=5)
    final = json.loads(await redis.get(STATUS_KEY))
    assert final["connected"] is False  # último estado al parar
    assert await redis.ttl(STATUS_KEY) > 0
