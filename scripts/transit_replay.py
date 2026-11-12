"""Replay de posiciones AIS grabadas por el detector de tránsitos (tarea 5.5).

Lee los ficheros JSON Lines del recolector (`scripts/ais_collect.py`, ADR-0012; formato en
`docs/AIS_COLLECTOR.md`) y pasa las posiciones de cada buque, en orden de hora, por la misma
máquina de estados que usa el worker (`app/services/transit_detector.py`). No usa base de datos
ni red: sirve para ver qué tránsitos habría detectado el worker con datos reales y es la base de
la validación de la tarea 5.7.

    python scripts/transit_replay.py data/collected/ais-*.jsonl
    python scripts/transit_replay.py data/collected/ais-*.jsonl --timeout-minutes 60 --json

Al terminar el fichero se cierra con `expire` a la hora de la última posición: un tránsito que
sigue abierto y aún no ha agotado el timeout queda como `in_progress`.
"""

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.services.ais_parser import PositionUpdate
from app.services.transit_detector import (
    TransitAborted,
    TransitCompleted,
    TransitDirection,
    TransitEvent,
    TransitStarted,
    VesselTrack,
    expire,
    on_position,
)
from app.services.zones import ZoneId, zone_at

DEFAULT_TIMEOUT_MINUTES = 30


@dataclass(frozen=True, slots=True)
class ReplayedTransit:
    mmsi: int
    direction: str
    status: str  # `completed`, `aborted` o `in_progress`
    abort_reason: str | None
    entered_at: datetime
    exited_at: datetime | None

    @property
    def duration(self) -> timedelta | None:
        if self.status != "completed" or self.exited_at is None:
            return None
        return self.exited_at - self.entered_at

    def as_json(self) -> dict[str, Any]:
        return {
            "mmsi": self.mmsi,
            "direction": self.direction,
            "status": self.status,
            "abort_reason": self.abort_reason,
            "entered_at": self.entered_at.isoformat(),
            "exited_at": self.exited_at.isoformat() if self.exited_at else None,
            "duration_minutes": (
                round(self.duration.total_seconds() / 60) if self.duration is not None else None
            ),
        }


@dataclass
class ReplayResult:
    transits: list[ReplayedTransit] = field(default_factory=list)
    positions: int = 0
    vessels: int = 0
    skipped: Counter[str] = field(default_factory=Counter)
    first_at: datetime | None = None
    last_at: datetime | None = None

    def completed_per_day(self) -> dict[date, Counter[str]]:
        """Tránsitos completados por día (UTC de la salida) y dirección."""
        days: dict[date, Counter[str]] = defaultdict(Counter)
        for transit in self.transits:
            if transit.status == "completed" and transit.exited_at is not None:
                days[transit.exited_at.astimezone(UTC).date()][transit.direction] += 1
        return dict(sorted(days.items()))


def read_positions(lines: Iterable[str], skipped: Counter[str]) -> list[PositionUpdate]:
    """Posiciones válidas de un JSON Lines. Lo demás se cuenta en `skipped` por motivo.

    El fichero es una entrada externa: nada de lo que traiga se confía sin comprobar tipo y rango.
    """
    positions: list[PositionUpdate] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            skipped["invalid_json"] += 1
            continue
        if not isinstance(record, dict):
            skipped["invalid_record"] += 1
            continue
        if record.get("kind") != "position":
            skipped["not_a_position"] += 1
            continue
        position = _position(record)
        if position is None:
            skipped["invalid_position"] += 1
            continue
        positions.append(position)
    return positions


def _number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _position(record: dict[str, Any]) -> PositionUpdate | None:
    mmsi, lat, lon = record.get("mmsi"), record.get("lat"), record.get("lon")
    if (
        not isinstance(mmsi, int)
        or isinstance(mmsi, bool)
        or not 100_000_000 <= mmsi <= 999_999_999
    ):
        return None
    if not (_number(lat) and _number(lon)) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    try:
        received_at = datetime.fromisoformat(str(record["received_at"]))
    except (KeyError, ValueError):
        return None
    if received_at.tzinfo is None:
        return None
    return PositionUpdate(
        mmsi=mmsi,
        received_at=received_at,
        lat=float(lat),
        lon=float(lon),
        sog=_optional_number(record.get("sog"), minimum=0, maximum=102.3),
        cog=_optional_number(record.get("cog"), minimum=0, maximum=360),
        heading=None,
        nav_status=None,
    )


def _optional_number(value: object, *, minimum: float, maximum: float) -> float | None:
    if not _number(value) or not math.isfinite(float(value)):
        return None
    numeric = float(value)
    if not minimum <= numeric < maximum:
        return None
    return numeric


