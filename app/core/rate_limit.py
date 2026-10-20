"""Rate limiting asíncrono compartido entre réplicas mediante Redis."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Annotated, Any, cast
from uuid import uuid4

import redis.asyncio as redis
from fastapi import Depends, HTTPException, Request
from limits import RateLimitItem
from limits import parse as parse_limit

WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')[2]
  return {0, math.max(1, math.ceil((oldest + window - now) / 1000))}
end
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, math.ceil(window / 1000))
return {1, 0}
"""


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    retry_after: int


def limit(text: str) -> RateLimitItem:
    """Parsea un límite con la sintaxis pública de `limits`."""
    return parse_limit(text)


class RedisRateLimiter:
    def __init__(self, client: redis.Redis, *, prefix: str = "canal:rate") -> None:
        self._client = client
        self._prefix = prefix

    async def hit(self, item: RateLimitItem, scope: str, *identifiers: str) -> RateLimitResult:
        digest = hashlib.sha256("\x1f".join(identifiers).encode()).hexdigest()
        key = f"{self._prefix}:{scope}:{digest}"
        now = int(time.time() * 1000)
        window = item.get_expiry() * 1000
        try:
            result = await cast(
                Awaitable[Any],
                self._client.eval(
                    WINDOW_SCRIPT,
                    1,
                    key,
                    str(now),
                    str(window),
                    str(item.amount),
                    uuid4().hex,
                ),
            )
        except redis.RedisError as error:
            raise RateLimitUnavailableError from error
        allowed, retry_after = cast(tuple[int, int], result)
        return RateLimitResult(bool(allowed), int(retry_after))


class RateLimitUnavailableError(Exception):
    """Redis no está disponible y no se puede aplicar el límite de forma segura."""


def get_rate_limiter(request: Request) -> RedisRateLimiter:
    return cast(RedisRateLimiter, request.app.state.rate_limiter)


def enforce(result: RateLimitResult) -> None:
    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail="Demasiadas peticiones",
            headers={"Retry-After": str(result.retry_after)},
        )


def client_identifier(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def enforce_request_limit(
    request: Request,
    limiter: RedisRateLimiter,
    item: RateLimitItem,
    scope: str,
    *identifiers: str,
) -> None:
    try:
        result = await limiter.hit(item, scope, *identifiers)
    except RateLimitUnavailableError:
        raise HTTPException(
            status_code=503, detail="Servicio de limitación no disponible"
        ) from None
    enforce(result)


async def enforce_register(
    request: Request,
    limiter: Annotated[RedisRateLimiter, Depends(get_rate_limiter)],
) -> None:
    await enforce_request_limit(
        request, limiter, limit("3/minute"), "register", client_identifier(request)
    )


async def enforce_login(
    request: Request,
    limiter: Annotated[RedisRateLimiter, Depends(get_rate_limiter)],
) -> None:
    body = await request.json()
    email = str(body.get("email", "")).strip().lower()
    await enforce_request_limit(
        request, limiter, limit("5/minute"), "login-ip", client_identifier(request)
    )
    await enforce_request_limit(request, limiter, limit("5/minute"), "login-email", email)


async def enforce_refresh(
    request: Request,
    limiter: Annotated[RedisRateLimiter, Depends(get_rate_limiter)],
) -> None:
    await enforce_request_limit(
        request, limiter, limit("10/minute"), "refresh", client_identifier(request)
    )


async def enforce_api_limit(
    request: Request,
    user_id: str,
    limiter: Annotated[RedisRateLimiter, Depends(get_rate_limiter)],
) -> None:
    await enforce_request_limit(request, limiter, limit("120/minute"), "api", user_id)
