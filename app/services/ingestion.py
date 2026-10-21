"""Estado de la ingesta AIS para `/admin/ingestion/status` (tarea 3.9).

Lee lo que el worker deja en Redis (3.5). Si la clave no existe, el worker está parado o lleva
más de su caducidad sin actualizar: "sin datos", no un error.
"""

from datetime import UTC, datetime, timedelta

import structlog
from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.redis import STATUS_KEY
from app.schemas.ingestion import IngestionStatusResponse, WorkerStatus
from app.services.exceptions import IngestionStatusUnavailableError

# El worker actualiza cada 5 s: un estado de más de 30 s es sospechoso aunque exista.
STALE_AFTER = timedelta(seconds=30)

logger = structlog.get_logger(__name__)


class IngestionService:
    def __init__(self, redis: "Redis") -> None:
        self._redis = redis

    async def status(self, now: datetime | None = None) -> IngestionStatusResponse:
        try:
            raw = await self._redis.get(STATUS_KEY)
        except (RedisError, OSError, TimeoutError) as error:
            logger.warning("ingestion_status_unavailable", error=type(error).__name__)
            raise IngestionStatusUnavailableError from None
        if raw is None:
            return IngestionStatusResponse(available=False)
        try:
            status = WorkerStatus.model_validate_json(raw)
        except ValidationError:
            # Lo escribe nuestro worker, pero Redis es otro sistema: no se devuelve a ciegas.
            logger.error("ingestion_status_invalid")
            return IngestionStatusResponse(available=False)
        age = max(timedelta(0), (now or datetime.now(UTC)) - status.updated_at)
        return IngestionStatusResponse(
            available=True,
            stale=age > STALE_AFTER,
            age_seconds=round(age.total_seconds(), 1),
            status=status,
        )
