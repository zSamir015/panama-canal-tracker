"""Healthcheck del contenedor del worker contra el Redis real (base 15)."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import SecretStr
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.redis import STATUS_KEY, create_redis
from app.workers import healthcheck
from app.workers.ais_consumer import ConsumerStats
from app.workers.ais_publisher import AisPublisher, worker_status
from app.workers.ais_writer import WriterStats


@pytest.fixture
async def redis(
    redis_url: SecretStr, redis_storage: Any, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Redis]:
    settings = Settings(app_env="test", redis_url=redis_url)
    monkeypatch.setattr(healthcheck, "get_settings", lambda: settings)
    client = create_redis(settings)
    await client.delete(STATUS_KEY)
    try:
        yield client
    finally:
        await client.delete(STATUS_KEY)
        await client.aclose()


async def publish(redis: Redis, updated_at: datetime) -> None:
    status = worker_status(
        consumer=ConsumerStats(), writer=WriterStats(), queue_size=0, now=updated_at
    )
    await AisPublisher(redis).publish_status(status)


async def test_recent_status_is_healthy(redis: Redis) -> None:
    await publish(redis, datetime.now(UTC))

    assert await healthcheck.check() is True


async def test_missing_status_is_unhealthy(redis: Redis) -> None:
    assert await healthcheck.check() is False


async def test_old_status_is_unhealthy(redis: Redis) -> None:
    await publish(redis, datetime.now(UTC) - timedelta(minutes=1))

    assert await healthcheck.check() is False


async def test_corrupt_status_is_unhealthy(redis: Redis) -> None:
    await redis.set(STATUS_KEY, b"{no es json", ex=15)

    assert await healthcheck.check() is False


async def test_unreachable_redis_is_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    down = Settings(app_env="test", redis_url="redis://:pw-falsa@127.0.0.1:1/15")  # type: ignore[arg-type]
    monkeypatch.setattr(healthcheck, "get_settings", lambda: down)

    assert await healthcheck.check() is False


def test_exit_code_follows_the_check(monkeypatch: pytest.MonkeyPatch) -> None:
    async def healthy() -> bool:
        return True

    async def unhealthy() -> bool:
        return False

    monkeypatch.setattr(healthcheck, "check", healthy)
    assert healthcheck.main() == 0
    monkeypatch.setattr(healthcheck, "check", unhealthy)
    assert healthcheck.main() == 1
