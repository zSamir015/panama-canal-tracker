"""Fondeaderos (tarea 6.1): geometría válida, sin solapes y `anchorage_at`."""

import itertools

import pytest

from app.services.anchorages import ANCHORAGES, Anchorage, anchorage_at
from app.services.zones import ZONES, Coordinate, point_in_ring, zone_at
from tests.test_zones import (
    MAX_LAT,
    MAX_LON,
    MIN_LAT,
    MIN_LON,
    segments_intersect,
    signed_area,
)

IN_ATLANTIC_ANCHORAGE = (-79.85, 9.45)
IN_PACIFIC_ANCHORAGE = (-79.52, 8.84)
OPEN_SEA = (-79.70, 9.60)


@pytest.mark.parametrize("anchorage", ANCHORAGES, ids=lambda anchorage: anchorage.id)
class TestEachAnchorage:
    def test_ring_is_closed_with_enough_points(self, anchorage: Anchorage) -> None:
        assert len(anchorage.ring) >= 4
        assert anchorage.ring[0] == anchorage.ring[-1]

    def test_coordinates_are_lon_lat_inside_the_canal_area(self, anchorage: Anchorage) -> None:
        for lon, lat in anchorage.ring:
            assert MIN_LON <= lon <= MAX_LON
            assert MIN_LAT <= lat <= MAX_LAT

    def test_ring_is_counterclockwise(self, anchorage: Anchorage) -> None:
        assert signed_area(anchorage.ring) > 0

    def test_ring_does_not_cross_itself(self, anchorage: Anchorage) -> None:
        edges = list(itertools.pairwise(anchorage.ring))
        for (i, (a1, a2)), (j, (b1, b2)) in itertools.combinations(enumerate(edges), 2):
            if j == i + 1 or (i == 0 and j == len(edges) - 1):
                continue
            assert not segments_intersect(a1, a2, b1, b2)

    def test_does_not_overlap_an_entrance_zone(self, anchorage: Anchorage) -> None:
        # Un buque no puede estar a la vez esperando turno y entrando: ningún vértice de un
        # polígono dentro del otro, ni el centro del fondeadero dentro de una entrada.
        for zone in ZONES:
            assert not any(point_in_ring(lon, lat, zone.ring) for lon, lat in anchorage.ring)
            assert not any(point_in_ring(lon, lat, anchorage.ring) for lon, lat in zone.ring)
            lons, lats = zip(*anchorage.ring, strict=True)
            assert zone_at(sum(lons) / len(lons), sum(lats) / len(lats)) is None


def test_ids_are_unique() -> None:
    assert [anchorage.id for anchorage in ANCHORAGES] == ["atlantic", "pacific"]


def test_the_atlantic_anchorage_is_north_of_the_pacific_one() -> None:
    atlantic, pacific = ANCHORAGES
    assert min(lat for _, lat in atlantic.ring) > max(lat for _, lat in pacific.ring)


@pytest.mark.parametrize(
    ("point", "expected"),
    [
        pytest.param(IN_ATLANTIC_ANCHORAGE, "atlantic", id="atlantic"),
        pytest.param(IN_PACIFIC_ANCHORAGE, "pacific", id="pacific"),
        pytest.param(OPEN_SEA, None, id="open sea"),
        pytest.param((-79.93, 9.39), None, id="atlantic entrance"),
        pytest.param((-79.552, 8.91), None, id="pacific entrance"),
        pytest.param((-79.75, 9.15), None, id="gatun lake"),
    ],
)
def test_anchorage_at(point: Coordinate, expected: str | None) -> None:
    assert anchorage_at(*point) == expected


def test_swapped_lat_lon_matches_nothing() -> None:
    # El error clásico con AISStream: [lat, lon] donde van [lon, lat].
    lon, lat = IN_ATLANTIC_ANCHORAGE
    assert anchorage_at(lat, lon) is None
