"""Detector de esperas en fondeo: máquina de estados pura por buque (tarea 6.1).

Convierte las posiciones de un buque en visitas a un fondeadero. Como `transit_detector`, no toca
base de datos, Redis ni el reloj: quien lo use (el worker) le pasa las posiciones y la hora actual
y guarda el estado de cada buque entre llamadas.

Reglas (docs/ARCHITECTURE.md §4.3):

| Situación                                                          | Resultado                  |
|--------------------------------------------------------------------|----------------------------|
| dentro de un fondeadero y parado durante `MIN_STAY` seguidos       | abre una visita            |
| con visita abierta, sale del fondeadero o navega a >= 1 nudo       | cierra la visita           |
| con visita abierta, pasa más del timeout sin señal                 | cierra la visita           |

"Parado" es velocidad menor de 0,5 nudos o, si el buque no informa de velocidad, estado de
navegación "fondeado". La velocidad manda sobre el estado de navegación, que la tripulación
cambia a mano y casi nunca actualiza. Entre 0,5 y 1 nudo (el buque borneando sobre el ancla) ni
se confirma una espera ni se rompe: así un fondeo con deriva no se corta en visitas pequeñas.

La visita se registra al confirmarse la espera, pero `arrived_at` es la hora en que el buque
empezó a estar parado, no la de la confirmación. Una parada de menos de `MIN_STAY` no deja rastro.
Si el buque deja de emitir, la visita se cierra a la hora de su última señal.

El estado es inmutable: cada función devuelve el estado nuevo y la lista de eventos.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from app.services.ais_parser import PositionUpdate
from app.services.anchorages import AnchorageId, anchorage_at

STATIONARY_SOG = 0.5  # nudos: por debajo, parado
DEPARTURE_SOG = 1.0  # nudos: desde aquí, navegando
NAV_STATUS_AT_ANCHOR = 1
MIN_STAY = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class StopCandidate:
    """Parado dentro de un fondeadero desde `since`, sin llegar aún a `MIN_STAY`."""

    anchorage: AnchorageId
    since: datetime


@dataclass(frozen=True, slots=True)
class OpenVisit:
    anchorage: AnchorageId
    arrived_at: datetime


@dataclass(frozen=True, slots=True)
class AnchorageTrack:
    """Lo que el detector recuerda de un buque entre posiciones."""

    mmsi: int
    candidate: StopCandidate | None = None
    visit: OpenVisit | None = None
    last_seen_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class VisitStarted:
    mmsi: int
    anchorage: AnchorageId
    arrived_at: datetime


@dataclass(frozen=True, slots=True)
class VisitEnded:
    mmsi: int
    anchorage: AnchorageId
    arrived_at: datetime
    departed_at: datetime

    @property
    def duration(self) -> timedelta:
        return self.departed_at - self.arrived_at


AnchorageEvent = VisitStarted | VisitEnded


def is_stationary(position: PositionUpdate) -> bool:
    if position.sog is not None:
        return position.sog < STATIONARY_SOG
    return position.nav_status == NAV_STATUS_AT_ANCHOR


def is_underway(position: PositionUpdate) -> bool:
    return position.sog is not None and position.sog >= DEPARTURE_SOG


def on_position(
    track: AnchorageTrack, position: PositionUpdate, *, timeout: timedelta
) -> tuple[AnchorageTrack, list[AnchorageEvent]]:
    """Procesa una posición del buque. Devuelve su estado nuevo y los eventos que provoca.

    Una posición con `received_at` anterior o igual a `track.last_seen_at` se ignora. Si pasó más
    del `timeout` desde la última señal, primero se cierra la visita abierta (a la hora de esa
    última señal) y después se procesa la posición como la de un buque que reaparece.
    """
    if track.last_seen_at is not None and position.received_at <= track.last_seen_at:
        return track, []

    track, events = expire(track, position.received_at, timeout=timeout)
    track = replace(track, last_seen_at=position.received_at)
    anchorage = anchorage_at(position.lon, position.lat)
    stationary = anchorage is not None and is_stationary(position)

    if track.visit is not None:
        if anchorage == track.visit.anchorage and not is_underway(position):
            return track, events
        ended = VisitEnded(
            mmsi=track.mmsi,
            anchorage=track.visit.anchorage,
            arrived_at=track.visit.arrived_at,
            departed_at=position.received_at,
        )
        track = replace(track, visit=None, candidate=None)
        events = [*events, ended]
        # Dejó un fondeadero y ya está parado en otro (o en el mismo tras moverse): empieza de cero.
        if stationary and anchorage is not None:
            track = replace(track, candidate=StopCandidate(anchorage, position.received_at))
        return track, events

    candidate = track.candidate
    if stationary and anchorage is not None:
        if candidate is None or candidate.anchorage != anchorage:
            candidate = StopCandidate(anchorage, position.received_at)
        if position.received_at - candidate.since >= MIN_STAY:
            visit = OpenVisit(anchorage=anchorage, arrived_at=candidate.since)
            started = VisitStarted(mmsi=track.mmsi, anchorage=anchorage, arrived_at=candidate.since)
            return replace(track, candidate=None, visit=visit), [*events, started]
        return replace(track, candidate=candidate), events

    if candidate is not None and (anchorage != candidate.anchorage or is_underway(position)):
        track = replace(track, candidate=None)
    return track, events


def expire(
    track: AnchorageTrack, now: datetime, *, timeout: timedelta
) -> tuple[AnchorageTrack, list[AnchorageEvent]]:
    """Cierra la visita abierta si `now` ya pasó el límite desde la última señal.

    Lo llama quien tenga el reloj (el worker): un buque que deja de emitir no produce ninguna
    posición que dispare la comprobación. Aborta cuando han pasado **más** de `timeout` (justo
    `timeout` todavía no), y la hora de salida es la de la última señal, no `now`. Un candidato
    que lleva más del `timeout` sin señal también se descarta (sin evento).
    """
    last_seen_at = track.last_seen_at
    if last_seen_at is None or now <= last_seen_at + timeout:
        return track, []

    track = replace(track, candidate=None)
    if track.visit is None:
        return track, []
    ended = VisitEnded(
        mmsi=track.mmsi,
        anchorage=track.visit.anchorage,
        arrived_at=track.visit.arrived_at,
        departed_at=last_seen_at,
    )
    return replace(track, visit=None), [ended]
