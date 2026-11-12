"""Detector de tránsitos (tarea 5.2): trayectorias sintéticas.

Escritos antes que la lógica (TDD): fallan con `NotImplementedError` hasta que `on_position`
exista de verdad. Los tests de abajo cubren lo básico; faltan los de la lista del diseño
(reversa, timeout, señal intermitente, buque detenido, posiciones antiguas...), que son tuyos.
"""

import itertools
from datetime import UTC, datetime, timedelta

import pytest

from app.services.ais_parser import PositionUpdate
from app.services.transit_detector import (
    AbortReason,
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

MMSI = 353_123_000
T0 = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
TIMEOUT = timedelta(minutes=30)  # TRANSIT_SIGNAL_TIMEOUT_MINUTES por defecto

# Puntos que `zone_at` sitúa dentro de cada entrada, y un punto en el lago Gatún (en ninguna).
IN_ATLANTIC = (-79.93, 9.40)
IN_PACIFIC = (-79.552, 8.91)
IN_THE_LAKE = (-79.90, 9.20)


def position(at: datetime, point: tuple[float, float]) -> PositionUpdate:
    # Sin COG: estos tests son de la máquina de estados y no dependen del rumbo. Con rumbo
    # desconocido el detector abre el tránsito sin mirar hacia dónde va el buque; las reglas del
    # rumbo (issue #121) están en tests/test_transit_direction.py.
    lon, lat = point
    return PositionUpdate(
        mmsi=MMSI, received_at=at, lat=lat, lon=lon, sog=10.0, cog=None, heading=None, nav_status=0
    )


def sail(
    waypoints: list[tuple[float, float]],
    *,
    start: datetime,
    hours: float,
    every: timedelta = timedelta(minutes=10),
) -> list[PositionUpdate]:
    """Posiciones a lo largo de una ruta con rumbo recto entre los puntos, a ritmo constante.

    Emite una posición cada `every`, desde `start` hasta `start + hours`, repartidas por la
    ruta según el tiempo. La primera cae en el primer punto y la última en el último.
    """
    total = timedelta(hours=hours)
    legs = len(waypoints) - 1
    positions = []
    steps = int(total / every)
    for step in range(steps + 1):
        progress = step / steps * legs  # 0..legs
        leg = min(int(progress), legs - 1)
        fraction = progress - leg
        (lon1, lat1), (lon2, lat2) = waypoints[leg], waypoints[leg + 1]
        point = (lon1 + (lon2 - lon1) * fraction, lat1 + (lat2 - lat1) * fraction)
        positions.append(position(start + step * every, point))
    return positions


def feed(
    track: VesselTrack, positions: list[PositionUpdate]
) -> tuple[VesselTrack, list[TransitEvent]]:
    """Pasa las posiciones por el detector en orden y junta todos los eventos."""
    events: list[TransitEvent] = []
    for item in positions:
        track, produced = on_position(track, item, timeout=TIMEOUT)
        events.extend(produced)
    return track, events


def test_the_helpers_place_the_points_where_the_tests_assume() -> None:
    assert zone_at(*IN_ATLANTIC) == "atlantic_entrance"
    assert zone_at(*IN_PACIFIC) == "pacific_entrance"
    assert zone_at(*IN_THE_LAKE) is None

    route = sail([IN_ATLANTIC, IN_THE_LAKE, IN_PACIFIC], start=T0, hours=9)
    assert route[0].received_at == T0
    assert route[-1].received_at == T0 + timedelta(hours=9)
    assert zone_at(route[0].lon, route[0].lat) == "atlantic_entrance"
    assert zone_at(route[-1].lon, route[-1].lat) == "pacific_entrance"
    gaps = {b.received_at - a.received_at for a, b in itertools.pairwise(route)}
    assert gaps == {timedelta(minutes=10)}  # siempre por debajo del timeout


def test_a_position_outside_every_zone_does_nothing() -> None:
    track = VesselTrack(mmsi=MMSI)

    new_track, events = on_position(track, position(T0, IN_THE_LAKE), timeout=TIMEOUT)

    assert events == []
    assert new_track.transit is None


def test_the_first_position_in_an_entrance_opens_a_transit() -> None:
    track = VesselTrack(mmsi=MMSI)

    new_track, events = on_position(track, position(T0, IN_ATLANTIC), timeout=TIMEOUT)

    assert events == [TransitStarted(mmsi=MMSI, origin="atlantic_entrance", entered_at=T0)]
    assert new_track.transit is not None
    assert new_track.transit.origin == "atlantic_entrance"
    assert new_track.transit.entered_at == T0
    assert track.transit is None  # el estado anterior no se modifica


def test_atlantic_to_pacific_is_a_completed_southbound_transit() -> None:
    route = sail([IN_ATLANTIC, IN_THE_LAKE, IN_PACIFIC], start=T0, hours=9)

    final_track, events = feed(VesselTrack(mmsi=MMSI), route)

    started, completed = events  # exactamente dos eventos, en este orden
    assert started == TransitStarted(mmsi=MMSI, origin="atlantic_entrance", entered_at=T0)
    assert isinstance(completed, TransitCompleted)
    assert completed.direction is TransitDirection.SOUTHBOUND
    assert completed.entered_at == T0
    assert completed.exited_at == T0 + timedelta(hours=9)
    assert completed.duration == timedelta(hours=9)
    assert final_track.transit is None


def test_a_vessel_that_left_the_zone_it_finished_in_can_start_a_new_transit() -> None:
    # Termina el tránsito en la entrada del Pacífico, sale al mar y días después vuelve a esa
    # misma entrada (para ir hacia el Atlántico). Ese regreso debe abrir un tránsito nuevo.
    route = sail([IN_ATLANTIC, IN_THE_LAKE, IN_PACIFIC], start=T0, hours=9)
    track, _ = feed(VesselTrack(mmsi=MMSI), route)
    out_at_sea = position(T0 + timedelta(hours=10), (-79.40, 8.80))
    back = position(T0 + timedelta(days=3), IN_PACIFIC)

    track, events = feed(track, [out_at_sea, back])

    assert events == [
        TransitStarted(mmsi=MMSI, origin="pacific_entrance", entered_at=T0 + timedelta(days=3))
    ]
    assert track.transit is not None


def test_staying_in_the_final_zone_after_completing_does_not_open_another_transit() -> None:
    # Al completar, el buque sigue dentro de la entrada del Pacífico y sigue emitiendo. Esas
    # posiciones no son el comienzo de un tránsito nuevo.
    route = sail([IN_ATLANTIC, IN_THE_LAKE, IN_PACIFIC], start=T0, hours=9)
    track, _ = feed(VesselTrack(mmsi=MMSI), route)
    lingering = [position(T0 + timedelta(hours=9, minutes=m), IN_PACIFIC) for m in (10, 20, 30)]

    track, events = feed(track, lingering)

    assert events == []
    assert track.transit is None


def test_a_position_with_the_same_time_as_the_last_one_is_ignored() -> None:
    track, _ = feed(VesselTrack(mmsi=MMSI), [position(T0, IN_ATLANTIC)])

    # Misma hora que la última, pero en otro sitio: si se procesara, el buque habría "salido".
    after, events = on_position(track, position(T0, IN_THE_LAKE), timeout=TIMEOUT)

    assert events == []
    assert after == track
    assert after.transit is not None
    assert after.transit.left_origin is False


def test_a_position_older_than_the_last_one_is_ignored() -> None:
    track, _ = feed(
        VesselTrack(mmsi=MMSI),
        [
            position(T0, IN_ATLANTIC),
            position(T0 + timedelta(minutes=20), IN_THE_LAKE),
        ],
    )

    # Llega tarde (un reintento del worker) una posición de hace 10 minutos, ya en el Pacífico:
    # no puede completar el tránsito ni mover el reloj hacia atrás.
    after, events = on_position(
        track, position(T0 + timedelta(minutes=10), IN_PACIFIC), timeout=TIMEOUT
    )

    assert events == []
    assert after == track
    assert after.last_seen_at == T0 + timedelta(minutes=20)


def out_and_back(
    origin_point: tuple[float, float], zone: ZoneId
) -> tuple[list[PositionUpdate], PositionUpdate]:
    """Ruta que sale de una entrada, se aleja por el lago y vuelve a la misma entrada.

    Devuelve las posiciones y la primera que, tras haber salido, vuelve a caer en la zona.
    """
    route = sail([origin_point, IN_THE_LAKE, origin_point], start=T0, hours=2)
    zones = [zone_at(item.lon, item.lat) for item in route]
    left = zones.index(None)
    back = next(i for i in range(left, len(route)) if zones[i] == zone)
    return route, route[back]


@pytest.mark.parametrize(
    ("zone", "point"),
    [
        pytest.param("atlantic_entrance", IN_ATLANTIC, id="atlantic"),
        pytest.param("pacific_entrance", IN_PACIFIC, id="pacific"),
    ],
)
def test_leaving_the_origin_zone_and_coming_back_aborts_the_transit_by_reversal(
    zone: ZoneId, point: tuple[float, float]
) -> None:
    route, first_back = out_and_back(point, zone)

    track, events = feed(VesselTrack(mmsi=MMSI), route)

    # Un solo aborto, en la primera posición de vuelta. Las que siguen dentro de la zona no
    # abren un tránsito nuevo: el buque tiene que salir antes.
    assert events == [
        TransitStarted(mmsi=MMSI, origin=zone, entered_at=T0),
        TransitAborted(
            mmsi=MMSI,
            reason=AbortReason.REVERSAL,
            entered_at=T0,
            aborted_at=first_back.received_at,
        ),
    ]
    assert track.transit is None


def test_a_vessel_that_aborted_by_reversal_can_start_again_after_leaving_the_zone() -> None:
    route, _ = out_and_back(IN_ATLANTIC, "atlantic_entrance")
    track, _ = feed(VesselTrack(mmsi=MMSI), route)
    out = position(T0 + timedelta(hours=3), IN_THE_LAKE)
    in_again = position(T0 + timedelta(hours=4), IN_ATLANTIC)

    track, events = feed(track, [out, in_again])

    assert events == [
        TransitStarted(mmsi=MMSI, origin="atlantic_entrance", entered_at=T0 + timedelta(hours=4))
    ]
    assert track.transit is not None


def opened_at_the_atlantic() -> VesselTrack:
    track, _ = feed(VesselTrack(mmsi=MMSI), [position(T0, IN_ATLANTIC)])
    return track


def test_expire_leaves_a_transit_alone_until_the_timeout_is_exceeded() -> None:
    track = opened_at_the_atlantic()

    inside, inside_events = expire(track, T0 + timedelta(minutes=10), timeout=TIMEOUT)
    at_the_limit, limit_events = expire(track, T0 + TIMEOUT, timeout=TIMEOUT)

    assert inside_events == [] and inside == track
    assert limit_events == [] and at_the_limit == track  # justo el timeout todavía no aborta


def test_expire_aborts_by_timeout_once_the_limit_is_exceeded() -> None:
    track = opened_at_the_atlantic()

    after, events = expire(track, T0 + TIMEOUT + timedelta(seconds=1), timeout=TIMEOUT)

    # La hora del aborto es cuando se cumplió el plazo, no cuando alguien lo comprobó: no depende
    # de cada cuánto llame el worker a `expire`.
    assert events == [
        TransitAborted(
            mmsi=MMSI,
            reason=AbortReason.TIMEOUT,
            entered_at=T0,
            aborted_at=T0 + TIMEOUT,
        )
    ]
    assert after.transit is None


def test_expire_does_nothing_without_an_open_transit() -> None:
    track = VesselTrack(mmsi=MMSI)

    after, events = expire(track, T0 + timedelta(days=1), timeout=TIMEOUT)

    assert events == [] and after == track


def test_a_late_position_aborts_the_old_transit_and_nothing_else() -> None:
    track = opened_at_the_atlantic()
    late = position(T0 + TIMEOUT + timedelta(minutes=1), IN_THE_LAKE)

    after, events = on_position(track, late, timeout=TIMEOUT)

    assert events == [
        TransitAborted(
            mmsi=MMSI, reason=AbortReason.TIMEOUT, entered_at=T0, aborted_at=T0 + TIMEOUT
        )
    ]
    assert after.transit is None
    assert after.last_seen_at == late.received_at


def test_a_late_position_in_the_opposite_zone_aborts_and_does_not_start_a_ghost_transit() -> None:
    # Reaparece en el Pacífico después de un hueco largo. Se aborta el tránsito viejo; esa
    # posición no abre un tránsito desde el Pacífico, ni las siguientes mientras siga en la zona.
    track = opened_at_the_atlantic()
    late = position(T0 + timedelta(hours=2), IN_PACIFIC)
    lingering = position(T0 + timedelta(hours=2, minutes=10), IN_PACIFIC)

    track, events = feed(track, [late, lingering])

    assert [type(event) for event in events] == [TransitAborted]
    assert track.transit is None


def test_a_gap_of_exactly_the_timeout_does_not_abort() -> None:
    route = [
        position(T0, IN_ATLANTIC),
        position(T0 + TIMEOUT, IN_THE_LAKE),  # hueco justo igual al timeout
        position(T0 + 2 * TIMEOUT, IN_PACIFIC),
    ]

    _, events = feed(VesselTrack(mmsi=MMSI), route)

    assert [type(event) for event in events] == [TransitStarted, TransitCompleted]


def test_an_intermittent_signal_with_gaps_under_the_timeout_still_completes() -> None:
    # Una posición cada 25 minutos durante 9 horas: nunca pasa el timeout de 30.
    route = sail(
        [IN_ATLANTIC, IN_THE_LAKE, IN_PACIFIC], start=T0, hours=9, every=timedelta(minutes=25)
    )

    _, events = feed(VesselTrack(mmsi=MMSI), route)

    assert [type(event) for event in events] == [TransitStarted, TransitCompleted]


def test_after_a_timeout_the_vessel_can_start_a_new_transit() -> None:
    track, _ = expire(opened_at_the_atlantic(), T0 + timedelta(hours=1), timeout=TIMEOUT)
    again = position(T0 + timedelta(hours=2), IN_ATLANTIC)

    track, events = on_position(track, again, timeout=TIMEOUT)

    assert events == [
        TransitStarted(mmsi=MMSI, origin="atlantic_entrance", entered_at=T0 + timedelta(hours=2))
    ]


def test_pacific_to_atlantic_is_a_completed_northbound_transit() -> None:
    route = sail([IN_PACIFIC, IN_THE_LAKE, IN_ATLANTIC], start=T0, hours=9)

    final_track, events = feed(VesselTrack(mmsi=MMSI), route)

    started, completed = events
    assert started == TransitStarted(mmsi=MMSI, origin="pacific_entrance", entered_at=T0)
    assert isinstance(completed, TransitCompleted)
    assert completed.direction is TransitDirection.NORTHBOUND
    # Sale en cuanto la ruta toca la entrada del Atlántico, algo antes de la última muestra.
    assert timedelta(hours=8) < completed.duration <= timedelta(hours=9)
    assert final_track.transit is None


def test_a_vessel_stopped_inside_the_entrance_for_days_opens_one_transit_and_nothing_else() -> None:
    # Fondeado dentro de la zona de entrada: una posición cada 10 minutos durante 3 días.
    stopped = [position(T0 + timedelta(minutes=10 * n), IN_ATLANTIC) for n in range(432)]

    track, events = feed(VesselTrack(mmsi=MMSI), stopped)

    assert [type(event) for event in events] == [TransitStarted]
    assert track.transit is not None
    assert track.transit.left_origin is False  # sin salir de la zona no hay reversa posible


def test_a_vessel_stopped_in_the_lake_longer_than_the_timeout_stays_open_while_it_reports() -> None:
    # Espera turno en el lago durante 5 horas, emitiendo cada 10 minutos: no hay hueco de señal.
    waiting = [position(T0 + timedelta(minutes=10 * n), IN_THE_LAKE) for n in range(31)]

    track, events = feed(VesselTrack(mmsi=MMSI), [position(T0, IN_ATLANTIC), *waiting[1:]])

    assert [type(event) for event in events] == [TransitStarted]
    assert track.transit is not None
    assert track.transit.left_origin is True


def test_a_vessel_stopped_in_the_lake_that_stops_reporting_is_aborted_by_timeout() -> None:
    track, events = feed(
        VesselTrack(mmsi=MMSI),
        [position(T0, IN_ATLANTIC), position(T0 + timedelta(minutes=20), IN_THE_LAKE)],
    )

    track, expired = expire(
        track, T0 + timedelta(minutes=20) + TIMEOUT + timedelta(seconds=1), timeout=TIMEOUT
    )

    assert [type(event) for event in events] == [TransitStarted]
    assert [type(event) for event in expired] == [TransitAborted]
    assert isinstance(expired[0], TransitAborted)
    assert expired[0].reason is AbortReason.TIMEOUT