def replay(positions: Sequence[PositionUpdate], *, timeout: timedelta) -> ReplayResult:
    """Pasa las posiciones por el detector, buque a buque, en orden de hora."""
    result = ReplayResult(positions=len(positions))
    if not positions:
        return result
    ordered = sorted(positions, key=lambda item: (item.received_at, item.mmsi))
    result.first_at, result.last_at = ordered[0].received_at, ordered[-1].received_at

    tracks: dict[int, VesselTrack] = {}
    open_: dict[int, tuple[ZoneId, datetime]] = {}
    for position in ordered:
        track = tracks.get(position.mmsi) or VesselTrack(mmsi=position.mmsi)
        tracks[position.mmsi], events = on_position(track, position, timeout=timeout)
        _collect(events, open_, result)

    # Un tránsito silencioso al final del fichero ya puede haber caducado.
    for mmsi, track in tracks.items():
        tracks[mmsi], events = expire(track, ordered[-1].received_at, timeout=timeout)
        _collect(events, open_, result)
    for mmsi, (origin, entered_at) in open_.items():
        result.transits.append(
            ReplayedTransit(
                mmsi=mmsi,
                direction=_direction(origin),
                status="in_progress",
                abort_reason=None,
                entered_at=entered_at,
                exited_at=None,
            )
        )
    result.vessels = len(tracks)
    result.transits.sort(key=lambda item: (item.entered_at, item.mmsi))
    return result


def _direction(origin: ZoneId) -> str:
    return (
        TransitDirection.SOUTHBOUND.value
        if origin == "atlantic_entrance"
        else TransitDirection.NORTHBOUND.value
    )


def _collect(
    events: list[TransitEvent],
    open_: dict[int, tuple[ZoneId, datetime]],
    result: ReplayResult,
) -> None:
    for event in events:
        if isinstance(event, TransitStarted):
            open_[event.mmsi] = (event.origin, event.entered_at)
        elif isinstance(event, TransitCompleted):
            open_.pop(event.mmsi, None)
            result.transits.append(
                ReplayedTransit(
                    mmsi=event.mmsi,
                    direction=event.direction.value,
                    status="completed",
                    abort_reason=None,
                    entered_at=event.entered_at,
                    exited_at=event.exited_at,
                )
            )
        elif isinstance(event, TransitAborted):
            origin, _ = open_.pop(event.mmsi)
            result.transits.append(
                ReplayedTransit(
                    mmsi=event.mmsi,
                    direction=_direction(origin),
                    status="aborted",
                    abort_reason=event.reason.value,
                    entered_at=event.entered_at,
                    exited_at=event.aborted_at,
                )
            )


def vessels_in_zones(positions: Iterable[PositionUpdate]) -> dict[ZoneId, set[int]]:
    """Buques que tuvieron al menos una posición dentro de cada entrada (para la validación)."""
    seen: dict[ZoneId, set[int]] = defaultdict(set)
    for position in positions:
        zone = zone_at(position.lon, position.lat)
        if zone is not None:
            seen[zone].add(position.mmsi)
    return dict(seen)


def render(result: ReplayResult) -> str:
    """Resumen legible: cobertura, tránsitos por estado y completados por día."""
    lines = []
    if result.first_at and result.last_at:
        lines.append(f"Periodo: {result.first_at.isoformat()} a {result.last_at.isoformat()}")
    lines.append(f"Posiciones: {result.positions}  Buques: {result.vessels}")
    if result.skipped:
        lines.append(
            "Líneas omitidas: " + ", ".join(f"{k}={v}" for k, v in sorted(result.skipped.items()))
        )
    by_status = Counter(transit.status for transit in result.transits)
    lines.append(
        "Tránsitos: " + (", ".join(f"{k}={v}" for k, v in sorted(by_status.items())) or "ninguno")
    )
    reasons = Counter(t.abort_reason for t in result.transits if t.status == "aborted")
    if reasons:
        lines.append("Abortados: " + ", ".join(f"{k}={v}" for k, v in sorted(reasons.items())))
    for day, counts in result.completed_per_day().items():
        lines.append(
            f"  {day}: {sum(counts.values())} completados "
            f"(southbound={counts['southbound']}, northbound={counts['northbound']})"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay de posiciones AIS por el detector.")
    parser.add_argument("files", nargs="+", type=Path, help="JSON Lines del recolector")
    parser.add_argument("--timeout-minutes", type=int, default=DEFAULT_TIMEOUT_MINUTES)
    parser.add_argument("--json", action="store_true", help="un tránsito por línea, en JSON")
    args = parser.parse_args(argv)
    if not 5 <= args.timeout_minutes <= 24 * 60:
        parser.error("--timeout-minutes debe estar entre 5 y 1440")

    skipped: Counter[str] = Counter()
    positions: list[PositionUpdate] = []
    for path in args.files:
        try:
            with path.open(encoding="utf-8") as handle:
                positions.extend(read_positions(handle, skipped))
        except OSError as error:
            sys.stderr.write(f"No se pudo leer {path.name}: {type(error).__name__}\n")
            return 1
    result = replay(positions, timeout=timedelta(minutes=args.timeout_minutes))
    result.skipped = skipped
    if args.json:
        for transit in result.transits:
            sys.stdout.write(json.dumps(transit.as_json()) + "\n")
    else:
        sys.stdout.write(render(result) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
