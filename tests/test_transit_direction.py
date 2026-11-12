"""Entrar o salir de una zona de entrada según el rumbo (issue #121).

Escritos antes que la lógica (TDD). Con datos reales (docs/VALIDATION.md) la mitad de los buques que
pisan una zona de entrada están **saliendo** del Canal, y el detector abría con ellos un tránsito
en sentido contrario que acababa abortado. El contrato que estos tests fijan:

- `heading_into_canal(zone, position)` devuelve `True` si el buque navega hacia el interior del
  Canal, `False` si navega hacia el mar y `None` si no se puede saber (sin COG, sin SOG, parado o
  de través).
- Hacia dentro = el COG está a menos de 90° del rumbo de entrada de la zona (`INBOUND_COG`).
  Rumbos medidos en los datos reales: Atlántico ~180° entrando y ~0° saliendo; Pacífico ~321°
  entrando y ~141° saliendo.
- Parado = SOG por debajo de `MOVING_SOG` (1 nudo): con el buque parado el COG es ruido.
- `on_position` sin tránsito abierto: si el buque **sale** (`False`), no abre nada y debe dejar
  la zona antes de poder abrir otro; si **entra** (`True`) o **no se sabe** (`None`), abre como
  hasta ahora. El rumbo solo decide la apertura: un tránsito ya abierto se completa al llegar a la
  zona opuesta, venga con el rumbo que venga.
- No cambia ningún umbral (timeout, polígonos) ni los eventos, la API o la base de datos.
"""

import itertools
import math
from datetime import UTC, datetime, timedelta

import pytest

from app.services.ais_parser import PositionUpdate
from app.services.transit_detector import (
    INBOUND_COG,
    MOVING_SOG,
    TransitCompleted,
    TransitDirection,
    TransitEvent,
    TransitStarted,
    VesselTrack,
    heading_into_canal,
    on_position,
)
from app.services.zones import ZoneId, zone_at
from tests.scripts_loader import load_script

replay_script = load_script("transit_replay")

MMSI = 353_123_000
T0 = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
TIMEOUT = timedelta(minutes=30)

IN_ATLANTIC = (-79.93, 9.40)
IN_PACIFIC = (-79.552, 8.91)
IN_THE_LAKE = (-79.90, 9.20)
SEA_NORTH_OF_ATLANTIC = (-79.919, 9.50)  # fuera de la zona, ya en el Caribe
SEA_SOUTH_OF_PACIFIC = (-79.40, 8.80)  # fuera de la zona, ya en la bahía de Panamá

INTO_ATLANTIC = 180.0
OUT_OF_ATLANTIC = 0.0
INTO_PACIFIC = 321.0
OUT_OF_PACIFIC = 141.0


def position(
    at: datetime,
    point: tuple[float, float],
    *,
    cog: float | None,
    sog: float | None = 10.0,
) -> PositionUpdate:
    lon, lat = point
    return PositionUpdate(
        mmsi=MMSI, received_at=at, lat=lat, lon=lon, sog=sog, cog=cog, heading=None, nav_status=0
    )


def bearing(start: tuple[float, float], end: tuple[float, float]) -> float:
    """Rumbo inicial de `start` a `end` en grados (0 = norte, 90 = este)."""
    lon1, lat1, lon2, lat2 = map(math.radians, (*start, *end))
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return math.degrees(math.atan2(x, y)) % 360


def sail(
    waypoints: list[tuple[float, float]], *, start: datetime, steps_per_leg: int = 12
) -> list[PositionUpdate]:
    """Posiciones cada 10 min por la ruta, cada una con el COG de su tramo."""
    positions = []
    at = start
    for (lon1, lat1), (lon2, lat2) in itertools.pairwise(waypoints):
        cog = bearing((lon1, lat1), (lon2, lat2))
        for step in range(steps_per_leg):
            fraction = step / steps_per_leg
            point = (lon1 + (lon2 - lon1) * fraction, lat1 + (lat2 - lat1) * fraction)
            positions.append(position(at, point, cog=cog))
            at += timedelta(minutes=10)
    positions.append(position(at, waypoints[-1], cog=cog))
    return positions


