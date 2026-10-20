from typing import Any

import pytest
import redis
from fastapi import HTTPException

from app.core.rate_limit import (
    RateLimitUnavailableError,
    RedisRateLimiter,
    enforce,
    limit,
)


class FakeRedis:
    def __init__(self, result: list[int] | Exception) -> None:
        self.result = result
        self.arguments: tuple[Any, ...] = ()

    async def eval(self, *arguments: Any) -> list[int]:
        self.arguments = arguments
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


async def test_rate_limiter_hashes_identifiers_and_returns_result() -> None:
    client = FakeRedis([1, 0])
    limiter = RedisRateLimiter(client)

    result = await limiter.hit(limit("5/minute"), "login-email", "ana@example.com")

    assert result.allowed
    assert "ana@example.com" not in str(client.arguments)
    assert "password" not in str(client.arguments)
    assert client.arguments[2].startswith("canal:rate:login-email:")


async def test_rate_limiter_maps_redis_failure() -> None:
    limiter = RedisRateLimiter(FakeRedis(redis.RedisError("offline")))

    with pytest.raises(RateLimitUnavailableError):
        await limiter.hit(limit("5/minute"), "login-ip", "127.0.0.1")


def test_exceeded_limit_has_retry_after_header() -> None:
    with pytest.raises(HTTPException) as raised:
        enforce(type("Result", (), {"allowed": False, "retry_after": 12})())

    assert raised.value.status_code == 429
    assert raised.value.headers == {"Retry-After": "12"}
