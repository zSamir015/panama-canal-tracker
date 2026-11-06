"""Detección de tránsitos dentro del worker AIS (tarea 5.3).

Une el detector puro (`app/services/transit_detector.py`, 5.2) con la base de datos:

1. **Tras cada lote guardado** (el mismo aviso que usa el publisher), pasa las posiciones del lote
   por el detector, en orden cronológico, y guarda en `transits` los eventos que salen: abrir un
   tránsito `in_progress`, o cerrarlo como `completed` o `aborted`.
2. **Cada minuto** llama a `expire` con la hora actual: un buque que deja de emitir no manda
   ninguna posición que dispare el timeout, así que alguien con reloj tiene que comprobarlo.
3. **Al arrancar** reconstruye el estado desde la base: los tránsitos abiertos (y si el buque ya
   había salido de la zona de origen, mirando sus posiciones) y los buques que acaban de cerrar
   uno y siguen dentro de la zona donde lo cerraron. Sin esto, cada reinicio del worker perdería
   los tránsitos en curso o abriría tránsitos falsos con los buques parados en una entrada.

El estado vive en memoria; la base es la fuente de verdad. Si la base no responde al guardar, se
reintenta unas veces y, si sigue sin responder, se descartan esos eventos y se cuentan. Un cierre
cuyo tránsito no llegó a abrirse en la base se guarda ya cerrado
(`TransitRepository.close_transit`).

Mientras no termine la reconstrucción del estado, los lotes no pasan por el detector (se cuentan
en `batches_skipped`): procesarlos con un estado vacío abriría tránsitos duplicados.
"""

import asyncio
import contextlib
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.exc import DataError, DBAPIError, IntegrityError

from app.core.db import SessionFactory
from app.repositories.transits import ClosedTransitRow, OpenTransitRow, TransitRepository
from app.services.ais_parser import PositionUpdate
from app.services.transit_detector import (
    AbortReason,
    OpenTransit,
    TransitAborted,
    TransitCompleted,
    TransitDirection,
    TransitEvent,
    TransitStarted,
    VesselTrack,
    expire,
    on_position,
)
from app.services.zones import ZoneId, zone_at
from app.workers.ais_writer import Batch
from app.workers.common import backoff_delay

EXPIRE_INTERVAL_SECONDS = 60.0
# Al arrancar, cuánto hacia atrás se miran los tránsitos cerrados para saber si un buque sigue
# dentro de la zona donde cerró el suyo.
RESTORE_CLOSED_WINDOW = timedelta(hours=24)
MAX_ATTEMPTS = 3
RETRY_MAX_SECONDS = 5.0

logger = structlog.get_logger(__name__)

TransitWrite = OpenTransitRow | ClosedTransitRow


@dataclass
class TransitStats:
    restored: bool = False
    started: int = 0
    completed: int = 0
    aborted: int = 0
    events_dropped: int = 0
    batches_skipped: int = 0
    last_error: str | None = None


def direction_from(origin: ZoneId) -> TransitDirection:
    """Atlántico a Pacífico es `southbound`; Pacífico a Atlántico, `northbound` (como la ACP)."""
    if origin == "atlantic_entrance":
        return TransitDirection.SOUTHBOUND
    return TransitDirection.NORTHBOUND


def origin_from(direction: str) -> ZoneId:
    return "atlantic_entrance" if direction == TransitDirection.SOUTHBOUND else "pacific_entrance"


def exit_zone(row: ClosedTransitRow) -> ZoneId | None:
    """Zona en la que el buque estaba al cerrarse el tránsito, si se sabe.

    Completado: la entrada opuesta a la de origen. Abortado por reversa: la de origen. Abortado
    por timeout: el buque reapareció donde fuera (o no reapareció), no se sabe.
    """
    origin = origin_from(row.direction)
    if row.status == "completed":
        return "pacific_entrance" if origin == "atlantic_entrance" else "atlantic_entrance"
    if row.abort_reason == AbortReason.REVERSAL:
        return origin
    return None