def feed(
    track: VesselTrack, positions: list[PositionUpdate]
) -> tuple[VesselTrack, list[TransitEvent]]:
    events: list[TransitEvent] = []
    for item in positions:
        track, produced = on_position(track, item, timeout=TIMEOUT)
        events.extend(produced)
    return track, events


def test_the_points_are_where_the_tests_assume() -> None:
    assert zone_at(*IN_ATLANTIC) == "atlantic_entrance"
    assert zone_at(*IN_PACIFIC) == "pacific_entrance"
    assert zone_at(*IN_THE_LAKE) is None
    assert zone_at(*SEA_NORTH_OF_ATLANTIC) is None
    assert zone_at(*SEA_SOUTH_OF_PACIFIC) is None
    # Las rutas sintéticas entran con un rumbo parecido al medido en los datos reales.
    assert abs(bearing(SEA_NORTH_OF_ATLANTIC, IN_ATLANTIC) - INTO_ATLANTIC) < 15
    assert abs(bearing(SEA_SOUTH_OF_PACIFIC, IN_PACIFIC) - INTO_PACIFIC) < 15


def test_the_inbound_bearings_match_the_real_data_and_moving_starts_at_one_knot() -> None:
    assert set(INBOUND_COG) == {"atlantic_entrance", "pacific_entrance"}
    assert abs(INBOUND_COG["atlantic_entrance"] - INTO_ATLANTIC) <= 10
    assert abs(INBOUND_COG["pacific_entrance"] - INTO_PACIFIC) <= 10
    assert MOVING_SOG == 1.0


# --- heading_into_canal: la regla, sin máquina de estados --------------------------------------


@pytest.mark.parametrize(
    ("zone", "cog", "expected"),
    [
        pytest.param("atlantic_entrance", INTO_ATLANTIC, True, id="atlantic-in"),
        pytest.param("atlantic_entrance", OUT_OF_ATLANTIC, False, id="atlantic-out"),
        pytest.param("atlantic_entrance", 359.0, False, id="atlantic-out-wraps-past-north"),
        pytest.param("atlantic_entrance", 120.0, True, id="atlantic-in-wide"),
        pytest.param("pacific_entrance", INTO_PACIFIC, True, id="pacific-in"),
        pytest.param("pacific_entrance", OUT_OF_PACIFIC, False, id="pacific-out"),
        pytest.param("pacific_entrance", 10.0, True, id="pacific-in-wraps-past-north"),
        pytest.param("pacific_entrance", 200.0, False, id="pacific-out-wide"),
    ],
)
def test_the_course_says_whether_the_vessel_goes_into_the_canal(
    zone: ZoneId, cog: float, expected: bool
) -> None:
    point = IN_ATLANTIC if zone == "atlantic_entrance" else IN_PACIFIC

    assert heading_into_canal(zone, position(T0, point, cog=cog)) is expected


@pytest.mark.parametrize(
    ("cog", "sog"),
    [
        pytest.param(None, 10.0, id="no-cog"),
        pytest.param(INTO_ATLANTIC, None, id="no-sog"),
        pytest.param(INTO_ATLANTIC, 0.0, id="stopped"),
        pytest.param(OUT_OF_ATLANTIC, 0.9, id="drifting-below-one-knot"),
        pytest.param(90.0, 10.0, id="abeam-east"),
        pytest.param(270.0, 10.0, id="abeam-west"),
    ],
)
def test_the_direction_is_unknown_without_a_reliable_course(
    cog: float | None, sog: float | None
) -> None:
    assert (
        heading_into_canal("atlantic_entrance", position(T0, IN_ATLANTIC, cog=cog, sog=sog)) is None
    )


def test_one_knot_already_counts_as_moving() -> None:
    at_the_limit = position(T0, IN_ATLANTIC, cog=OUT_OF_ATLANTIC, sog=MOVING_SOG)

    assert heading_into_canal("atlantic_entrance", at_the_limit) is False


# --- on_position: quien sale no abre un tránsito -----------------------------------------------


