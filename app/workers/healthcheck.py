"""Healthcheck del contenedor del worker: `python -m app.workers.healthcheck`.

El worker no sirve HTTP; su señal de vida es el estado que publica en Redis cada 5 s (3.5). Sale
con 0 si ese estado existe y es reciente, y con 1 si no: Docker marca el contenedor `unhealthy`.
No comprueba la conexión con AISStream: una caída de AISStream es un problema del servicio
externo, no del contenedor, y reiniciarlo no lo arreglaría (el worker ya reintenta solo).
"""

import asyncio
import sys
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.redis import STATUS_KEY, create_redis
from app.schemas.ingestion import WorkerStatus

MAX_AGE = timedelta(seconds=30)


async def check(now: datetime | None = None) -> bool:
    redis = create_redis(get_settings())
    try:
        raw = await redis.get(STATUS_KEY)
    except (RedisError, OSError, TimeoutError):
        return False
    finally:
        await redis.aclose()
    if raw is None:
        return False
    try:
        status = WorkerStatus.model_validate_json(raw)
    except ValidationError:
        return False
    return (now or datetime.now(UTC)) - status.updated_at <= MAX_AGE


def main() -> int:
    return 0 if asyncio.run(check()) else 1


if __name__ == "__main__":
    sys.exit(main())
