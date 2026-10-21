"""Cliente de Redis y nombres de claves/canales compartidos por el worker y la API.

El worker escribe (3.5) y la API lee (3.9) las mismas claves: los nombres viven aquí para que
los dos usen siempre los mismos.
"""

from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

from app.core.config import Settings

# Prefijo propio: el rate limiting usa `canal_rate_limit` (ADR-0007).
KEY_PREFIX = "canal:"
LIVE_CHANNEL = f"{KEY_PREFIX}vessels.live"
STATUS_KEY = f"{KEY_PREFIX}ais:worker:status"

REDIS_TIMEOUT_SECONDS = 1.0


def create_redis(settings: Settings) -> "Redis":
    """Cliente con timeouts cortos y sin reintentos: un Redis colgado no frena ni
    al worker ni a la API.

    Por defecto `redis-py` espera sin límite y reintenta. La contraseña va en la URL
    (`REDIS_URL`, SecretStr); la librería la muestra como `<REDACTED>` en su `repr`.
    """
    return Redis.from_url(
        settings.redis_url.get_secret_value(),
        socket_timeout=REDIS_TIMEOUT_SECONDS,
        socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
        retry=Retry(NoBackoff(), 0),
        retry_on_timeout=False,
    )
