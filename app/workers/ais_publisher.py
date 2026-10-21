"""Publicación en Redis: posiciones en vivo y estado del worker AIS (tarea 3.5, ADR-0004).

- **Posiciones**: tras cada lote guardado (nunca antes del commit), un `PUBLISH` en
  `canal:vessels.live` con la última posición de cada buque del lote, en el formato que la API
  reenviará por `/ws/live` (docs/API_DESIGN.md). La base de datos es la fuente de verdad; el mapa
  en vivo es "lo mejor posible".
- **Estado**: `canal:ais:worker:status` con contadores del consumer y del writer y `updated_at`,
  con caducidad: si el worker muere, la clave desaparece sola y `/admin/ingestion/status` (3.9)
  puede decir "sin datos" en vez de enseñar un estado viejo como si fuera actual.

Redis caído no frena nada: timeout de 1 s, sin reintentos de la librería y, tras un fallo, no se
vuelve a intentar durante unos segundos (un Redis colgado no puede añadir 1 s a cada lote). Los
fallos se cuentan; nunca se propagan al writer ni al consumer.
"""

import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

import structlog
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError

from app.core.config import Settings
from app.repositories.ais import PositionRow
from app.workers.ais_writer import Batch, WriterStats

if TYPE_CHECKING:
    from app.workers.ais_consumer import ConsumerStats

KEY_PREFIX = "canal:"
LIVE_CHANNEL = f"{KEY_PREFIX}vessels.live"
STATUS_KEY = f"{KEY_PREFIX}ais:worker:status"

REDIS_TIMEOUT_SECONDS = 1.0
# Tras un fallo, cuánto tiempo se deja de intentar publicar.
COOLDOWN_SECONDS = 5.0
STATUS_INTERVAL_SECONDS = 5.0
# Si el worker deja de actualizar el estado durante 3 intervalos, la clave caduca.
STATUS_TTL_SECONDS = 15
# Buques por mensaje: mantiene cada PUBLISH muy por debajo de los límites razonables de Redis.
MAX_VESSELS_PER_MESSAGE = 200
# Nombres y tipos de los buques vistos (de los ShipStaticData) para completar las posiciones.
MAX_KNOWN_VESSELS = 5_000

logger = structlog.get_logger(__name__)


class LiveVessel(BaseModel):
    """Una posición tal como la recibirá el navegador (docs/API_DESIGN.md, `/ws/live`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mmsi: int = Field(ge=100_000_000, le=999_999_999)
    lon: float = Field(ge=-180, le=180, allow_inf_nan=False)
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    cog: float | None = Field(ge=0, lt=360)
    sog: float | None = Field(ge=0, lt=102.3)
    ship_type: int | None = Field(ge=1, le=99)
    # Texto del buque tal cual (puede traer "<img ...>"): el navegador lo muestra como texto.
    name: str | None = Field(max_length=128)
    ts: AwareDatetime


class LiveUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["update"] = "update"
    vessels: list[LiveVessel] = Field(max_length=MAX_VESSELS_PER_MESSAGE)


class WorkerStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    updated_at: AwareDatetime
    connected: bool
    subscribed: bool
    connections: int
    last_message_at: AwareDatetime | None
    last_error: str | None
    received: int
    queued: int
    queue_size: int
    dropped: int
    ignored: int
    rejected: dict[str, int]
    batches: int
    positions_written: int
    positions_duplicated: int
    rows_rejected_by_db: int
    batches_dropped: int
    last_flush_at: AwareDatetime | None


@dataclass
class PublisherStats:
    messages_published: int = 0
    vessels_published: int = 0
    status_updates: int = 0
    failures: int = 0
    skipped: int = 0
    invalid: int = 0


def create_redis(settings: Settings) -> "Redis":
    """Cliente con timeouts cortos y sin reintentos: un Redis colgado no frena al worker.

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


def _chunks[T](items: Sequence[T], size: int) -> list[Sequence[T]]:
    return [items[start : start + size] for start in range(0, len(items), size)]


