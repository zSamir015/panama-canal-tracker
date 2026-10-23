"""Writer de buques con destino al Canal (#59, ADR-0009).

Recibe los `ShipStaticData` de la segunda conexión (bbox mundial, unos 16 mensajes por segundo) y
solo escribe los que importan:

- si el destino declarado es el Canal (`app/services/canal_destination.py`), upsert del buque;
- si un buque que ya estaba guardado declara otro destino (o ninguno), se borra;
- el resto, la inmensa mayoría, se descarta sin tocar la base.

Para saber qué buques están guardados sin consultar la base en cada lote, el writer guarda sus
MMSI en memoria (se cargan en el primer lote y se actualizan tras cada commit).

Tiene su propia cola y su propia sesión: si la base va lenta, la ingesta del área del Canal
(`AisWriter`) no espera por esto.
"""

import asyncio
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog
from sqlalchemy.exc import DataError, DBAPIError, IntegrityError

from app.core.db import SessionFactory
from app.repositories.canal_bound import CanalBoundRepository, CanalBoundRow
from app.services.ais_parser import VesselStatic
from app.services.canal_destination import match_canal_destination
from app.workers.ais_writer import MAX_ATTEMPTS, RETRY_MAX_SECONDS
from app.workers.common import AisRecord, backoff_delay, collect_batch

DEFAULT_BATCH_SIZE = 500
# Sin prisa: un destino no cambia de un segundo a otro, y así casi todos los lotes van vacíos.
DEFAULT_FLUSH_SECONDS = 5.0

logger = structlog.get_logger(__name__)


@dataclass
class CanalBoundStats:
    received: int = 0
    upserted: int = 0
    removed: int = 0
    batches: int = 0
    batches_retried: int = 0
    batches_dropped: int = 0
    last_flush_at: datetime | None = None
    last_error: str | None = None
    ports: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CanalBoundBatch:
    upserts: list[CanalBoundRow]
    removals: list[int]


def build_canal_bound_batch(records: Sequence[AisRecord], tracked: set[int]) -> CanalBoundBatch:
    """Qué guardar y qué borrar. Por buque cuenta su último mensaje del lote."""
    latest: dict[int, VesselStatic] = {}
    for record in records:
        if isinstance(record, VesselStatic):
            latest[record.mmsi] = record
    upserts: list[CanalBoundRow] = []
    removals: list[int] = []
    for mmsi in sorted(latest):
        static = latest[mmsi]
        port = match_canal_destination(static.destination)
        if port is not None and static.destination is not None and static.received_at:
            upserts.append(
                CanalBoundRow(
                    mmsi=mmsi,
                    destination=static.destination,
                    port_locode=port,
                    reported_at=static.received_at,
                    name=static.name,
                    imo=static.imo,
                    ship_type=static.ship_type,
                    length_m=static.length_m,
                    eta=static.eta,
                    lat=static.lat,
                    lon=static.lon,
                )
            )
        elif mmsi in tracked:
            removals.append(mmsi)
    return CanalBoundBatch(upserts=upserts, removals=removals)


class CanalBoundWriter:
    def __init__(
        self,
        *,
        queue: asyncio.Queue[AisRecord],
        session_factory: SessionFactory,
        batch_size: int = DEFAULT_BATCH_SIZE,
        flush_seconds: float = DEFAULT_FLUSH_SECONDS,
        max_attempts: int = MAX_ATTEMPTS,
        retry_max_seconds: float = RETRY_MAX_SECONDS,
        retry_base_seconds: float = 1.0,
        rng: random.Random | None = None,
    ) -> None:
        self._queue = queue
        self._session_factory = session_factory
        self._batch_size = batch_size
        self._flush_seconds = flush_seconds
        self._max_attempts = max_attempts
        self._retry_max_seconds = retry_max_seconds
        self._retry_base_seconds = retry_base_seconds
        self._rng = rng or random.Random()  # noqa: S311 (jitter, no criptografía)
        # MMSI guardados en la tabla; None hasta que se cargan (en el primer lote).
        self._tracked: set[int] | None = None
        self.stats = CanalBoundStats()

    async def run(self, stop: asyncio.Event) -> None:
        """Escribe lotes hasta que `stop` se active y la cola quede vacía."""
        while True:
            records = await collect_batch(
                self._queue, stop, batch_size=self._batch_size, flush_seconds=self._flush_seconds
            )
            if records:
                await self.flush(records)
            elif stop.is_set():
                return

    async def flush(self, records: Sequence[AisRecord]) -> None:
        self.stats.received += len(records)
        for attempt in range(self._max_attempts):
            try:
                tracked = await self._load_tracked()
                batch = build_canal_bound_batch(records, tracked)
                if not batch.upserts and not batch.removals:
                    return
                removed = await self._write(batch)
            except (IntegrityError, DataError) as error:
                # El parser y la detección validan antes: si la base lo rechaza, reintentar el
                # mismo lote fallaría siempre.
                self.stats.last_error = type(error).__name__
                logger.warning("ais_canal_bound_batch_rejected", error=type(error).__name__)
                break
            except (DBAPIError, OSError, TimeoutError) as error:
                self.stats.last_error = type(error).__name__
                self.stats.batches_retried += 1
                delay = backoff_delay(
                    attempt,
                    cap=self._retry_max_seconds,
                    rng=self._rng,
                    base=self._retry_base_seconds,
                )
                logger.warning(
                    "ais_canal_bound_batch_retry",
                    attempt=attempt + 1,
                    delay_seconds=round(delay, 3),
                    error=type(error).__name__,
                )
                await asyncio.sleep(delay)
            else:
                self._record_success(batch, tracked, removed)
                return
        self.stats.batches_dropped += 1
        logger.error("ais_canal_bound_batch_dropped", error=self.stats.last_error)

    async def _load_tracked(self) -> set[int]:
        if self._tracked is None:
            async with self._session_factory() as session:
                self._tracked = await CanalBoundRepository(session).tracked_mmsis()
        return self._tracked

    async def _write(self, batch: CanalBoundBatch) -> int:
        async with self._session_factory() as session:
            try:
                repository = CanalBoundRepository(session)
                await repository.upsert(batch.upserts)
                removed = await repository.remove(batch.removals)
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
        return removed

    def _record_success(self, batch: CanalBoundBatch, tracked: set[int], removed: int) -> None:
        # Solo después del commit: si el lote se pierde, la memoria sigue igual que la base.
        tracked.update(row.mmsi for row in batch.upserts)
        tracked.difference_update(batch.removals)
        self.stats.batches += 1
        self.stats.upserted += len(batch.upserts)
        self.stats.removed += removed
        for row in batch.upserts:
            self.stats.ports[row.port_locode] = self.stats.ports.get(row.port_locode, 0) + 1
        self.stats.last_flush_at = datetime.now(UTC)
        # Solo recuentos: destinos y nombres son datos externos (AGENTS.md §8.6).
        logger.info("ais_canal_bound_batch_written", upserted=len(batch.upserts), removed=removed)
