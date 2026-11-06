"""`zone_at(lon, lat)`: en qué zona de entrada está un punto (tarea 5.2).

Escritos antes que la función (TDD): fallan con `ImportError` hasta que exista
`app.services.zones.zone_at`. Los puntos se eligieron sobre los polígonos de `zones.py`.
"""

import pytest

from app.services.zones import ZoneId, zone_at

ATLANTIC: ZoneId = "atlantic_entrance"
PACIFIC: ZoneId = "pacific_entrance"


@pytest.mark.parametrize(
    ("lon", "lat", "expected"),
    [
        pytest.param(-79.93, 9.40, ATLANTIC, id="atlantic-center"),
        pytest.param(-79.552, 8.91, PACIFIC, id="pacific-center"),
    ],
)
def test_a_point_inside_a_zone_returns_that_zone(lon: float, lat: float, expected: ZoneId) -> None:
    assert zone_at(lon, lat) == expected


@pytest.mark.parametrize(
    ("lon", "lat"),
    [
        pytest.param(-79.70, 9.30, id="caribbean-off-portobelo"),
        pytest.param(-79.90, 9.20, id="gatun-lake-between-the-zones"),
        pytest.param(-79.40, 8.80, id="bay-of-panama-far-from-the-entrance"),
    ],
)
def test_a_point_outside_every_zone_returns_none(lon: float, lat: float) -> None:
    assert zone_at(lon, lat) is None


def test_arguments_are_lon_then_lat_not_the_other_way_round() -> None:
    # El error clásico: AISStream da [lat, lon] y GeoJSON [lon, lat]. Con el orden invertido,
    # un punto que está dentro del Atlántico no puede seguir contando como dentro.
    assert zone_at(-79.93, 9.40) == ATLANTIC
    assert zone_at(9.40, -79.93) is None


def test_a_vertex_latitude_counts_the_crossing_once() -> None:
    # 9.375 coincide con la latitud de un vértice del Atlántico; el punto sigue siendo interior.
    assert zone_at(-79.93, 9.375) == ATLANTIC


@pytest.mark.parametrize(
    ("lon", "lat", "expected"),
    [
        pytest.param(-79.915, 9.40, ATLANTIC, id="just-inside-the-east-edge"),
        pytest.param(-79.905, 9.40, None, id="just-outside-the-east-edge"),
        pytest.param(-79.93, 9.425, None, id="just-north-of-the-top-edge"),
        pytest.param(-79.93, 9.355, None, id="just-south-of-the-bottom-edge"),
    ],
)
def test_points_a_few_hundred_meters_from_an_edge(
    lon: float, lat: float, expected: ZoneId | None
) -> None:
    assert zone_at(lon, lat) == expected


@pytest.mark.parametrize(
    ("lon", "lat", "expected"),
    [
        pytest.param(-79.5575, 8.925, PACIFIC, id="right-of-the-notch-is-inside"),
        pytest.param(-79.560, 8.925, None, id="left-of-the-notch-is-outside"),
        pytest.param(-79.5575, 8.902, None, id="lower-left-concavity-is-outside"),
    ],
)
def test_the_pacific_polygon_is_not_convex(lon: float, lat: float, expected: ZoneId | None) -> None:
    # Su borde oeste tiene un quiebre hacia dentro. Si solo se comprueba la caja que lo envuelve
    # (min/max de lon y lat), estos puntos saldrían todos "dentro".
    assert zone_at(lon, lat) == expected
