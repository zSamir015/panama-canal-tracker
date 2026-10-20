"""Rate limiting contra el Redis real de `docker compose` (ADR-0007).

Usa la base 15 de Redis, no la 0 de desarrollo, y la vacía al terminar.
"""

from collections.abc import AsyncIterator
from urllib.parse import urlsplit, urlunsplit

import pytest
from fastapi import HTTPException
from limits.aio.storage import RedisStorage
from pydantic import SecretStr
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.rate_limit import REGISTER_PER_IP, AppRateLimiter, create_storage

TEST_REDIS_DB = 15
NO_REDIS_HELP = (
    "No se pudo conectar a Redis con REDIS_URL. Levántalo con: docker compose up -d --wait. "
    "Para ejecutar solo los tests unitarios: pytest -m 'not integration'"
)


def with_test_db(url: SecretStr) -> SecretStr:
    parts = urlsplit(url.get_secret_value())
    return SecretStr(urlunsplit(parts._replace(path=f"/{TEST_REDIS_DB}")))


@pytest.fixture
def redis_url() -> SecretStr:
    return with_test_db(Settings(app_env="test").redis_url)


@pytest.fixture
async def storage(redis_url: SecretStr) -> AsyncIterator[RedisStorage]:
    settings = Settings(app_env="test", redis_url=redis_url)
    redis = create_storage(settings)
    if not await redis.check():
        pytest.fail(NO_REDIS_HELP, pytrace=False)
    await redis.reset()
    yield redis
    await redis.reset()


async def test_two_replicas_share_the_same_counter(storage: RedisStorage) -> None:
    # Dos instancias de la API (dos procesos) con el mismo Redis: el cupo es uno solo.
    replica_a = AppRateLimiter(storage)
    replica_b = AppRateLimiter(storage)

    await replica_a.check_auth(REGISTER_PER_IP, "register", "ip", "203.0.113.10")
    await replica_b.check_auth(REGISTER_PER_IP, "register", "ip", "203.0.113.10")
    await replica_a.check_auth(REGISTER_PER_IP, "register", "ip", "203.0.113.10")

    with pytest.raises(HTTPException) as caught:
        await replica_b.check_auth(REGISTER_PER_IP, "register", "ip", "203.0.113.10")

    assert caught.value.status_code == 429
    assert caught.value.headers is not None
    assert 1 <= int(caught.value.headers["Retry-After"]) <= 60


async def test_redis_keys_carry_the_app_prefix(storage: RedisStorage, redis_url: SecretStr) -> None:
    await AppRateLimiter(storage).check_api(REGISTER_PER_IP, "api", "user", "u-1")

    client = Redis.from_url(redis_url.get_secret_value(), decode_responses=True)
    try:
        keys = [key async for key in client.scan_iter()]
    finally:
        await client.aclose()

    assert keys
    assert all(key.startswith("canal_rate_limit") for key in keys)
