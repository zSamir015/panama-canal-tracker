"""Fondeaderos del Canal de Panamá (tarea 6.1).

Donde los buques esperan turno antes de entrar: al norte de la entrada del Atlántico (Limón Bay,
frente a Cristóbal) y al sur de la del Pacífico (Bahía de Panamá). La detección de esperas
(`app/services/anchorage_detector.py`) decide con estos polígonos si un buque está fondeado.

Como las entradas (`app/services/zones.py`), los polígonos son **aproximados**: rectángulos
trazados a mano sobre agua abierta, sin una fuente oficial de la ACP, que no tocan tierra ni las
zonas de entrada. Los fondeaderos reales son más grandes y de forma irregular; con datos reales
(tarea 5.7) se comprueba cuántos buques parados caen fuera. Si hay que moverlos, se cambian aquí.

Orden de coordenadas: `[lon, lat]`, como GeoJSON y PostGIS (en AISStream es `[lat, lon]`). Los
anillos son cerrados y van en sentido antihorario.
"""

from dataclasses import dataclass
from typing import Literal

from app.services.zones import Coordinate, point_in_ring

AnchorageId = Literal["atlantic", "pacific"]


@dataclass(frozen=True)
class Anchorage:
    id: AnchorageId
    name: str
    ring: tuple[Coordinate, ...]


# Mar abierto al norte-noreste del rompeolas de Cristóbal, fuera de la entrada del Atlántico.
ATLANTIC_ANCHORAGE = Anchorage(
    id="atlantic",
    name="Fondeadero Atlántico",
    ring=(
        (-79.90, 9.41),
        (-79.80, 9.41),
        (-79.80, 9.50),
        (-79.90, 9.50),
        (-79.90, 9.41),
    ),
)

# Bahía de Panamá, al sur de la entrada del Pacífico y al norte de la isla Taboga.
PACIFIC_ANCHORAGE = Anchorage(
    id="pacific",
    name="Fondeadero Pacífico",
    ring=(
        (-79.57, 8.80),
        (-79.47, 8.80),
        (-79.47, 8.885),
        (-79.57, 8.885),
        (-79.57, 8.80),
    ),
)

ANCHORAGES: tuple[Anchorage, ...] = (ATLANTIC_ANCHORAGE, PACIFIC_ANCHORAGE)


def anchorage_at(lon: float, lat: float) -> AnchorageId | None:
    """El fondeadero que contiene el punto, o `None`."""
    for anchorage in ANCHORAGES:
        if point_in_ring(lon, lat, anchorage.ring):
            return anchorage.id
    return None
