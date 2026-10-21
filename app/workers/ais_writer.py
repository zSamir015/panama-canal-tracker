"""Writer del worker AIS: guarda en la base, por lotes, lo que deja el consumer en la cola (3.4).

Cada lote es una transacción:

1. **upsert de `vessels`**: todos los buques del lote, antes que sus posiciones (la FK de
   `positions.vessel_mmsi` lo exige); los datos estáticos (`ShipStaticData`) se mezclan aquí;
2. **insert de `positions`** en una sola sentencia; un mensaje repetido se ignora.

Si algo falla, rollback: o se guarda el lote entero o nada. Después, según el error:

- **un dato que la base rechaza** (CHECK, tipo...): se reintenta fila a fila, cada una en su
  savepoint, y solo se descartan las malas. Un mensaje raro no tira las otras 499 posiciones;
- **la base no responde**: se reintenta el mismo lote con backoff y, si sigue sin responder, se
  descarta y se cuenta. Mientras, el consumer sigue leyendo (la cola descarta lo más antiguo).

Nunca se registran los datos del lote: solo contadores y el tipo de error.
"""

import asyncio
import random
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial

import structlog
from sqlalchemy.exc import DataError, DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionFactory
from app.repositories.ais import AisRepository, PositionRow, VesselRow
from app.services.ais_parser import PositionUpdate, VesselStatic
from app.workers.common import AisRecord, backoff_delay

DEFAULT_BATCH_SIZE = 500
DEFAULT_FLUSH_SECONDS = 2.0
MAX_ATTEMPTS = 5
# Con 5 intentos y un techo de 10 s, un lote con la base caída se abandona en unos 20 s.
RETRY_MAX_SECONDS = 10.0

logger = structlog.get_logger(__name__)


@dataclass
class WriterStats:
    batches: int = 0
    positions_written: int = 0
    positions_duplicated: int = 0
    vessels_upserted: int = 0
    rows_rejected_by_db: int = 0
    batches_retried: int = 0
    batches_dropped: int = 0
    records_dropped: int = 0
    last_flush_at: datetime | None = None
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class Batch:
    vessels: list[VesselRow]
    positions: list[PositionRow]
    size: int  # registros recibidos de la cola (antes de quitar duplicados)


def build_batch(records: Sequence[AisRecord]) -> Batch:
    """Prepara un lote: un buque por MMSI y sin posiciones repetidas dentro del lote.

    El último dato estático de cada buque gana; `last_seen_at` es su última posición.
    """
    positions: dict[tuple[datetime, int], PositionRow] = {}
    last_seen: dict[int, datetime] = {}
    statics: dict[int, VesselStatic] = {}
    for record in records:
        if isinstance(record, PositionUpdate):
            positions[(record.received_at, record.mmsi)] = PositionRow(
                received_at=record.received_at,
                mmsi=record.mmsi,
                lat=record.lat,
                lon=record.lon,
                sog=record.sog,
                cog=record.cog,
                heading=record.heading,
                nav_status=record.nav_status,
            )
            previous = last_seen.get(record.mmsi)
            if previous is None or record.received_at > previous:
                last_seen[record.mmsi] = record.received_at
        else:
            statics[record.mmsi] = record
    vessels = []
    for mmsi in sorted(last_seen.keys() | statics.keys()):
        static = statics.get(mmsi)
        vessels.append(
            VesselRow(
                mmsi=mmsi,
                last_seen_at=last_seen.get(mmsi),
                name=static.name if static else None,
                imo=static.imo if static else None,
                ship_type=static.ship_type if static else None,
                length_m=static.length_m if static else None,
                beam_m=static.beam_m if static else None,
            )
        )
    return Batch(vessels=vessels, positions=list(positions.values()), size=len(records))


