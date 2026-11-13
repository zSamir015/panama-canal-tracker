"""Zonas del Canal (tarea 5.1): geometría válida y copia del frontend al día."""

import itertools
import json
from pathlib import Path

import pytest

from app.services.zones import ZONES, Coordinate, Zone, zones_geojson
from tests.scripts_loader import load_script

export_zones = load_script("export_zones")

# Caja de trabajo del proyecto (AGENTS.md §1): lat 8.4 a 9.7, lon -80.2 a -79.2.
MIN_LON, MAX_LON = -80.2, -79.2
MIN_LAT, MAX_LAT = 8.4, 9.7


def signed_area(ring: tuple[Coordinate, ...]) -> float:
    """Fórmula del cordón: positiva si el anillo va en sentido antihorario."""
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in itertools.pairwise(ring)) / 2


def cross(o: Coordinate, a: Coordinate, b: Coordinate) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def segments_intersect(p1: Coordinate, p2: Coordinate, p3: Coordinate, p4: Coordinate) -> bool:
    """Cruce propio de dos segmentos (sin contar que se toquen en un extremo compartido)."""
    d1, d2 = cross(p3, p4, p1), cross(p3, p4, p2)
    d3, d4 = cross(p1, p2, p3), cross(p1, p2, p4)
    return d1 * d2 < 0 and d3 * d4 < 0


@pytest.mark.parametrize("zone", ZONES, ids=lambda zone: zone.id)
class TestEachZone:
    def test_ring_is_closed_with_enough_points(self, zone: Zone) -> None:
        assert len(zone.ring) >= 4
        assert zone.ring[0] == zone.ring[-1]

    def test_coordinates_are_lon_lat_inside_the_canal_area(self, zone: Zone) -> None:
        # Con lat y lon invertidas (el error clásico con AISStream) esto falla.
        for lon, lat in zone.ring:
            assert MIN_LON <= lon <= MAX_LON
            assert MIN_LAT <= lat <= MAX_LAT

    def test_ring_is_counterclockwise(self, zone: Zone) -> None:
        assert signed_area(zone.ring) > 0

    def test_ring_does_not_cross_itself(self, zone: Zone) -> None:
        edges = list(itertools.pairwise(zone.ring))
        for (i, (a1, a2)), (j, (b1, b2)) in itertools.combinations(enumerate(edges), 2):
            if j == i + 1 or (i == 0 and j == len(edges) - 1):
                continue  # aristas contiguas: comparten un vértice
            assert not segments_intersect(a1, a2, b1, b2)


def test_zone_ids_are_unique() -> None:
    ids = [zone.id for zone in ZONES]
    assert len(ids) == len(set(ids)) == 2


def test_atlantic_entrance_is_entirely_north_of_the_pacific_one() -> None:
    # Dirección de la ACP: southbound = Atlántico a Pacífico. Sin solape entre las dos zonas.
    atlantic, pacific = ZONES
    assert min(lat for _, lat in atlantic.ring) > max(lat for _, lat in pacific.ring)


def test_geojson_is_a_feature_collection_of_polygons() -> None:
    collection = zones_geojson()
    assert collection["type"] == "FeatureCollection"
    assert [feature["properties"]["id"] for feature in collection["features"]] == [
        zone.id for zone in ZONES
    ]
    for feature in collection["features"]:
        assert feature["geometry"]["type"] == "Polygon"
        assert len(feature["geometry"]["coordinates"]) == 1  # solo anillo exterior


def test_frontend_copy_is_up_to_date() -> None:
    """`web/src/map/canalZones.json` sale de `zones.py`: si se cambia uno, hay que exportar."""
    exported = export_zones.OUTPUT.read_text(encoding="utf-8")
    assert exported == export_zones.render()
    assert json.loads(exported) == json.loads(json.dumps(zones_geojson()))


def test_export_check_flags_a_stale_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stale = tmp_path / "canalZones.json"
    stale.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(export_zones, "OUTPUT", stale)
    assert export_zones.main(["--check"]) == 1
    assert export_zones.main([]) == 0  # la escritura lo deja al día
    assert export_zones.main(["--check"]) == 0
