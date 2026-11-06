"""Detección de esperas en fondeo dentro del worker AIS (tarea 6.1).

Une el detector puro (`app/services/anchorage_detector.py`) con la base de datos, igual que
`transit_tracker.py` hace con los tránsitos:

1. **Tras cada lote guardado**, pasa las posiciones por el detector, en orden cronológico, y guarda
   en `anchorage_visits` los eventos: abrir una visita al confirmarse la espera o cerrarla.
2. **Cada minuto** llama a `expire` con la hora actual, porque un buque que deja de emitir no
   manda ninguna posición que dispare el timeout.
3. **Al arrancar** reconstruye el estado desde la base: las visitas abiertas, con la hora de la
   última señal de cada buque. Una espera todavía no confirmada (menos de 15 minutos) se pierde en
   un reinicio: es lo único que no está en la base.

El estado vive en memoria; la base es la fuente de verdad. Si la base no responde al guardar, se
reintenta unas veces y, si sigue sin responder, se descartan esos eventos y se cuentan. Mientras no
termine la reconstrucción, los lotes no pasan por el detector (`batches_skipped`).
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
from app.repositories.anchorages import (
    AnchorageRepository,
    ClosedVisitRow,
    OpenVisitRow,
)
from app.services.ais_parser import PositionUpdate
from app.services.anchorage_detector import (
    AnchorageEvent,
    AnchorageTrack,
    OpenVisit,
    VisitEnded,
    VisitStarted,
    expire,
    on_position,
)
from app.services.anchorages import AnchorageId
from app.services.waiting import match_visits_to_transits
from app.workers.ais_writer import Batch
from app.workers.common import backoff_delay

EXPIRE_INTERVAL_SECONDS = 60.0
# Hasta dónde se miran atrás las visitas y los tránsitos sin enlazar: más que `MAX_WAIT_GAP` más la
# duración de un tránsito, para no perder el enlace de una espera larga que acaba de terminar.
LINK_WINDOW = timedelta(hours=72)
MAX_ATTEMPTS = 3
RETRY_MAX_SECONDS = 5.0

logger = structlog.get_logger(__name__)

VisitWrite = OpenVisitRow | ClosedVisitRow


@dataclass
class AnchorageStats:
    restored: bool = False
    started: int = 0
    ended: int = 0
    events_dropped: int = 0
    batches_skipped: int = 0
    linked: int = 0
    last_error: str | None = None


def to_write(event: AnchorageEvent) -> VisitWrite:
    """Fila que guarda un evento."""
    if isinstance(event, VisitStarted):
        return OpenVisitRow(mmsi=event.mmsi, anchorage=event.anchorage, arrived_at=event.arrived_at)
    return ClosedVisitRow(
        mmsi=event.mmsi,
        anchorage=event.anchorage,
        arrived_at=event.arrived_at,
        departed_at=event.departed_at,
    )


class AnchorageTracker:
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
        self.tracks: dict[int, AnchorageTrack] = {}
        self.stats = AnchorageStats()

    @property
    def open_visits(self) -> int:
        return sum(1 for track in self.tracks.values() if track.visit is not None)

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
                    "anchorage_restore_retry", error=type(error).__name__, delay_seconds=delay
                )
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=delay)
        while not stop.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._expire_interval)
            if not stop.is_set():
                now = self._clock()
                await self.expire(now)
                await self.link(now)

    async def restore(self) -> None:
        """Carga las visitas abiertas desde la base. Ver el docstring del módulo."""
        now = self._clock()
        tracks: dict[int, AnchorageTrack] = {}
        async with self._session_factory() as session:
            repository = AnchorageRepository(session)
            for row in await repository.open_visits():
                last = await repository.last_signal(row.mmsi)
                anchorage: AnchorageId = "atlantic" if row.anchorage == "atlantic" else "pacific"
                tracks[row.mmsi] = AnchorageTrack(
                    mmsi=row.mmsi,
                    visit=OpenVisit(anchorage=anchorage, arrived_at=row.arrived_at),
                    last_seen_at=max(last, row.arrived_at) if last else row.arrived_at,
                )
        async with self._lock:
            self.tracks = tracks
            self.stats.restored = True
        logger.info("anchorage_state_restored", open_visits=self.open_visits)
        # Lo que caducó mientras el worker estaba parado se cierra ya.
        await self.expire(now)

    # --- Eventos -------------------------------------------------------------------------------

    async def on_batch(self, batch: Batch) -> None:
        """Pasa por el detector las posiciones de un lote ya guardado y guarda los eventos."""
        if not self.stats.restored:
            self.stats.batches_skipped += 1
            return
        async with self._lock:
            writes: list[VisitWrite] = []
            for row in sorted(batch.positions, key=lambda row: (row.received_at, row.mmsi)):
                track = self.tracks.get(row.mmsi) or AnchorageTrack(mmsi=row.mmsi)
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
                writes.extend(self._record(event) for event in events)
            await self._save(writes)

    async def expire(self, now: datetime) -> None:
        """Cierra por timeout las visitas sin señal y olvida los buques que ya no hacen falta."""
        async with self._lock:
            writes: list[VisitWrite] = []
            for mmsi, track in list(self.tracks.items()):
                updated, events = expire(track, now, timeout=self._timeout)
                writes.extend(self._record(event) for event in events)
                if (
                    updated.visit is None
                    and updated.candidate is None
                    and _silent(updated, now, self._timeout)
                ):
                    del self.tracks[mmsi]
                else:
                    self.tracks[mmsi] = updated
            await self._save(writes)

    async def link(self, now: datetime) -> None:
        """Enlaza cada visita con el tránsito que la sigue (6.2). Idempotente.

        Va aparte de los eventos porque los dos detectores trabajan por su cuenta: el tránsito
        puede abrirse antes o después de que se cierre la visita, y el enlace no depende del orden.
        Se repite cada minuto sobre lo reciente sin enlazar, así que también cubre los reinicios y
        los eventos que se guardaron tarde. Un fallo de la base se registra y se reintenta en la
        siguiente pasada.
        """
        since = now - LINK_WINDOW
        try:
            async with self._session_factory() as session:
                repository = AnchorageRepository(session)
                pairs = match_visits_to_transits(
                    await repository.unlinked_visits(since),
                    await repository.unlinked_transits(since),
                )
                linked = 0
                for visit_id, transit_id in pairs:
                    linked += await repository.link(visit_id, transit_id)
                await session.commit()
        except (DBAPIError, OSError, TimeoutError) as error:
            self.stats.last_error = type(error).__name__
            logger.warning("anchorage_link_failed", error=type(error).__name__)
            return
        self.stats.linked += linked
        if linked:
            logger.info("anchorage_visits_linked", linked=linked)

    def _record(self, event: AnchorageEvent) -> VisitWrite:
        if isinstance(event, VisitStarted):
            self.stats.started += 1
        elif isinstance(event, VisitEnded):
            self.stats.ended += 1
        logger.info("anchorage_event", kind=type(event).__name__, mmsi=event.mmsi)
        return to_write(event)

    async def _save(self, writes: list[VisitWrite]) -> None:
        if not writes:
            return
        for attempt in range(self._max_attempts):
            try:
                async with self._session_factory() as session:
                    try:
                        repository = AnchorageRepository(session)
                        for write in writes:
                            if isinstance(write, OpenVisitRow):
                                await repository.open_visit(write)
                            else:
                                await repository.close_visit(write)
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
                    "anchorage_save_retry", attempt=attempt + 1, error=type(error).__name__
                )
                await asyncio.sleep(delay)
        self.stats.events_dropped += len(writes)
        logger.error("anchorage_events_dropped", events=len(writes), error=self.stats.last_error)


def _silent(track: AnchorageTrack, now: datetime, timeout: timedelta) -> bool:
    """Callado más que el timeout: recordarlo no sirve y el estado no crece con cada buque."""
    return track.last_seen_at is not None and now - track.last_seen_at > timeout