class AisWriter:
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
        self.stats = WriterStats()

    async def run(self, stop: asyncio.Event) -> None:
        """Escribe lotes hasta que `stop` se active y la cola quede vacía."""
        while True:
            records = await self._collect(stop)
            if records:
                await self.flush(records)
            elif stop.is_set():
                return

    async def _collect(self, stop: asyncio.Event) -> list[AisRecord]:
        """Junta registros hasta llenar el lote o agotar el plazo desde el primero.

        Con `stop` activo no espera: recoge lo que quede en la cola para vaciarla antes de salir.
        """
        loop = asyncio.get_running_loop()
        records: list[AisRecord] = []
        deadline: float | None = None
        while len(records) < self._batch_size:
            if stop.is_set():
                try:
                    records.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
                self._queue.task_done()
                continue
            timeout = self._flush_seconds if deadline is None else deadline - loop.time()
            if timeout <= 0:
                break
            record = await self._next(stop, timeout)
            if record is None:
                if stop.is_set():
                    continue  # vaciar la cola sin esperar (rama de arriba)
                break  # plazo agotado
            records.append(record)
            if deadline is None:
                deadline = loop.time() + self._flush_seconds
        return records

    async def _next(self, stop: asyncio.Event, wait_seconds: float) -> AisRecord | None:
        """El siguiente registro, o None si vence el plazo o se activa `stop` antes."""
        getter = asyncio.ensure_future(self._queue.get())
        stopper = asyncio.ensure_future(stop.wait())
        try:
            await asyncio.wait(
                {getter, stopper}, timeout=wait_seconds, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            stopper.cancel()
            getter.cancel()
        # `get` pudo terminar justo a la vez que `stop`: ese registro no se puede perder.
        if getter.done() and not getter.cancelled():
            self._queue.task_done()
            return getter.result()
        return None

    async def flush(self, records: Sequence[AisRecord]) -> None:
        batch = build_batch(records)
        row_by_row = False
        for attempt in range(self._max_attempts):
            try:
                if row_by_row:
                    await self._write_row_by_row(batch)
                else:
                    await self._write(batch)
                return
            except (IntegrityError, DataError) as error:
                # Un dato que la base no acepta: reintentar el lote igual fallaría siempre.
                # Se pasa a fila a fila (que también puede encontrarse la base caída y reintentar).
                self.stats.last_error = type(error).__name__
                logger.warning("ais_batch_rejected", size=batch.size, error=type(error).__name__)
                if row_by_row:
                    break
                row_by_row = True
            except (DBAPIError, OSError, TimeoutError) as error:
                # Base caída o conexión perdida: el mismo lote puede salir bien más tarde.
                self.stats.last_error = type(error).__name__
                self.stats.batches_retried += 1
                delay = backoff_delay(
                    attempt,
                    cap=self._retry_max_seconds,
                    rng=self._rng,
                    base=self._retry_base_seconds,
                )
                logger.warning(
                    "ais_batch_retry",
                    attempt=attempt + 1,
                    delay_seconds=round(delay, 3),
                    error=type(error).__name__,
                )
                await asyncio.sleep(delay)
        self.stats.batches_dropped += 1
        self.stats.records_dropped += batch.size
        logger.error("ais_batch_dropped", size=batch.size, error=self.stats.last_error)

    async def _write(self, batch: Batch) -> None:
        async with self._session_factory() as session:
            try:
                repository = AisRepository(session)
                await repository.upsert_vessels(batch.vessels)
                written = await repository.insert_positions(batch.positions)
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
        self._record_success(
            vessels=len(batch.vessels),
            written=written,
            duplicated=len(batch.positions) - written,
        )

    async def _write_row_by_row(self, batch: Batch) -> None:
        """Cada buque y cada posición en su propio savepoint: solo se pierden los que fallan."""
        written = 0
        accepted_positions = 0
        rejected = 0
        upserted: set[int] = set()
        async with self._session_factory() as session:
            try:
                repository = AisRepository(session)
                for vessel in batch.vessels:
                    done = await _in_savepoint(
                        session, partial(repository.upsert_vessels, [vessel])
                    )
                    if isinstance(done, _Rejected):
                        rejected += 1
                    else:
                        upserted.add(vessel.mmsi)
                for position in batch.positions:
                    if position.mmsi not in upserted:
                        rejected += 1  # sin su buque, la FK la rechazaría
                        continue
                    inserted = await _in_savepoint(
                        session, partial(repository.insert_positions, [position])
                    )
                    if isinstance(inserted, _Rejected):
                        rejected += 1
                    else:
                        accepted_positions += 1
                        written += inserted
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
        self.stats.rows_rejected_by_db += rejected
        logger.warning("ais_rows_rejected_by_db", rejected=rejected, size=batch.size)
        self._record_success(
            vessels=len(upserted), written=written, duplicated=accepted_positions - written
        )

    def _record_success(self, *, vessels: int, written: int, duplicated: int) -> None:
        self.stats.batches += 1
        self.stats.positions_written += written
        self.stats.positions_duplicated += duplicated
        self.stats.vessels_upserted += vessels
        self.stats.last_flush_at = datetime.now(UTC)
        logger.debug("ais_batch_written", positions=written, vessels=vessels, duplicated=duplicated)


class _Rejected:
    """Marca de una operación que la base rechazó dentro de su savepoint."""


_REJECTED = _Rejected()


async def _in_savepoint[T](
    session: AsyncSession, operation: Callable[[], Awaitable[T]]
) -> T | _Rejected:
    savepoint = await session.begin_nested()
    try:
        result = await operation()
    except (IntegrityError, DataError):
        await savepoint.rollback()
        return _REJECTED
    await savepoint.commit()
    return result
