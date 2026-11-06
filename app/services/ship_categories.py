"""Categorías de buque a partir del tipo AIS (tarea 6.4).

Las mismas que usa el mapa (`web/src/map/vesselGeoJson.ts`, `shipCategory`): si se cambia una
regla, hay que cambiarla en los dos. Una sola lista de rangos alimenta la función de Python y la
expresión SQL de las estadísticas, y un test comprueba que dan lo mismo para los 100 códigos.
"""

from typing import Literal

ShipCategory = Literal[
    "cargo", "tanker", "passenger", "tug", "fishing", "pleasure", "other", "unknown"
]

# (categoría, rangos inclusivos de tipo AIS). Lo que no está aquí es `other`; sin tipo, `unknown`.
CATEGORY_RANGES: tuple[tuple[ShipCategory, tuple[tuple[int, int], ...]], ...] = (
    ("cargo", ((70, 79),)),
    ("tanker", ((80, 89),)),
    ("passenger", ((60, 69),)),
    # 31 y 32: remolcando; 50: práctico; 52: remolcador (en el Canal van juntos).
    ("tug", ((31, 32), (50, 50), (52, 52))),
    ("fishing", ((30, 30),)),
    ("pleasure", ((36, 37),)),
)

CATEGORIES: tuple[ShipCategory, ...] = (
    *(category for category, _ in CATEGORY_RANGES),
    "other",
    "unknown",
)


def ship_category(ship_type: int | None) -> ShipCategory:
    if ship_type is None:
        return "unknown"
    for category, ranges in CATEGORY_RANGES:
        if any(low <= ship_type <= high for low, high in ranges):
            return category
    return "other"
