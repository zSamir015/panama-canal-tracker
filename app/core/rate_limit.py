"""Rate limiting con el contador en Redis, compartido entre réplicas (ADR-0007, AGENTS.md §8.8).

- Auth (login, register, refresh): ventana deslizante exacta (moving window). Si Redis no
  responde, **falla cerrado** con 503: sin límite, la fuerza bruta contra el login no tendría freno.
- API general: sliding window counter (más barata). Si Redis no responde, **falla abierto**: una
  caída de Redis no debe tirar el mapa entero. Queda en el log como `rate_limit_unavailable`.

Las claves nunca llevan contraseñas, tokens ni emails en claro (el email va como SHA-256).
"""

import hashlib
import math
import time
from http import HTTPStatus
from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, Request
from limits import RateLimitItem, parse
from limits.aio.storage import RedisStorage, Storage
from limits.aio.strategies import (
    MovingWindowRateLimiter,
    RateLimiter,
    SlidingWindowCounterRateLimiter,
)
from limits.errors import StorageError

from app.core.auth import CurrentUser
from app.core.config import Settings

LOGIN_PER_IP = parse("5/minute")
LOGIN_PER_EMAIL = parse("5/minute")
REGISTER_PER_IP = parse("3/minute")
REFRESH_PER_IP = parse("10/minute")
API_PER_USER = parse("120/minute")

TOO_MANY_REQUESTS_DETAIL = "Demasiadas peticiones; vuelve a intentarlo más tarde"
UNAVAILABLE_DETAIL = "Servicio no disponible temporalmente"
UNAVAILABLE_RETRY_AFTER_SECONDS = 30
# Un Redis colgado no puede dejar las peticiones esperando: se rinde rápido y aplica la política.
REDIS_TIMEOUT_SECONDS = 1.0
KEY_PREFIX = "canal_rate_limit"

logger = structlog.get_logger(__name__)


def create_storage(settings: Settings) -> RedisStorage:
    """Almacenamiento en Redis. No abre la conexión hasta la primera consulta."""
    return RedisStorage(
        f"async+{settings.redis_url.get_secret_value()}",
        implementation="redispy",
        # Cualquier fallo de Redis llega como `StorageError`.
        wrap_exceptions=True,
        key_prefix=KEY_PREFIX,
        socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
        socket_timeout=REDIS_TIMEOUT_SECONDS,
    )


class AppRateLimiter:
    def __init__(self, storage: Storage) -> None:
        self._auth = MovingWindowRateLimiter(storage)
        self._api = SlidingWindowCounterRateLimiter(storage)

    async def check_auth(self, limit: RateLimitItem, *key: str) -> None:
        await self._check(self._auth, limit, key, fail_open=False)

    async def check_api(self, limit: RateLimitItem, *key: str) -> None:
        await self._check(self._api, limit, key, fail_open=True)

    @staticmethod
    async def _check(
        strategy: RateLimiter, limit: RateLimitItem, key: tuple[str, ...], *, fail_open: bool
    ) -> None:
        try:
            if await strategy.hit(limit, *key):
                return
            stats = await strategy.get_window_stats(limit, *key)
        except StorageError as error:
            # Solo el ámbito (`login`, `api`...): el resto de la clave puede ser una IP o un id.
            logger.error(
                "rate_limit_unavailable",
                scope=key[0],
                fail_open=fail_open,
                error=type(error.storage_error).__name__,
            )
            if fail_open:
                return
            raise HTTPException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                detail=UNAVAILABLE_DETAIL,
                headers={"Retry-After": str(UNAVAILABLE_RETRY_AFTER_SECONDS)},
            ) from None

        retry_after = max(1, math.ceil(stats.reset_time - time.time()))
        logger.warning("rate_limit_exceeded", scope=key[0], retry_after=retry_after)
        raise HTTPException(
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            detail=TOO_MANY_REQUESTS_DETAIL,
            headers={"Retry-After": str(retry_after)},
        )


def get_rate_limiter(request: Request) -> AppRateLimiter:
    limiter: AppRateLimiter = request.app.state.rate_limiter
    return limiter


Limiter = Annotated[AppRateLimiter, Depends(get_rate_limiter)]


def client_ip(request: Request) -> str:
    """IP del cliente según el servidor ASGI.

    Detrás del reverse proxy, uvicorn la toma de `X-Forwarded-For` solo si la conexión viene de
    `--forwarded-allow-ips`. Leer esa cabecera aquí permitiría a cualquiera elegir su IP.
    """
    return request.client.host if request.client else "unknown"


def email_key(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()


async def limit_login_by_ip(request: Request, limiter: Limiter) -> None:
    await limiter.check_auth(LOGIN_PER_IP, "login", "ip", client_ip(request))


async def limit_register_by_ip(request: Request, limiter: Limiter) -> None:
    await limiter.check_auth(REGISTER_PER_IP, "register", "ip", client_ip(request))


async def limit_refresh_by_ip(request: Request, limiter: Limiter) -> None:
    await limiter.check_auth(REFRESH_PER_IP, "refresh", "ip", client_ip(request))


async def limit_api_by_user(user: CurrentUser, limiter: Limiter) -> None:
    await limiter.check_api(API_PER_USER, "api", "user", str(user.id))