def to_write(event: TransitEvent, origin: ZoneId | None) -> TransitWrite:
    """Fila que guarda un evento. `origin` es el del tránsito que cierra el evento, si cierra."""
    if isinstance(event, TransitStarted):
        return OpenTransitRow(
            mmsi=event.mmsi,
            direction=direction_from(event.origin).value,
            entered_at=event.entered_at,
        )
    if isinstance(event, TransitCompleted):
        return ClosedTransitRow(
            mmsi=event.mmsi,
            direction=event.direction.value,
            status="completed",
            abort_reason=None,
            entered_at=event.entered_at,
            exited_at=event.exited_at,
        )
    if origin is None:  # un aborto siempre cierra un tránsito abierto
        raise ValueError("TransitAborted sin tránsito abierto")
    return ClosedTransitRow(
        mmsi=event.mmsi,
        direction=direction_from(origin).value,
        status="aborted",
        abort_reason=event.reason.value,
        entered_at=event.entered_at,
        exited_at=event.aborted_at,
    )


class TransitTracker:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        timeout: timedelta,
        expire_interval: float = EXPIRE_INTERVAL_SECONDS,
        max_attempts: int = MAX_ATTEMPTS,
        retry_max_seconds: float = RETRY_MAX_SECONDS,
        retry_base_seconds: float = 1.0,
        rng: random.Random | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._timeout = timeout
        self._expire_interval = expire_interval
        self._max_attempts = max_attempts
        self._retry_max_seconds = retry_max_seconds
        self._retry_base_seconds = retry_base_seconds
        self._rng = rng or random.Random()  # noqa: S311 (jitter, no criptografía)
        self._clock = clock
        # Un lote y una expiración nunca tocan el estado a la vez.
        self._lock = asyncio.Lock()
        self.tracks: dict[int, VesselTrack] = {}
        self.stats = TransitStats()

    @property
    def open_transits(self) -> int:
        return sum(1 for track in self.tracks.values() if track.transit is not None)

    # --- Ciclo de vida -------------------------------------------------------------------------

    async def run(self, stop: asyncio.Event) -> None:
        """Reconstruye el estado (reintentando si la base no responde) y expira cada minuto."""
        attempt = 0
        while not self.stats.restored and not stop.is_set():
            try:
                await self.restore()
            except (DBAPIError, OSError, TimeoutError) as error:
                self.stats.last_error = type(error).__name__
                delay = backoff_delay(
                    attempt,
                    cap=self._retry_max_seconds * 6,
                    rng=self._rng,
                    base=self._retry_base_seconds,
                )
                attempt += 1
                logger.warning(
                    "transit_restore_retry", error=type(error).__name__, delay_seconds=delay
                )
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=delay)
        while not stop.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._expire_interval)
            if not stop.is_set():
                await self.expire(self._clock())

    async def restore(self) -> None:
        """Carga el estado del detector desde la base. Ver el docstring del módulo."""
        now = self._clock()
        tracks: dict[int, VesselTrack] = {}
        async with self._session_factory() as session:
            repository = TransitRepository(session)
            for row in await repository.open_transits():
                origin = origin_from(row.direction)
                points = await repository.track(row.mmsi, row.entered_at)
                tracks[row.mmsi] = VesselTrack(
                    mmsi=row.mmsi,
                    transit=OpenTransit(
                        origin=origin,
                        entered_at=row.entered_at,
                        left_origin=any(zone_at(p.lon, p.lat) != origin for p in points),
                    ),
                    last_seen_at=points[-1].received_at if points else row.entered_at,
                )
            for closed in await repository.last_closed_transits(now - RESTORE_CLOSED_WINDOW):
                zone = exit_zone(closed)
                if closed.mmsi in tracks or zone is None:
                    continue
                last = await repository.last_point(closed.mmsi)
                if last is None or last.received_at < closed.exited_at:
                    continue
                if zone_at(last.lon, last.lat) == zone:
                    tracks[closed.mmsi] = VesselTrack(
                        mmsi=closed.mmsi, last_seen_at=last.received_at, must_leave=zone
                    )
        async with self._lock:
            self.tracks = tracks
            self.stats.restored = True
        logger.info("transit_state_restored", open_transits=self.open_transits, tracks=len(tracks))
        # Lo que caducó mientras el worker estaba parado se cierra ya.
        await self.expire(now)

    # --- Eventos -------------------------------------------------------------------------------

    async def on_batch(self, batch: Batch) -> None:
        """Pasa por el detector las posiciones de un lote ya guardado y guarda los eventos."""
        if not self.stats.restored:
            self.stats.batches_skipped += 1
            return
        async with self._lock:
            writes: list[TransitWrite] = []
            for row in sorted(batch.positions, key=lambda row: (row.received_at, row.mmsi)):
                track = self.tracks.get(row.mmsi) or VesselTrack(mmsi=row.mmsi)
                origin = track.transit.origin if track.transit else None
                position = PositionUpdate(
                    mmsi=row.mmsi,
                    received_at=row.received_at,
                    lat=row.lat,
                    lon=row.lon,
                    sog=row.sog,
                    cog=row.cog,
                    heading=row.heading,
                    nav_status=row.nav_status,
                )
                self.tracks[row.mmsi], events = on_position(track, position, timeout=self._timeout)
                writes.extend(self._record(event, origin) for event in events)
            await self._save(writes)

    async def expire(self, now: datetime) -> None:
        """Aborta por timeout los tránsitos sin señal y olvida los buques que ya no hacen falta."""
        async with self._lock:
            writes: list[TransitWrite] = []
            for mmsi, track in list(self.tracks.items()):
                origin = track.transit.origin if track.transit else None
                updated, events = expire(track, now, timeout=self._timeout)
                writes.extend(self._record(event, origin) for event in events)
                if _forgettable(updated, now, self._timeout):
                    del self.tracks[mmsi]
                else:
                    self.tracks[mmsi] = updated
            await self._save(writes)

    def _record(self, event: TransitEvent, origin: ZoneId | None) -> TransitWrite:
        if isinstance(event, TransitStarted):
            self.stats.started += 1
        elif isinstance(event, TransitCompleted):
            self.stats.completed += 1
        elif isinstance(event, TransitAborted):
            self.stats.aborted += 1
        logger.info("transit_event", kind=type(event).__name__, mmsi=event.mmsi)
        return to_write(event, origin)

    async def _save(self, writes: list[TransitWrite]) -> None:
        if not writes:
            return
        for attempt in range(self._max_attempts):
            try:
                async with self._session_factory() as session:
                    try:
                        repository = TransitRepository(session)
                        for write in writes:
                            if isinstance(write, OpenTransitRow):
                                await repository.open_transit(write)
                            else:
                                await repository.close_transit(write)
                        await session.commit()
                    except BaseException:
                        await session.rollback()
                        raise
                return
            except (IntegrityError, DataError) as error:
                # La base rechaza el dato: reintentar daría lo mismo.
                self.stats.last_error = type(error).__name__
                break
            except (DBAPIError, OSError, TimeoutError) as error:
                self.stats.last_error = type(error).__name__
                if attempt + 1 == self._max_attempts:
                    break
                delay = backoff_delay(
                    attempt,
                    cap=self._retry_max_seconds,
                    rng=self._rng,
                    base=self._retry_base_seconds,
                )
                logger.warning(
                    "transit_save_retry", attempt=attempt + 1, error=type(error).__name__
                )
                await asyncio.sleep(delay)
        self.stats.events_dropped += len(writes)
        logger.error("transit_events_dropped", events=len(writes), error=self.stats.last_error)


def _forgettable(track: VesselTrack, now: datetime, timeout: timedelta) -> bool:
    """Un buque sin tránsito abierto ni zona pendiente, callado más que el timeout.

    Recordarlo solo serviría para ignorar posiciones viejas suyas, y esas ya no abrirían nada
    que no abriera un buque nuevo. Así el estado no crece con cada buque que pasa por el área.
    """
    return (
        track.transit is None
        and track.must_leave is None
        and track.last_seen_at is not None
        and now - track.last_seen_at > timeout
    )
