"""Importación de los datos del recolector (issue #187) contra PostgreSQL real."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import SessionFactory
from app.models.anchorage_visit import AnchorageVisit
from app.models.position import Position
from app.models.transit import Transit
from app.models.vessel import Vessel
from app.repositories.ais import AisRepository, VesselRow
from app.repositories.transits import OpenTransitRow, TransitRepository
from app.services.ais_parser import PositionUpdate
from tests.scripts_loader import load_script

importer = load_script("import_collected")

T0 = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)
TIMEOUT = timedelta(minutes=30)
ENTRANCE = (-79.93, 9.39)
LAKE = (-79.75, 9.15)
ANCHORAGE = (-79.85, 9.45)
OUTSIDE = (-79.70, 9.60)
LIVE = 352000001  # buque con un tránsito abierto del worker
OLD = 353000002  # buque solo del recolector


@pytest.fixture
async def sessions(migrated: AsyncEngine, db_app: FastAPI) -> AsyncIterator[SessionFactory]:
    factory: SessionFactory = db_app.state.session_factory  # rol canal_app
    yield factory


def at(minutes: float, point: tuple[float, float], mmsi: int, sog: float = 8.0) -> PositionUpdate:
    lon, lat = point
    return PositionUpdate(
        mmsi=mmsi,
        received_at=T0 + timedelta(minutes=minutes),
        lat=lat,
        lon=lon,
        sog=sog,
        cog=None,
        heading=None,
        nav_status=None,
    )


def collected() -> object:
    positions = [
        # OLD: cruza la entrada, se queda en silencio (tránsito abortado) y fondea (visita).
        at(0, ENTRANCE, OLD),
        at(20, LAKE, OLD),
        *(at(m, ANCHORAGE, OLD, sog=0.1) for m in range(300, 325, 5)),
        at(330, OUTSIDE, OLD),
        # LIVE: tiene un tránsito abierto del worker (mes siguiente) y, en estos datos, uno viejo
        # que se aborta por silencio. Importarlo no debe cerrar el abierto.
        at(0, ENTRANCE, LIVE),
        at(20, LAKE, LIVE),
    ]
    return importer.Collected(
        positions=positions,
        statics={OLD: importer.StaticInfo(T0, 70, 294.0, 32.0)},
    )


async def count(sessions: SessionFactory, model: type) -> int:
    async with sessions() as session:
        return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


async def start_worker_transit(sessions: SessionFactory) -> None:
    """Deja un tránsito abierto de LIVE, como el que tendría el worker en marcha."""
    async with sessions() as session:
        await AisRepository(session).upsert_vessels([VesselRow(mmsi=LIVE, last_seen_at=T0)])
        await TransitRepository(session).open_transit(
            OpenTransitRow(mmsi=LIVE, direction="southbound", entered_at=T0 + timedelta(days=30))
        )
        await session.commit()


async def test_a_dry_run_counts_but_writes_nothing(sessions: SessionFactory) -> None:
    summary = await importer.import_collected(
        sessions, collected(), signal_timeout=TIMEOUT, apply=False
    )

    assert summary.transits_new >= 1 and summary.visits_new >= 1
    assert summary.positions_inserted == 0
    assert await count(sessions, Position) == 0
    assert await count(sessions, Vessel) == 0
    assert await count(sessions, Transit) == 0


async def test_apply_writes_vessels_positions_and_closed_events(sessions: SessionFactory) -> None:
    summary = await importer.import_collected(
        sessions, collected(), signal_timeout=TIMEOUT, apply=True
    )

    assert summary.positions_inserted == summary.positions_read
    assert await count(sessions, Position) == summary.positions_read
    async with sessions() as session:
        vessel = (await session.execute(select(Vessel).where(Vessel.mmsi == OLD))).scalar_one()
        assert (vessel.ship_type, vessel.length_m) == (70, 294.0)
        statuses = (await session.execute(select(Transit.vessel_mmsi, Transit.status))).all()
        visits = (await session.execute(select(AnchorageVisit.vessel_mmsi))).all()
    assert (OLD, "aborted") in [tuple(row) for row in statuses]
    assert OLD in [row[0] for row in visits]


async def test_importing_twice_does_not_duplicate_anything(sessions: SessionFactory) -> None:
    await importer.import_collected(sessions, collected(), signal_timeout=TIMEOUT, apply=True)
    before = (
        await count(sessions, Position),
        await count(sessions, Transit),
        await count(sessions, AnchorageVisit),
    )

    again = await importer.import_collected(
        sessions, collected(), signal_timeout=TIMEOUT, apply=True
    )

    assert again.positions_inserted == 0
    assert (again.transits_new, again.visits_new) == (0, 0)
    assert again.transits_skipped >= 1 and again.visits_skipped >= 1
    assert (
        await count(sessions, Position),
        await count(sessions, Transit),
        await count(sessions, AnchorageVisit),
    ) == before


async def test_an_open_transit_of_the_worker_is_never_touched(sessions: SessionFactory) -> None:
    await start_worker_transit(sessions)

    await importer.import_collected(sessions, collected(), signal_timeout=TIMEOUT, apply=True)

    async with sessions() as session:
        [row] = (
            await session.execute(
                select(Transit.status, Transit.exited_at, Transit.entered_at).where(
                    Transit.vessel_mmsi == LIVE, Transit.status == "in_progress"
                )
            )
        ).all()
    assert row.exited_at is None
    assert row.entered_at == T0 + timedelta(days=30)
    async with sessions() as session:
        closed = (
            await session.execute(
                select(Transit.status, Transit.entered_at).where(
                    Transit.vessel_mmsi == LIVE, Transit.status == "aborted"
                )
            )
        ).all()
    assert [tuple(r) for r in closed] == [("aborted", T0)]  # el viejo sí se importa, ya cerrado
