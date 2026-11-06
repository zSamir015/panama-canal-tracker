"""Recolector de posiciones AIS reales del Canal (ADR-0012).

Se conecta a AISStream con la misma suscripción que el worker y escribe cada posición y cada
dato estático válido en un fichero JSON Lines, una línea por mensaje. No usa base de datos ni
Redis: lo ejecuta el workflow `collect-ais.yml` en GitHub Actions para acumular días de datos
reales sin una máquina encendida, y el replay de la tarea 5.5 los lee después.

    python scripts/ais_collect.py --minutes 340 --output ais.jsonl

Usa la key de `AISSTREAM_API_KEY` y nunca la escribe, ni en el fichero ni en la salida. Si la
conexión se cae, reconecta con espera creciente hasta que se acaba el tiempo. Cuenta como una
conexión más con la misma key: no ejecutarlo a la vez que el worker (AGENTS.md §2.6, ADR-0009).

De cada mensaje solo guarda lo que necesita el detector de tránsitos y su validación; no guarda
nombres ni destinos de los buques.
"""

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from app.core.config import get_settings
from app.services.ais_parser import AisMessageRejected, PositionUpdate, VesselStatic, parse_message
from app.workers.ais_consumer import CANAL_BOUNDING_BOXES, MAX_FRAME_BYTES, MESSAGE_TYPES

# Un job de GitHub Actions dura como mucho 360 min: se deja margen para instalar y subir.
MAX_MINUTES = 350
RECONNECT_MIN_SECONDS = 2.0
RECONNECT_MAX_SECONDS = 60.0
# Una conexión que aguanta esto se considera sana: tras caerse, el siguiente reintento es rápido.
STABLE_CONNECTION_SECONDS = 60.0

Frame = bytes | str


def to_record(parsed: PositionUpdate | VesselStatic | None) -> dict[str, Any] | None:
    """Lo que se guarda de un mensaje ya parseado (pura). `None` si no hay nada que guardar."""
    if isinstance(parsed, PositionUpdate):
        return {
            "kind": "position",
            "mmsi": parsed.mmsi,
            "received_at": parsed.received_at.isoformat(),
            "lat": parsed.lat,
            "lon": parsed.lon,
            "sog": parsed.sog,
            "cog": parsed.cog,
            "heading": parsed.heading,
            "nav_status": parsed.nav_status,
        }
    if isinstance(parsed, VesselStatic):
        return {
            "kind": "static",
            "mmsi": parsed.mmsi,
            "received_at": parsed.received_at.isoformat() if parsed.received_at else None,
            "ship_type": parsed.ship_type,
            "length_m": parsed.length_m,
            "beam_m": parsed.beam_m,
        }
    return None


class Recorder:
    """Convierte frames en líneas JSON y lleva la cuenta. Sin red: se prueba con ejemplos."""

    def __init__(self, write: Callable[[str], None]) -> None:
        self._write = write
        self.counts: Counter[str] = Counter()

    def handle(self, frame: Frame, *, received_at: datetime) -> None:
        try:
            record = to_record(parse_message(frame, received_at=received_at))
        except AisMessageRejected as rejection:
            self.counts[f"rejected:{rejection.reason}"] += 1
            return
        if record is None:
            return
        self.counts[str(record["kind"])] += 1
        self._write(json.dumps(record, separators=(",", ":")) + "\n")


def subscription_message(api_key: str) -> str:
    return json.dumps(
        {
            "APIKey": api_key,
            "BoundingBoxes": [[list(corner) for corner in box] for box in CANAL_BOUNDING_BOXES],
            "FilterMessageTypes": list(MESSAGE_TYPES),
        }
    )


async def collect(
    url: str,
    api_key: str,
    seconds: float,
    recorder: Recorder,
    *,
    reconnect_min: float = RECONNECT_MIN_SECONDS,
    reconnect_max: float = RECONNECT_MAX_SECONDS,
    stable_after: float = STABLE_CONNECTION_SECONDS,
) -> int:
    """Recoge durante `seconds`, reconectando si se cae. Devuelve cuántas conexiones se abrieron.

    La espera entre reintentos crece al doble cada vez y solo vuelve al mínimo si la conexión
    anterior aguantó `stable_after` segundos: un servidor que acepta y cierra al instante (key
    rechazada, límite de conexiones) no recibe una avalancha de reconexiones.
    """
    deadline = time.monotonic() + seconds
    delay = reconnect_min
    connections = 0
    while time.monotonic() < deadline:
        opened_at: float | None = None
        try:
            # `close_timeout` corto: al acabar el plazo no se espera 10 s a que el servidor cierre.
            async with connect(
                url, max_size=MAX_FRAME_BYTES, compression="deflate", close_timeout=2
            ) as connection:
                await connection.send(subscription_message(api_key))
                connections += 1
                opened_at = time.monotonic()
                while (left := deadline - time.monotonic()) > 0:
                    try:
                        frame = await asyncio.wait_for(connection.recv(), timeout=left)
                    except TimeoutError:
                        return connections
                    recorder.handle(frame, received_at=datetime.now(UTC))
        except (WebSocketException, OSError) as error:
            if opened_at is not None and time.monotonic() - opened_at >= stable_after:
                delay = reconnect_min
            # Solo el tipo: el mensaje de un error de conexión podría traer la URL o cabeceras.
            sys.stderr.write(
                f"Conexión perdida ({type(error).__name__}); reintento en {delay:.1f} s\n"
            )
        left = deadline - time.monotonic()
        if left <= 0:
            break
        await asyncio.sleep(min(delay, left))
        delay = min(delay * 2, reconnect_max)
    return connections


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recolecta posiciones AIS reales del Canal.")
    parser.add_argument("--minutes", type=float, required=True, help=f"de 0 a {MAX_MINUTES}")
    parser.add_argument("--output", type=Path, required=True, help="fichero JSON Lines (se añade)")
    args = parser.parse_args(argv)
    if not 0 < args.minutes <= MAX_MINUTES:
        parser.error(f"--minutes debe estar entre 0 y {MAX_MINUTES}")

    settings = get_settings()
    key = settings.aisstream_api_key
    if key is None or not key.get_secret_value().strip():
        parser.error("AISSTREAM_API_KEY no está definida")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Línea a línea: si el job se corta, lo recogido hasta ese momento ya está en el fichero.
    with args.output.open("a", encoding="utf-8", buffering=1) as handle:
        recorder = Recorder(handle.write)
        connections = asyncio.run(
            collect(settings.aisstream_url, key.get_secret_value(), args.minutes * 60, recorder)
        )
    summary = {"minutes": args.minutes, "connections": connections, **dict(recorder.counts)}
    sys.stdout.write(json.dumps(summary) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
