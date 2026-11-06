"""Zonas geográficas del Canal de Panamá (tarea 5.1).

Fuente única de los polígonos de entrada: la detección de tránsitos (5.2 y 5.3) decide con ellos
cuándo un buque entra o sale del Canal, y el mapa los dibuja a partir de una copia exportada
(`scripts/export_zones.py` genera `web/src/map/canalZones.json`; un test comprueba que no se
desfasan).

Los polígonos son **aproximados**: se trazaron a mano sobre los tiles de OpenFreeMap, sin una
fuente oficial de la ACP. Cubren el agua de la aproximación a cada entrada y no tocan tierra.
Su precisión real se mide en la tarea 5.7 con datos reales; si hay que moverlos, se cambian aquí
y se vuelve a exportar.

Orden de coordenadas: GeoJSON y PostGIS usan `[lon, lat]` (en AISStream es `[lat, lon]`).
Los anillos son cerrados y van en sentido antihorario, como pide el RFC 7946.
"""

from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Literal

ZoneId = Literal["atlantic_entrance", "pacific_entrance"]

Coordinate = tuple[float, float]  # (lon, lat)


@dataclass(frozen=True)
class Zone:
    id: ZoneId
    name: str
    ring: tuple[Coordinate, ...]

    def to_feature(self) -> dict[str, Any]:
        return {
            "type": "Feature",
            "properties": {"id": self.id, "name": self.name},
            "geometry": {"type": "Polygon", "coordinates": [[list(point) for point in self.ring]]},
        }


# Boca de la bahía de Limón, al norte de Colón y de la punta de Fort Sherman.
ATLANTIC_ENTRANCE = Zone(
    id="atlantic_entrance",
    name="Entrada Atlántico",
    ring=(
        (-79.955, 9.42),
        (-79.946, 9.378),
        (-79.94, 9.36),
        (-79.915, 9.36),
        (-79.91, 9.375),
        (-79.91, 9.42),
        (-79.955, 9.42),
    ),
)

# Aproximación a Balboa, al sur del Puente de las Américas y al este de Playa Bonita.
PACIFIC_ENTRANCE = Zone(
    id="pacific_entrance",
    name="Entrada Pacífico",
    ring=(
        (-79.562, 8.936),
        (-79.556, 8.915),
        (-79.558, 8.89),
        (-79.547, 8.89),
        (-79.547, 8.926),
        (-79.553, 8.936),
        (-79.562, 8.936),
    ),
)

ZONES: tuple[Zone, ...] = (ATLANTIC_ENTRANCE, PACIFIC_ENTRANCE)


def zone_at(lon: float, lat: float) -> ZoneId | None:
    """Devuelve la zona que contiene el punto, usando ray casting.

    Los puntos exactamente sobre un borde o un vértice no forman parte del contrato de esta
    función. El criterio usado por el algoritmo puede considerarlos dentro o fuera según la
    arista que se evalúe.
    """
    for zone in ZONES:
        inside = False
        # Los anillos están cerrados; así pairwise incluye también la arista del último vértice
        # al primero. Usar > en ambos lados cuenta un vértice una sola vez y evita aristas
        # horizontales, que harían cero el denominador del cruce.
        for (edge_lon_1, edge_lat_1), (edge_lon_2, edge_lat_2) in pairwise(zone.ring):
            crosses_latitude = (edge_lat_1 > lat) != (edge_lat_2 > lat)
            if not crosses_latitude:
                continue

            crossing_lon = edge_lon_1 + (lat - edge_lat_1) * (edge_lon_2 - edge_lon_1) / (
                edge_lat_2 - edge_lat_1
            )
            if lon < crossing_lon:
                inside = not inside

        if inside:
            return zone.id

    return None


def zones_geojson() -> dict[str, Any]:
    """Las zonas como un `FeatureCollection` GeoJSON."""
    return {"type": "FeatureCollection", "features": [zone.to_feature() for zone in ZONES]}
