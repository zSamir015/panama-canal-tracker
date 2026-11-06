"""Métricas para Prometheus y comprobación de disponibilidad (tarea 7.1, ADR-0014).

Dos piezas:

- `render` escribe el formato de exposición de texto de Prometheus (versión 0.0.4) a mano: unas
  pocas métricas con nombres y etiquetas fijos, sin una librería nueva que auditar (AGENTS.md
  §8.14). Nunca lleva texto de AIS ni datos de usuario: solo números.
- `MetricsService` reúne las cifras. Las del worker AIS salen del estado que publica en Redis
  (3.5) y las de tránsitos y fondeo, de la base. Si una dependencia no responde, sus métricas se
  omiten y `canal_dependency_up` lo dice: un scrape nunca falla por eso.

Los contadores `*_total` son los del worker y se reinician cuando este arranca; Prometheus lo
trata como un reinicio de contador (`rate`/`increase` lo compensan).
"""

import asyncio
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionFactory
from app.repositories.anchorages import AnchorageRepository
from app.repositories.transits import TransitRepository
from app.schemas.ingestion import IngestionStatusResponse
from app.services.exceptions import IngestionStatusUnavailableError
from app.services.ingestion import IngestionService

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
CHECK_TIMEOUT_SECONDS = 2.0

logger = structlog.get_logger(__name__)

MetricType = Literal["gauge", "counter"]


@dataclass(frozen=True, slots=True)
class Sample:
    value: float
    labels: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class Metric:
    name: str
    help: str
    type: MetricType
    samples: tuple[Sample, ...]


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def _labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    # Los nombres y valores de las etiquetas son constantes nuestras (ver `MetricsService`); aun
    # así se escapan como pide el formato, por si algún día dejan de serlo.
    pairs = ",".join(
        f'{name}="{value.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'
        for name, value in labels
    )
    return "{" + pairs + "}"


def render(metrics: Sequence[Metric]) -> str:
    """El texto de `/metrics`: `# HELP`, `# TYPE` y una línea por muestra."""
    lines: list[str] = []
    for metric in metrics:
        lines.append(f"# HELP {metric.name} {metric.help}")
        lines.append(f"# TYPE {metric.name} {metric.type}")
        lines.extend(
            f"{metric.name}{_labels(sample.labels)} {_number(sample.value)}"
            for sample in metric.samples
        )
    return "\n".join(lines) + "\n"


def gauge(name: str, help_text: str, value: float) -> Metric:
    return Metric(name, help_text, "gauge", (Sample(value),))


def counter(name: str, help_text: str, value: float) -> Metric:
    return Metric(name, help_text, "counter", (Sample(value),))


@dataclass(frozen=True, slots=True)
class Readiness:
    database: bool
    redis: bool

    @property
    def ready(self) -> bool:
        return self.database and self.redis


async def check_database(session_factory: SessionFactory) -> bool:
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS), session_factory() as session:
            await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError, TimeoutError) as error:
        logger.warning("ready_database_failed", error=type(error).__name__)
        return False
    return True


async def check_redis(redis: "Redis") -> bool:
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
            # Los stubs de redis-py tipan `ping` como `Awaitable[bool] | bool` (sync o async).
            await cast("Awaitable[bool]", redis.ping())
    except (RedisError, OSError, TimeoutError) as error:
        logger.warning("ready_redis_failed", error=type(error).__name__)
        return False
    return True


async def readiness(session_factory: SessionFactory, redis: "Redis") -> Readiness:
    database, redis_ok = await asyncio.gather(check_database(session_factory), check_redis(redis))
    return Readiness(database=database, redis=redis_ok)


def worker_metrics(status: IngestionStatusResponse, now: datetime) -> list[Metric]:
    """Las métricas del worker AIS a partir del estado que publica en Redis."""
    available = status.available and not status.stale
    metrics = [
        gauge(
            "canal_ais_worker_available",
            "1 si el worker AIS publicó su estado hace menos de 30 s, 0 si no.",
            1 if available else 0,
        )
    ]
    data = status.status
    if data is None:
        return metrics
    metrics.extend(
        [
            gauge(
                "canal_ais_worker_connected",
                "1 si el worker tiene la conexión abierta con AISStream.",
                1 if data.connected else 0,
            ),
            gauge(
                "canal_ais_queue_size",
                "Mensajes en la cola entre el WebSocket y el writer.",
                data.queue_size,
            ),
            counter(
                "canal_ais_messages_received_total",
                "Mensajes recibidos de AISStream desde que arrancó el worker.",
                data.received,
            ),
            counter(
                "canal_ais_messages_dropped_total",
                "Mensajes descartados por cola llena desde que arrancó el worker.",
                data.dropped,
            ),
            counter(
                "canal_ais_positions_written_total",
                "Posiciones guardadas en la base desde que arrancó el worker.",
                data.positions_written,
            ),
            counter(
                "canal_ais_batches_dropped_total",
                "Lotes abandonados por fallo de la base desde que arrancó el worker.",
                data.batches_dropped,
            ),
        ]
    )
    if data.last_message_at is not None:
        age = max(0.0, (now - data.last_message_at).total_seconds())
        metrics.append(
            gauge(
                "canal_ais_last_message_age_seconds",
                "Segundos desde el último mensaje de AISStream que recibió el worker.",
                round(age, 1),
            )
        )
    return metrics


class MetricsService:
    def __init__(self, session_factory: SessionFactory, redis: "Redis") -> None:
        self._session_factory = session_factory
        self._redis = redis

    async def collect(self, now: datetime | None = None) -> list[Metric]:
        now = now or datetime.now(UTC)
        metrics: list[Metric] = [gauge("canal_up", "La API responde.", 1)]
        status = await self._worker_status()
        counts = await self._counts()
        metrics.append(
            Metric(
                "canal_dependency_up",
                "1 si la dependencia respondió durante este scrape.",
                "gauge",
                (
                    Sample(1 if counts is not None else 0, (("name", "database"),)),
                    Sample(1 if status is not None else 0, (("name", "redis"),)),
                ),
            )
        )
        if status is not None:
            metrics.extend(worker_metrics(status, now))
        if counts is not None:
            metrics.extend(
                [
                    gauge(
                        "canal_transits_in_progress",
                        "Tránsitos del Canal en curso.",
                        counts[0],
                    ),
                    gauge(
                        "canal_anchorage_visits_open",
                        "Buques esperando ahora en un fondeadero.",
                        counts[1],
                    ),
                ]
            )
        return metrics

    async def _worker_status(self) -> IngestionStatusResponse | None:
        try:
            return await IngestionService(self._redis).status()
        except IngestionStatusUnavailableError:
            return None

    async def _counts(self) -> tuple[int, int] | None:
        try:
            async with asyncio.timeout(CHECK_TIMEOUT_SECONDS), self._session_factory() as session:
                return await _count(session)
        except (SQLAlchemyError, OSError, TimeoutError) as error:
            logger.warning("metrics_database_failed", error=type(error).__name__)
            return None


async def _count(session: AsyncSession) -> tuple[int, int]:
    return (
        await TransitRepository(session).count_in_progress(),
        await AnchorageRepository(session).count_open(),
    )