@pytest.mark.parametrize(
    ("point", "cog"),
    [
        pytest.param(IN_ATLANTIC, OUT_OF_ATLANTIC, id="atlantic"),
        pytest.param(IN_PACIFIC, OUT_OF_PACIFIC, id="pacific"),
    ],
)
def test_a_vessel_leaving_through_an_entrance_does_not_open_a_transit(
    point: tuple[float, float], cog: float
) -> None:
    track, events = on_position(
        VesselTrack(mmsi=MMSI), position(T0, point, cog=cog), timeout=TIMEOUT
    )

    assert events == []
    assert track.transit is None
    assert track.last_seen_at == T0


@pytest.mark.parametrize(
    ("point", "zone", "cog"),
    [
        pytest.param(IN_ATLANTIC, "atlantic_entrance", INTO_ATLANTIC, id="atlantic"),
        pytest.param(IN_PACIFIC, "pacific_entrance", INTO_PACIFIC, id="pacific"),
    ],
)
def test_a_vessel_entering_an_entrance_opens_a_transit(
    point: tuple[float, float], zone: ZoneId, cog: float
) -> None:
    _, events = on_position(VesselTrack(mmsi=MMSI), position(T0, point, cog=cog), timeout=TIMEOUT)

    assert events == [TransitStarted(mmsi=MMSI, origin=zone, entered_at=T0)]


@pytest.mark.parametrize(
    ("cog", "sog"),
    [
        pytest.param(None, 10.0, id="no-cog"),
        pytest.param(OUT_OF_ATLANTIC, 0.2, id="stopped"),
        pytest.param(90.0, 10.0, id="abeam"),
    ],
)
def test_without_a_reliable_course_a_transit_is_opened_as_before(
    cog: float | None, sog: float | None
) -> None:
    # Con la cobertura actual muchos buques dejan una sola posición en la zona: si no se sabe el
    # sentido se abre, como antes de este cambio, para no perder tránsitos reales.
    _, events = on_position(
        VesselTrack(mmsi=MMSI), position(T0, IN_ATLANTIC, cog=cog, sog=sog), timeout=TIMEOUT
    )

    assert [type(event) for event in events] == [TransitStarted]


def test_a_vessel_that_left_and_then_stops_in_the_zone_still_does_not_open_a_transit() -> None:
    # Sale hacia el mar, pero se queda parado (sin rumbo fiable) antes de salir del polígono. Sus
    # posiciones paradas no pueden abrir un tránsito: tiene que salir de la zona primero.
    leaving = position(T0, IN_ATLANTIC, cog=OUT_OF_ATLANTIC)
    stopped = [
        position(T0 + timedelta(minutes=10 * n), IN_ATLANTIC, cog=None, sog=0.0) for n in (1, 2, 3)
    ]

    track, events = feed(VesselTrack(mmsi=MMSI), [leaving, *stopped])

    assert events == []
    assert track.transit is None


def test_a_vessel_that_left_can_open_a_transit_when_it_comes_back_in() -> None:
    leaving = position(T0, IN_ATLANTIC, cog=OUT_OF_ATLANTIC)
    at_sea = position(T0 + timedelta(hours=1), SEA_NORTH_OF_ATLANTIC, cog=OUT_OF_ATLANTIC)
    back_in = position(T0 + timedelta(days=2), IN_ATLANTIC, cog=INTO_ATLANTIC)

    _, events = feed(VesselTrack(mmsi=MMSI), [leaving, at_sea, back_in])

    assert events == [
        TransitStarted(mmsi=MMSI, origin="atlantic_entrance", entered_at=T0 + timedelta(days=2))
    ]


@pytest.mark.parametrize(
    "route",
    [
        pytest.param([IN_THE_LAKE, IN_ATLANTIC, SEA_NORTH_OF_ATLANTIC], id="out-to-the-caribbean"),
        pytest.param([IN_THE_LAKE, IN_PACIFIC, SEA_SOUTH_OF_PACIFIC], id="out-to-the-pacific"),
    ],
)
def test_a_vessel_coming_out_of_the_canal_crosses_the_entrance_without_any_event(
    route: list[tuple[float, float]],
) -> None:
    # El caso de los datos reales: no lo vimos entrar (sin cobertura dentro del Canal) y lo vemos
    # salir. Antes abría un tránsito en sentido contrario que acababa abortado por timeout.
    track, events = feed(VesselTrack(mmsi=MMSI), sail(route, start=T0))

    assert events == []
    assert track.transit is None