class AisPublisher:
    def __init__(
        self,
        redis: "Redis",
        *,
        cooldown_seconds: float = COOLDOWN_SECONDS,
        status_ttl_seconds: int = STATUS_TTL_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._redis = redis
        self._cooldown_seconds = cooldown_seconds
        self._status_ttl_seconds = status_ttl_seconds
        self._monotonic = monotonic
        self._paused_until = 0.0
        self._known: OrderedDict[int, tuple[str | None, int | None]] = OrderedDict()
        self.stats = PublisherStats()

    def __repr__(self) -> str:
        return "AisPublisher()"  # el cliente lleva la URL con la contraseña

    def _remember(self, batch: Batch) -> None:
        for vessel in batch.vessels:
            if vessel.name is None and vessel.ship_type is None:
                continue
            previous_name, previous_type = self._known.get(vessel.mmsi, (None, None))
            self._known[vessel.mmsi] = (
                vessel.name or previous_name,
                vessel.ship_type or previous_type,
            )
            self._known.move_to_end(vessel.mmsi)
        while len(self._known) > MAX_KNOWN_VESSELS:
            self._known.popitem(last=False)

    def live_vessels(self, batch: Batch) -> list[LiveVessel]:
        """La última posición de cada buque del lote, con su nombre y tipo si se conocen."""
        self._remember(batch)
        latest: dict[int, PositionRow] = {}
        for position in batch.positions:
            current = latest.get(position.mmsi)
            if current is None or position.received_at > current.received_at:
                latest[position.mmsi] = position
        vessels = []
        for mmsi in sorted(latest):
            position = latest[mmsi]
            name, ship_type = self._known.get(mmsi, (None, None))
            try:
                vessels.append(
                    LiveVessel(
                        mmsi=mmsi,
                        lon=position.lon,
                        lat=position.lat,
                        cog=position.cog,
                        sog=position.sog,
                        ship_type=ship_type,
                        name=name,
                        ts=position.received_at,
                    )
                )
            except ValidationError:
                # No debería pasar (el parser y la base ya validaron), pero el formato que llega
                # al navegador no se negocia: ese buque no se publica.
                self.stats.invalid += 1
        return vessels

    async def publish_batch(self, batch: Batch) -> None:
        """Publica un lote ya guardado. Nunca lanza: un fallo se cuenta y se sigue."""
        vessels = self.live_vessels(batch)
        if not vessels:
            return
        for chunk in _chunks(vessels, MAX_VESSELS_PER_MESSAGE):
            payload = LiveUpdate(vessels=list(chunk)).model_dump_json().encode()
            if not await self._call("publish", self._redis.publish, LIVE_CHANNEL, payload):
                return
            self.stats.messages_published += 1
            self.stats.vessels_published += len(chunk)

    async def publish_status(self, status: WorkerStatus) -> None:
        payload = status.model_dump_json().encode()
        if await self._call(
            "status", self._redis.set, STATUS_KEY, payload, ex=self._status_ttl_seconds
        ):
            self.stats.status_updates += 1

    async def _call(self, operation: str, method: Any, *args: Any, **kwargs: Any) -> bool:
        if self._monotonic() < self._paused_until:
            self.stats.skipped += 1
            return False
        try:
            await method(*args, **kwargs)
        except (RedisError, OSError, TimeoutError) as error:
            self.stats.failures += 1
            self._paused_until = self._monotonic() + self._cooldown_seconds
            # Solo el tipo: el texto de algunos errores de conexión incluye host y puerto.
            logger.warning(
                "redis_publish_failed",
                operation=operation,
                error=type(error).__name__,
                failures=self.stats.failures,
            )
            return False
        return True

    async def close(self) -> None:
        await self._redis.aclose()


def worker_status(
    *,
    consumer: "ConsumerStats",
    writer: WriterStats,
    queue_size: int,
    now: datetime | None = None,
) -> WorkerStatus:
    return WorkerStatus(
        updated_at=now or datetime.now(UTC),
        connected=consumer.connected,
        subscribed=consumer.subscribed,
        connections=consumer.connections,
        last_message_at=consumer.last_message_at,
        last_error=consumer.last_error,
        received=consumer.received,
        queued=consumer.queued,
        queue_size=queue_size,
        dropped=consumer.dropped,
        ignored=consumer.ignored,
        rejected=dict(consumer.rejected),
        batches=writer.batches,
        positions_written=writer.positions_written,
        positions_duplicated=writer.positions_duplicated,
        rows_rejected_by_db=writer.rows_rejected_by_db,
        batches_dropped=writer.batches_dropped,
        last_flush_at=writer.last_flush_at,
    )
