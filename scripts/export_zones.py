"""Exporta las zonas del Canal a GeoJSON para el frontend (tarea 5.1).

`app/services/zones.py` es la fuente de verdad; el mapa lee esta copia estática, que también
usa la demo (que no tiene backend). Un test comprueba que la copia no se desfasa.

    python scripts/export_zones.py            # escribe web/src/map/canalZones.json
    python scripts/export_zones.py --check    # falla si el archivo no está al día
"""

import argparse
import json
import sys
from pathlib import Path

from app.services.zones import zones_geojson

OUTPUT = Path(__file__).resolve().parent.parent / "web" / "src" / "map" / "canalZones.json"


def render() -> str:
    """El JSON exacto que debe tener el archivo (con salto de línea final)."""
    return json.dumps(zones_geojson(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Exporta las zonas del Canal a GeoJSON.")
    parser.add_argument("--check", action="store_true", help="solo comprueba, no escribe")
    args = parser.parse_args(argv)

    expected = render()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != expected:
            print(f"{OUTPUT} está desfasado: ejecuta python scripts/export_zones.py")
            return 1
        return 0
    OUTPUT.write_text(expected, encoding="utf-8")
    print(f"Escrito {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
