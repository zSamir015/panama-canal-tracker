"""Rate limiting contra el Redis real de `docker compose` (ADR-0007).

`redis_storage` (conftest) usa la base 15 de Redis, no la 0 de desarrollo, y la vacía al terminar.
"""

import pytest
from fastapi import HTTPException
from limits.aio.storage import RedisStorage
from pydantic import SecretStr
from redis.asyncio import Redis

from app.core.rate_limit import REGISTER_PER_IP, AppRateLimiter


async def test_two_replicas_share_the_same_counter(redis_storage: RedisStorage) -> None:
    # Dos instancias de la API (dos procesos) con el mismo Redis: el cupo es uno solo.
    replica_a = AppRateLimiter(redis_storage)
    replica_b = AppRateLimiter(redis_storage)

    await replica_a.check_auth(REGISTER_PER_IP, "register", "ip", "203.0.113.10")
    await replica_b.check_auth(REGISTER_PER_IP, "register", "ip", "203.0.113.10")
    await replica_a.check_auth(REGISTER_PER_IP, "register", "ip", "203.0.113.10")

    with pytest.raises(HTTPException) as caught:
        await replica_b.check_auth(REGISTER_PER_IP, "register", "ip", "203.0.113.10")

    assert caught.value.status_code == 429
    assert caught.value.headers is not None
    assert 1 <= int(caught.value.headers["Retry-After"]) <= 60


async def test_redis_keys_carry_the_app_prefix(
    redis_storage: RedisStorage, redis_url: SecretStr
) -> None:
    await AppRateLimiter(redis_storage).check_api(REGISTER_PER_IP, "api", "user", "u-1")

    client = Redis.from_url(redis_url.get_secret_value(), decode_responses=True)
    try:
        keys = [key async for key in client.scan_iter()]
    finally:
        await client.aclose()

    assert keys
    assert all(key.startswith("canal_rate_limit") for key in keys)
