"""Importa los datos del recolector de GitHub a la base local (issue #187).

Lee los ficheros JSON Lines descifrados de `data/collected/` (formato en `docs/AIS_COLLECTOR.md`) y
los carga en la base que lee la app:

* `vessels`: un buque por MMSI, con los datos estáticos (tipo, eslora, manga) del recolector.
* `positions`: todas las posiciones válidas. `ON CONFLICT DO NOTHING` sobre (hora, MMSI): las que
  el worker ya guardó no se duplican y se puede repetir el comando sin riesgo.
* `transits` y `anchorage_visits`: se recalculan con los mismos detectores que usa el worker y solo
  se guardan los ya **cerrados**. Un tránsito o una visita que siga abierta pertenece al worker y no
  se toca; tampoco los que se solapen en el tiempo con una fila existente del mismo buque.

    python scripts/import_collected.py                       # ensayo: cuenta, no escribe
    python scripts/import_collected.py --apply               # escribe en la base de `.env`
    python scripts/import_collected.py ais-1.jsonl --apply   # solo esos ficheros

Cuidado con qué hace y qué no: el mapa en vivo solo enseña buques con una posición de los últimos
30 minutos (`LIVE_WINDOW`), así que esto alimenta estadísticas, historial y estelas, no el mapa en
vivo. Los datos del recolector no traen nombres de buque.
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.config import get_settings
from app.core.db import SessionFactory, create_engine, create_session_factory
from app.core.logging import configure_logging
from app.models.anchorage_visit import AnchorageVisit
from app.models.transit import Transit
from app.repositories.ais import AisRepository, PositionRow, VesselRow
from app.repositories.anchorages import ClosedVisitRow
from app.services import anchorage_detector
from app.services.ais_parser import PositionUpdate

sys.path.insert(0, str(Path(__file__).resolve().parent))
from transit_replay import ReplayedTransit, read_positions, replay

DEFAULT_FILES = "data/collected/ais-*.jsonl"
BATCH_SIZE = 1000

# Un intervalo ya guardado (o a guardar): (mmsi, inicio, fin). `fin` None = sigue abierto.
Interval = tuple[int, datetime, datetime | None]


@dataclass(frozen=True, slots=True)
class StaticInfo:
    received_at: datetime
    ship_type: int | None
    length_m: float | None
    beam_m: float | None


@dataclass(slots=True)
class Collected:
    positions: list[PositionUpdate] = field(default_factory=list)
    statics: dict[int, StaticInfo] = field(default_factory=dict)
    skipped: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True, slots=True)
class Derived:
    transits: list[ReplayedTransit]
    visits: list[ClosedVisitRow]
    open_transits: int
    open_visits: int


@dataclass(slots=True)
class Summary:
    positions_read: int = 0
    vessels: int = 0
    positions_inserted: int = 0
    transits_new: int = 0
    transits_skipped: int = 0
    visits_new: int = 0
    visits_skipped: int = 0
    open_ignored: int = 0


def _positive(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if value > 0 else None


def _ship_type(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= 99 else None


def read_collected(lines: Iterable[str]) -> Collected:
    """Separa las posiciones válidas de los datos estáticos de un fichero del recolector."""
    collected = Collected()
    lines = list(lines)
    collected.positions = read_positions(lines, collected.skipped)
    for line in lines:
        if '"static"' not in line:
            continue
        try:
            record = json.loads(line)
            if record.get("kind") != "static":
                continue
            mmsi = record["mmsi"]
            received_at = datetime.fromisoformat(str(record["received_at"]))
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        if isinstance(mmsi, bool) or not isinstance(mmsi, int):
            continue
        if not 100_000_000 <= mmsi <= 999_999_999:
            continue
        info = StaticInfo(
            received_at=received_at,
            ship_type=_ship_type(record.get("ship_type")),
            length_m=_positive(record.get("length_m")),
            beam_m=_positive(record.get("beam_m")),
        )
        known = collected.statics.get(mmsi)
        if known is None or info.received_at >= known.received_at:
            collected.statics[mmsi] = info
    return collected


def merge(parts: Iterable[Collected]) -> Collected:
    total = Collected()
    for part in parts:
        total.positions.extend(part.positions)
        total.skipped.update(part.skipped)
        for mmsi, info in part.statics.items():
            known = total.statics.get(mmsi)
            if known is None or info.received_at >= known.received_at:
                total.statics[mmsi] = info
    return total


def vessel_rows(collected: Collected) -> list[VesselRow]:
    """Un `VesselRow` por buque visto: la última posición y los datos estáticos más recientes."""
    last_seen: dict[int, datetime] = {}
    for position in collected.positions:
        if position.mmsi not in last_seen or position.received_at > last_seen[position.mmsi]:
            last_seen[position.mmsi] = position.received_at
    rows = []
    for mmsi in sorted(last_seen):
        info = collected.statics.get(mmsi)
        rows.append(
            VesselRow(
                mmsi=mmsi,
                last_seen_at=last_seen[mmsi],
                ship_type=info.ship_type if info else None,
                length_m=info.length_m if info else None,
                beam_m=info.beam_m if info else None,
            )
        )
    return rows


def position_rows(positions: Iterable[PositionUpdate]) -> list[PositionRow]:
    return [
        PositionRow(
            received_at=p.received_at,
            mmsi=p.mmsi,
            lat=p.lat,
            lon=p.lon,
            sog=p.sog,
            cog=p.cog,
            heading=p.heading,
            nav_status=p.nav_status,
        )
        for p in positions
    ]


def derive_events(positions: Sequence[PositionUpdate], *, timeout: timedelta) -> Derived:
    """Recalcula con los detectores del worker; devuelve solo lo cerrado y cuenta lo abierto."""
    ordered = sorted(positions, key=lambda p: (p.received_at, p.mmsi))
    result = replay(ordered, timeout=timeout)
    closed = [t for t in result.transits if t.status in ("completed", "aborted")]
    open_transits = sum(1 for t in result.transits if t.status == "in_progress")

    visits: list[ClosedVisitRow] = []
    tracks: dict[int, anchorage_detector.AnchorageTrack] = {}
    for position in ordered:
        track = tracks.get(position.mmsi) or anchorage_detector.AnchorageTrack(mmsi=position.mmsi)
        tracks[position.mmsi], events = anchorage_detector.on_position(
            track, position, timeout=timeout
        )
        visits.extend(_closed_visits(events))
    if ordered:
        # Una visita silenciosa al final de los datos ya puede haber caducado.
        for mmsi, track in tracks.items():
            tracks[mmsi], events = anchorage_detector.expire(
                track, ordered[-1].received_at, timeout=timeout
            )
            visits.extend(_closed_visits(events))
    open_visits = sum(1 for track in tracks.values() if track.visit is not None)
    visits.sort(key=lambda v: (v.arrived_at, v.mmsi))
    return Derived(closed, visits, open_transits, open_visits)


def _closed_visits(events: Iterable[Any]) -> list[ClosedVisitRow]:
    return [
        ClosedVisitRow(
            mmsi=e.mmsi,
            anchorage=str(e.anchorage),
            arrived_at=e.arrived_at,
            departed_at=e.departed_at,
        )
        for e in events
        if isinstance(e, anchorage_detector.VisitEnded)
    ]


def overlaps(start: datetime, end: datetime | None, other: Interval) -> bool:
    """¿Se solapan [start, end] y el intervalo guardado? `None` = abierto (sin fin)."""
    _, other_start, other_end = other
    if end is not None and end < other_start:
        return False
    return not (other_end is not None and other_end < start)


def split_overlapping(
    candidates: Sequence[tuple[int, datetime, datetime | None]],
    existing: Iterable[Interval],
) -> tuple[list[int], list[int]]:
    """Devuelve los índices de los candidatos (nuevos, solapados con algo ya guardado)."""
    by_vessel: dict[int, list[Interval]] = {}
    for interval in existing:
        by_vessel.setdefault(interval[0], []).append(interval)
    new, skipped = [], []
    for index, (mmsi, start, end) in enumerate(candidates):
        if any(overlaps(start, end, other) for other in by_vessel.get(mmsi, ())):
            skipped.append(index)
        else:
            new.append(index)
    return new, skipped


async def existing_intervals(session: Any) -> tuple[list[Interval], list[Interval]]:
    transits = await session.execute(
        select(Transit.vessel_mmsi, Transit.entered_at, Transit.exited_at)
    )
    visits = await session.execute(
        select(AnchorageVisit.vessel_mmsi, AnchorageVisit.arrived_at, AnchorageVisit.departed_at)
    )
    return [tuple(row) for row in transits.all()], [tuple(row) for row in visits.all()]


async def import_collected(
    sessions: SessionFactory,
    collected: Collected,
    *,
    signal_timeout: timedelta,
    apply: bool,
) -> Summary:
    """Escribe (o solo cuenta, si `apply` es False) en una única transacción."""
    summary = Summary(positions_read=len(collected.positions))
    vessels = vessel_rows(collected)
    summary.vessels = len(vessels)
    derived = derive_events(collected.positions, timeout=signal_timeout)
    summary.open_ignored = derived.open_transits + derived.open_visits

    async with sessions() as session:
        existing_transits, existing_visits = await existing_intervals(session)
        new_t, skip_t = split_overlapping(
            [(t.mmsi, t.entered_at, t.exited_at) for t in derived.transits], existing_transits
        )
        new_v, skip_v = split_overlapping(
            [(v.mmsi, v.arrived_at, v.departed_at) for v in derived.visits], existing_visits
        )
        summary.transits_new, summary.transits_skipped = len(new_t), len(skip_t)
        summary.visits_new, summary.visits_skipped = len(new_v), len(skip_v)
        if not apply:
            await session.rollback()
            return summary

        ais = AisRepository(session)
        # Los buques primero: posiciones, tránsitos y visitas los referencian por clave foránea.
        for row in vessels:
            await ais.upsert_vessels([row])
        rows = position_rows(collected.positions)
        for start in range(0, len(rows), BATCH_SIZE):
            summary.positions_inserted += await ais.insert_positions(
                rows[start : start + BATCH_SIZE]
            )
        # Insertar filas ya cerradas, nunca `close_transit`/`close_visit`: estos cierran la fila
        # abierta del buque, que sería la del worker.
        for index in new_t:
            t = derived.transits[index]
            await session.execute(
                insert(Transit).values(
                    vessel_mmsi=t.mmsi,
                    direction=t.direction,
                    status=t.status,
                    abort_reason=t.abort_reason,
                    entered_at=t.entered_at,
                    exited_at=t.exited_at,
                )
            )
        for index in new_v:
            v = derived.visits[index]
            await session.execute(
                insert(AnchorageVisit).values(
                    vessel_mmsi=v.mmsi,
                    anchorage=v.anchorage,
                    arrived_at=v.arrived_at,
                    departed_at=v.departed_at,
                )
            )
        await session.commit()
    return summary


def load_files(paths: Sequence[Path]) -> Collected:
    parts = []
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            parts.append(read_collected(handle))
    return merge(parts)


async def run(paths: Sequence[Path], *, signal_timeout: timedelta, apply: bool) -> Summary:
    collected = load_files(paths)
    engine = create_engine(get_settings())
    try:
        return await import_collected(
            create_session_factory(engine), collected, signal_timeout=signal_timeout, apply=apply
        )
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Importa los datos del recolector a la base.")
    parser.add_argument("files", nargs="*", type=Path, help=f"por defecto: {DEFAULT_FILES}")
    parser.add_argument("--apply", action="store_true", help="escribe en la base (si no, ensayo)")
    parser.add_argument(
        "--timeout-minutes", type=int, default=settings.transit_signal_timeout_minutes
    )
    args = parser.parse_args(argv)

    configure_logging(settings.log_level)
    logger = structlog.get_logger("import_collected")
    paths: list[Path] = args.files or sorted(Path().glob(DEFAULT_FILES))
    if not paths:
        logger.error("no_files", pattern=DEFAULT_FILES)
        return 1
    try:
        summary = asyncio.run(
            run(paths, signal_timeout=timedelta(minutes=args.timeout_minutes), apply=args.apply)
        )
    except OSError as error:
        logger.error("cannot_read", reason=type(error).__name__)
        return 1
    logger.info(
        "import_applied" if args.apply else "import_dry_run",
        files=len(paths),
        positions_read=summary.positions_read,
        vessels=summary.vessels,
        positions_inserted=summary.positions_inserted,
        transits_new=summary.transits_new,
        transits_skipped=summary.transits_skipped,
        visits_new=summary.visits_new,
        visits_skipped=summary.visits_skipped,
        open_ignored=summary.open_ignored,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
