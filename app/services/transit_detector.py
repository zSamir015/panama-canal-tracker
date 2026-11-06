"""Detector de tránsitos del Canal: máquina de estados pura por buque (tarea 5.2).

Convierte las posiciones de un buque en eventos de tránsito. No toca base de datos, Redis ni el
reloj: quien lo use (el worker, en la 5.3) le pasa las posiciones y la hora actual, y guarda el
estado de cada buque entre llamadas. Así se prueba con trayectorias sintéticas.

Las reglas (docs/ARCHITECTURE.md §4.2):

| Situación                                            | Resultado                              |
|------------------------------------------------------|----------------------------------------|
| sin tránsito y aparece en una zona de entrada        | abre `in_progress` desde esa zona      |
| `in_progress` y aparece en la zona opuesta           | `completed` (dirección según el origen)|
| `in_progress` y vuelve a la zona de origen           | `aborted` por reversa                  |
| `in_progress` y pasa más del timeout sin señal       | `aborted` por timeout                  |

Dirección, como la ACP: Atlántico a Pacífico es `southbound`; Pacífico a Atlántico, `northbound`.

El estado es inmutable: cada función devuelve el estado nuevo y la lista de eventos, sin modificar
el que recibe.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum

from app.services.ais_parser import PositionUpdate
from app.services.zones import ZoneId, zone_at


class TransitDirection(StrEnum):
    SOUTHBOUND = "southbound"  # Atlántico a Pacífico
    NORTHBOUND = "northbound"  # Pacífico a Atlántico


class AbortReason(StrEnum):
    TIMEOUT = "timeout"  # demasiado tiempo sin señal
    REVERSAL = "reversal"  # salió de la zona de origen y volvió a ella


@dataclass(frozen=True, slots=True)
class OpenTransit:
    """Un tránsito `in_progress`."""

    origin: ZoneId
    entered_at: datetime
    # Ya salió de la zona de origen alguna vez. Sin esto no se distingue "sigue en la zona de
    # entrada" de "dio la vuelta y volvió".
    left_origin: bool = False


@dataclass(frozen=True, slots=True)
class VesselTrack:
    """Lo que el detector recuerda de un buque entre posiciones.

    `last_seen_at`: hora de la última posición aceptada (para ignorar las que llegan antes).
    `must_leave`: zona en la que acabó un tránsito; hasta que el buque salga de ella no puede
    abrir otro, o sus siguientes posiciones en esa zona abrirían uno nuevo cada vez.
    """

    mmsi: int
    transit: OpenTransit | None = None
    last_seen_at: datetime | None = None
    must_leave: ZoneId | None = None


@dataclass(frozen=True, slots=True)
class TransitStarted:
    mmsi: int
    origin: ZoneId
    entered_at: datetime


@dataclass(frozen=True, slots=True)
class TransitCompleted:
    mmsi: int
    direction: TransitDirection
    entered_at: datetime
    exited_at: datetime

    @property
    def duration(self) -> timedelta:
        return self.exited_at - self.entered_at


@dataclass(frozen=True, slots=True)
class TransitAborted:
    mmsi: int
    reason: AbortReason
    entered_at: datetime
    aborted_at: datetime


TransitEvent = TransitStarted | TransitCompleted | TransitAborted


def on_position(
    track: VesselTrack, position: PositionUpdate, *, timeout: timedelta
) -> tuple[VesselTrack, list[TransitEvent]]:
    """Procesa una posición del buque. Devuelve su estado nuevo y los eventos que provoca.

    Una posición con `received_at` anterior o igual a `track.last_seen_at` se ignora.
    Una posición cuya zona es la de origen del tránsito abierto lo aborta por reversa si el buque
    ya había salido de ella; si no, sigue dentro y no pasa nada.
    Una posición que llega pasado el `timeout` desde la última señal aborta el tránsito abierto
    (motivo `TIMEOUT`) y no se procesa más: no completa ni abre otro tránsito, y el buque debe
    salir de la zona en la que reaparece antes de poder abrir uno nuevo.
    Cada posición provoca como mucho un evento. Tras completar o abortar en una zona, el buque
    debe salir de ella antes de poder abrir otro tránsito.
    """
    if track.last_seen_at is not None and position.received_at <= track.last_seen_at:
        return track, []

    zone = zone_at(position.lon, position.lat)

    # Un hueco más largo que el timeout ya habría abortado el tránsito si alguien hubiera llamado
    # a `expire`; aquí se hace al llegar la posición tardía, antes de mirar qué dice.
    expired_track, expired_events = expire(track, position.received_at, timeout=timeout)
    if expired_events:
        return replace(expired_track, last_seen_at=position.received_at, must_leave=zone), (
            expired_events
        )

    updated_track = replace(track, last_seen_at=position.received_at)

    if updated_track.transit is None:
        if zone is None:
            return replace(updated_track, must_leave=None), []
        if updated_track.must_leave == zone:
            return updated_track, []

        transit = OpenTransit(
            origin=zone,
            entered_at=position.received_at,
        )
        return replace(updated_track, transit=transit, must_leave=None), [
            TransitStarted(mmsi=track.mmsi, origin=zone, entered_at=position.received_at)
        ]

    transit = updated_track.transit
    if zone == transit.origin:
        if not transit.left_origin:
            return updated_track, []  # sigue dentro de la zona por la que entró
        # Salió de la zona de origen y ha vuelto a ella: dio la vuelta. Se aborta, y como tras
        # completar, el buque debe salir de la zona antes de poder abrir otro tránsito: así esta
        # posición provoca un solo evento y un buque que merodea por la entrada no encadena
        # abortos y aperturas.
        aborted = TransitAborted(
            mmsi=track.mmsi,
            reason=AbortReason.REVERSAL,
            entered_at=transit.entered_at,
            aborted_at=position.received_at,
        )
        return replace(updated_track, transit=None, must_leave=zone), [aborted]
    if zone is None:
        if transit.left_origin:
            return updated_track, []
        return replace(updated_track, transit=replace(transit, left_origin=True)), []

    direction = (
        TransitDirection.SOUTHBOUND
        if transit.origin == "atlantic_entrance"
        else TransitDirection.NORTHBOUND
    )
    completed = TransitCompleted(
        mmsi=track.mmsi,
        direction=direction,
        entered_at=transit.entered_at,
        exited_at=position.received_at,
    )
    return replace(updated_track, transit=None, must_leave=zone), [completed]


def expire(
    track: VesselTrack, now: datetime, *, timeout: timedelta
) -> tuple[VesselTrack, list[TransitEvent]]:
    """Cierra como `aborted` por timeout el tránsito abierto si `now` ya pasó el límite.

    Lo llama quien tenga el reloj (el worker, en la 5.3), porque un buque que deja de emitir no
    produce ninguna posición que dispare la comprobación.

    Aborta cuando han pasado **más** de `timeout` desde la última señal (justo `timeout` todavía
    no). La hora del aborto es `última señal + timeout`, el momento en que se cumplió el plazo, y
    no `now`: así no depende de cada cuánto se llame a esta función.
    """
    if track.transit is None or track.last_seen_at is None:
        return track, []

    deadline = track.last_seen_at + timeout
    if now <= deadline:
        return track, []

    aborted = TransitAborted(
        mmsi=track.mmsi,
        reason=AbortReason.TIMEOUT,
        entered_at=track.transit.entered_at,
        aborted_at=deadline,
    )
    return replace(track, transit=None), [aborted]
