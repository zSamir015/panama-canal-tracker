"""Mide la cobertura de AISStream en el área del Canal (tarea 3.8).

Abre una conexión con la misma suscripción que el worker durante unos minutos, cuenta lo que
llega y añade una línea JSON a un fichero local. Ejecutado varias veces durante unos días, dice si
la cobertura de los receptores voluntarios de AISStream sirve para el mapa en vivo.

    python scripts/ais_coverage.py --minutes 2 --output data/coverage.jsonl

Usa la key de `.env` (`AISSTREAM_API_KEY`) y nunca la escribe. Es una conexión más con la misma
key: AISStream admite 3 por cuenta, pero mejor no ejecutarlo mientras corre el worker.
No guarda mensajes, solo recuentos.
"""

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from websockets.asyncio.client import connect

from app.core.config import get_settings
from app.services.ais_parser import AisMessageRejected, PositionUpdate, VesselStatic, parse_message
from app.workers.ais_consumer import CANAL_BOUNDING_BOXES, MAX_FRAME_BYTES, MESSAGE_TYPES

MAX_MINUTES = 30


@dataclass
class CoverageSample:
    started_at: str
    seconds: float
    confirmed: bool = False
    positions: int = 0
    statics: int = 0
    rejected: dict[str, int] = field(default_factory=dict)
    vessels: int = 0
    # Posiciones dentro de la bbox del Canal (AISStream puede entregar algo de los bordes).
    positions_in_canal: int = 0


def _in_canal(lat: float, lon: float) -> bool:
    return any(
        min(a[0], b[0]) <= lat <= max(a[0], b[0]) and min(a[1], b[1]) <= lon <= max(a[1], b[1])
        for a, b in CANAL_BOUNDING_BOXES
    )


def summarize(
    frames: Iterable[bytes | str], *, started_at: datetime, seconds: float
) -> CoverageSample:
    """Cuenta lo recibido. Pura: no toca la red, se prueba con frames de ejemplo."""
    sample = CoverageSample(started_at=started_at.isoformat(), seconds=round(seconds, 1))
    rejected: Counter[str] = Counter()
    vessels: set[int] = set()
    for frame in frames:
        try:
            record = parse_message(frame, received_at=started_at)
        except AisMessageRejected as rejection:
            rejected[rejection.reason] += 1
            continue
        if isinstance(record, PositionUpdate):
            sample.positions += 1
            vessels.add(record.mmsi)
            if _in_canal(record.lat, record.lon):
                sample.positions_in_canal += 1
        elif isinstance(record, VesselStatic):
            sample.statics += 1
            vessels.add(record.mmsi)
        elif '"SubscriptionConfirmation"' in (frame if isinstance(frame, str) else frame.decode()):
            sample.confirmed = True
    sample.rejected = dict(rejected)
    sample.vessels = len(vessels)
    return sample


async def collect(url: str, api_key: str, seconds: float) -> list[bytes | str]:
    frames: list[bytes | str] = []
    subscription = {
        "APIKey": api_key,
        "BoundingBoxes": [[list(corner) for corner in box] for box in CANAL_BOUNDING_BOXES],
        "FilterMessageTypes": list(MESSAGE_TYPES),
    }
    async with connect(url, max_size=MAX_FRAME_BYTES, compression="deflate") as connection:
        await connection.send(json.dumps(subscription))
        deadline = time.monotonic() + seconds
        while (left := deadline - time.monotonic()) > 0:
            try:
                frames.append(await asyncio.wait_for(connection.recv(), timeout=left))
            except TimeoutError:
                break
    return frames


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mide la cobertura de AISStream en el Canal.")
    parser.add_argument("--minutes", type=float, default=2.0, help=f"de 0 a {MAX_MINUTES}")
    parser.add_argument("--output", type=Path, help="fichero JSON Lines al que añadir la muestra")
    args = parser.parse_args(argv)
    if not 0 < args.minutes <= MAX_MINUTES:
        parser.error(f"--minutes debe estar entre 0 y {MAX_MINUTES}")

    settings = get_settings()
    key = settings.aisstream_api_key
    if key is None or not key.get_secret_value().strip():
        parser.error("AISSTREAM_API_KEY no está definida en .env")

    started_at = datetime.now(UTC)
    seconds = args.minutes * 60
    frames = asyncio.run(collect(settings.aisstream_url, key.get_secret_value(), seconds))
    line = json.dumps(asdict(summarize(frames, started_at=started_at, seconds=seconds)))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    sys.stdout.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