@pytest.mark.parametrize(
    ("route", "direction"),
    [
        pytest.param(
            [SEA_NORTH_OF_ATLANTIC, IN_ATLANTIC, IN_THE_LAKE, IN_PACIFIC, SEA_SOUTH_OF_PACIFIC],
            TransitDirection.SOUTHBOUND,
            id="southbound",
        ),
        pytest.param(
            [SEA_SOUTH_OF_PACIFIC, IN_PACIFIC, IN_THE_LAKE, IN_ATLANTIC, SEA_NORTH_OF_ATLANTIC],
            TransitDirection.NORTHBOUND,
            id="northbound",
        ),
    ],
)
def test_a_full_crossing_with_real_courses_completes_once(
    route: list[tuple[float, float]], direction: TransitDirection
) -> None:
    # Al llegar a la zona opuesta el buque ya va hacia el mar (rumbo de salida): eso no impide
    # completar. El rumbo solo decide la apertura.
    track, events = feed(VesselTrack(mmsi=MMSI), sail(route, start=T0))

    started, completed = events
    assert isinstance(started, TransitStarted)
    assert isinstance(completed, TransitCompleted)
    assert completed.direction is direction
    assert track.transit is None


def test_an_open_transit_is_not_closed_by_a_course_pointing_to_sea() -> None:
    # Fuera del alcance de #121: abierto sin rumbo fiable (parado en la zona) y luego navegando
    # hacia el mar sin salir del polígono. Sigue abierto; lo cerrará el timeout o la reversa.
    # Cerrarlo pediría un motivo de aborto nuevo (cambio de API y de base de datos).
    stopped = position(T0, IN_ATLANTIC, cog=None, sog=0.0)
    leaving = position(T0 + timedelta(minutes=10), IN_ATLANTIC, cog=OUT_OF_ATLANTIC)

    track, events = feed(VesselTrack(mmsi=MMSI), [stopped, leaving])

    assert [type(event) for event in events] == [TransitStarted]
    assert track.transit is not None


# --- El replay tiene que leer el rumbo y la velocidad ------------------------------------------


def collector_line(**changes: object) -> dict[str, object]:
    record: dict[str, object] = {
        "kind": "position",
        "mmsi": MMSI,
        "received_at": T0.isoformat(),
        "lat": IN_ATLANTIC[1],
        "lon": IN_ATLANTIC[0],
        "sog": 7.3,
        "cog": 181.0,
        "heading": 180,
        "nav_status": 0,
    }
    return record | changes


def test_the_replay_keeps_the_course_and_speed_of_each_position() -> None:
    parsed = replay_script._position(collector_line())

    assert parsed is not None
    assert parsed.sog == 7.3
    assert parsed.cog == 181.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("cog", 360.0, id="cog-not-available"),
        pytest.param("cog", -1.0, id="cog-negative"),
        pytest.param("cog", 400.0, id="cog-too-big"),
        pytest.param("cog", "180", id="cog-not-a-number"),
        pytest.param("cog", True, id="cog-bool"),
        pytest.param("cog", None, id="cog-missing"),
        pytest.param("sog", -0.1, id="sog-negative"),
        pytest.param("sog", 102.3, id="sog-not-available"),
        pytest.param("sog", "fast", id="sog-not-a-number"),
        pytest.param("sog", None, id="sog-missing"),
        # `json.loads` acepta NaN e Infinity aunque no sean JSON estándar.
        pytest.param("cog", math.nan, id="cog-nan"),
        pytest.param("sog", math.inf, id="sog-infinity"),
        pytest.param("sog", -math.inf, id="sog-minus-infinity"),
    ],
)
def test_an_unusable_course_or_speed_is_dropped_but_the_position_is_kept(
    field: str, value: object
) -> None:
    parsed = replay_script._position(collector_line(**{field: value}))

    assert parsed is not None
    assert getattr(parsed, field) is None


def test_the_replay_of_a_vessel_coming_out_of_the_canal_has_no_transits() -> None:
    positions = sail([IN_THE_LAKE, IN_ATLANTIC, SEA_NORTH_OF_ATLANTIC], start=T0)

    result = replay_script.replay(positions, timeout=TIMEOUT)

    assert result.transits == []
