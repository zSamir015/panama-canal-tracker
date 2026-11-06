"""Esperas en fondeo en el worker (6.1) contra PostgreSQL real, con el rol de la app."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import SessionFactory
from app.models.anchorage_visit import AnchorageVisit
from app.repositories.ais import AisRepository, VesselRow
from app.repositories.anchorages import AnchorageRepository, ClosedVisitRow, OpenVisitRow
from app.repositories.transits import OpenTransitRow, TransitRepository
from app.services.ais_parser import PositionUpdate
from app.workers.ais_writer import AisWriter
from app.workers.anchorage_tracker import AnchorageTracker

T0 = datetime(2026, 11, 6, 6, 0, tzinfo=UTC)
TIMEOUT = timedelta(minutes=30)
MMSI = 352000001

ATLANTIC = (-79.85, 9.45)
PACIFIC = (-79.52, 8.84)
SEA = (-79.70, 9.60)


def at(
    minutes: float, point: tuple[float, float] = ATLANTIC, mmsi: int = MMSI, sog: float = 0.1
) -> PositionUpdate:
    lon, lat = point
    return PositionUpdate(
        mmsi=mmsi,
        received_at=T0 + timedelta(minutes=minutes),
        lat=lat,
        lon=lon,
        sog=sog,
        cog=None,
        heading=None,
        nav_status=1,
    )


@pytest.fixture
async def sessions(migrated: AsyncEngine, db_app: FastAPI) -> AsyncIterator[SessionFactory]:
    factory: SessionFactory = db_app.state.session_factory  # rol canal_app
    yield factory


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def make_tracker(
    sessions: SessionFactory, clock: Clock | None = None, **kwargs: Any
) -> AnchorageTracker:
    options: dict[str, Any] = {
        "session_factory": sessions,
        "timeout": TIMEOUT,
        "retry_base_seconds": 0.001,
        "retry_max_seconds": 0.01,
        "clock": clock or Clock(),
    }
    return AnchorageTracker(**(options | kwargs))


async def restored(sessions: SessionFactory, clock: Clock | None = None) -> AnchorageTracker:
    tracker = make_tracker(sessions, clock)
    await tracker.restore()
    return tracker


async def feed(
    sessions: SessionFactory, tracker: AnchorageTracker, *positions: PositionUpdate
) -> None:
    """Guarda las posiciones con el writer real, que avisa al tracker tras cada commit."""
    writer = AisWriter(
        queue=asyncio.Queue(), session_factory=sessions, on_committed=tracker.on_batch
    )
    for position in positions:
        await writer.flush([position])


async def visits(sessions: SessionFactory) -> list[Any]:
    async with sessions() as session:
        rows = await session.execute(
            select(
                AnchorageVisit.vessel_mmsi,
                AnchorageVisit.anchorage,
                AnchorageVisit.arrived_at,
                AnchorageVisit.departed_at,
                AnchorageVisit.transit_id,
            ).order_by(AnchorageVisit.arrived_at)
        )
        return list(rows.all())


def waiting(start: int, end: int, point: tuple[float, float] = ATLANTIC) -> list[PositionUpdate]:
    return [at(m, point) for m in range(start, end, 5)]


# --- Eventos del detector en la base --------------------------------------------------------


async def test_a_confirmed_wait_is_stored_open_from_when_the_vessel_stopped(
    sessions: SessionFactory,
) -> None:
    tracker = await restored(sessions)

    await feed(sessions, tracker, *waiting(0, 25))

    assert await visits(sessions) == [(MMSI, "atlantic", T0, None, None)]
    assert tracker.open_visits == 1
    assert tracker.stats.started == 1


async def test_a_short_stop_is_not_stored(sessions: SessionFactory) -> None:
    tracker = await restored(sessions)

    await feed(sessions, tracker, *waiting(0, 10), at(12, SEA, sog=8.0))

    assert await visits(sessions) == []


async def test_leaving_closes_the_visit(sessions: SessionFactory) -> None:
    tracker = await restored(sessions)

    await feed(sessions, tracker, *waiting(0, 60), at(60, SEA, sog=8.0))

    assert await visits(sessions) == [(MMSI, "atlantic", T0, T0 + timedelta(minutes=60), None)]
    assert tracker.open_visits == 0


async def test_each_anchorage_is_its_own_visit(sessions: SessionFactory) -> None:
    tracker = await restored(sessions)

    await feed(
        sessions,
        tracker,
        *waiting(0, 20),
        at(25, SEA, sog=8.0),
        *[at(m, PACIFIC, mmsi=352000002) for m in range(0, 20, 5)],
    )

    rows = await visits(sessions)
    assert [(row[0], row[1], row[3] is None) for row in rows] == [
        (352000001, "atlantic", False),
        (352000002, "pacific", True),
    ]


async def test_expire_closes_a_silent_visit_at_its_last_signal(
    sessions: SessionFactory,
) -> None:
    tracker = await restored(sessions)
    await feed(sessions, tracker, *waiting(0, 25))

    await tracker.expire(T0 + timedelta(minutes=20) + TIMEOUT)  # justo el límite
    assert (await visits(sessions))[0][3] is None

    await tracker.expire(T0 + timedelta(minutes=51))

    assert (await visits(sessions))[0][3] == T0 + timedelta(minutes=20)
    assert tracker.open_visits == 0


async def test_expire_forgets_quiet_vessels(sessions: SessionFactory) -> None:
    tracker = await restored(sessions)
    await feed(sessions, tracker, at(0, SEA), at(5, ATLANTIC, mmsi=352000002))

    await tracker.expire(T0 + timedelta(minutes=40))

    assert tracker.tracks == {}


async def test_batches_are_skipped_until_the_state_is_restored(sessions: SessionFactory) -> None:
    tracker = make_tracker(sessions)

    await feed(sessions, tracker, *waiting(0, 25))

    assert await visits(sessions) == []
    assert tracker.stats.batches_skipped == 5


# --- Repositorio ----------------------------------------------------------------------------


async def seed_vessel(sessions: SessionFactory) -> None:
    async with sessions() as session:
        await AisRepository(session).upsert_vessels([VesselRow(mmsi=MMSI, last_seen_at=T0)])
        await session.commit()


async def test_a_vessel_has_at_most_one_open_visit(sessions: SessionFactory) -> None:
    await seed_vessel(sessions)
    row = OpenVisitRow(mmsi=MMSI, anchorage="atlantic", arrived_at=T0)

    async with sessions() as session:
        repository = AnchorageRepository(session)
        assert await repository.open_visit(row) is True
        assert await repository.open_visit(row) is False
        await session.commit()

    assert len(await visits(sessions)) == 1


async def test_a_close_without_its_open_row_stores_the_whole_visit(
    sessions: SessionFactory,
) -> None:
    await seed_vessel(sessions)

    async with sessions() as session:
        await AnchorageRepository(session).close_visit(
            ClosedVisitRow(
                mmsi=MMSI,
                anchorage="pacific",
                arrived_at=T0,
                departed_at=T0 + timedelta(hours=9),
            )
        )
        await session.commit()

    assert await visits(sessions) == [(MMSI, "pacific", T0, T0 + timedelta(hours=9), None)]


async def test_the_database_rejects_a_visit_that_leaves_before_it_arrives(
    sessions: SessionFactory,
) -> None:
    await seed_vessel(sessions)

    with pytest.raises(IntegrityError):
        async with sessions() as session:
            await AnchorageRepository(session).close_visit(
                ClosedVisitRow(mmsi=MMSI, anchorage="atlantic", arrived_at=T0, departed_at=T0)
            )
            await session.commit()


async def test_events_are_dropped_and_counted_when_the_database_is_down(
    sessions: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    tracker = await restored(sessions)

    async def database_down(*_: Any, **__: Any) -> bool:
        raise OSError("connection refused")

    monkeypatch.setattr(AnchorageRepository, "open_visit", database_down)
    await feed(sessions, tracker, *waiting(0, 25))

    assert tracker.stats.events_dropped == 1
    assert tracker.stats.last_error == "OSError"
    assert await visits(sessions) == []
    # El detector sigue con su estado: el cierre guardará la visita completa.
    monkeypatch.undo()
    await feed(sessions, tracker, at(30, SEA, sog=8.0))
    assert await visits(sessions) == [(MMSI, "atlantic", T0, T0 + timedelta(minutes=30), None)]


# --- Reinicio del worker --------------------------------------------------------------------


async def test_an_open_visit_survives_a_restart(sessions: SessionFactory) -> None:
    clock = Clock()
    first = await restored(sessions, clock)
    await feed(sessions, first, *waiting(0, 25))

    clock.now = T0 + timedelta(minutes=30)
    second = await restored(sessions, clock)
    track = second.tracks[MMSI]
    assert track.visit is not None and track.visit.arrived_at == T0
    assert track.last_seen_at == T0 + timedelta(minutes=20)

    await feed(sessions, second, at(40, SEA, sog=8.0))
    assert await visits(sessions) == [(MMSI, "atlantic", T0, T0 + timedelta(minutes=40), None)]


async def test_a_visit_that_expired_while_stopped_is_closed_on_restart(
    sessions: SessionFactory,
) -> None:
    first = await restored(sessions)
    await feed(sessions, first, *waiting(0, 25))

    clock = Clock()
    clock.now = T0 + timedelta(hours=3)
    second = await restored(sessions, clock)

    assert await visits(sessions) == [(MMSI, "atlantic", T0, T0 + timedelta(minutes=20), None)]
    assert second.open_visits == 0


async def test_run_restores_and_stops_on_request(sessions: SessionFactory) -> None:
    tracker = make_tracker(sessions, expire_interval=0.01)
    stop = asyncio.Event()

    task = asyncio.create_task(tracker.run(stop))
    for _ in range(100):
        if tracker.stats.restored:
            break
        await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(task, timeout=2)

    assert tracker.stats.restored is True


# --- Enlace con el tránsito siguiente (6.2) -------------------------------------------------


async def add_transit(
    sessions: SessionFactory, minutes: float, direction: str = "southbound", mmsi: int = MMSI
) -> None:
    async with sessions() as session:
        await AisRepository(session).upsert_vessels([VesselRow(mmsi=mmsi, last_seen_at=T0)])
        await TransitRepository(session).open_transit(
            OpenTransitRow(mmsi, direction, T0 + timedelta(minutes=minutes))
        )
        await session.commit()


async def linked(sessions: SessionFactory) -> list[Any]:
    return [row[4] is not None for row in await visits(sessions)]


async def test_a_wait_is_linked_to_the_transit_that_follows_it(sessions: SessionFactory) -> None:
    tracker = await restored(sessions)
    await feed(sessions, tracker, *waiting(0, 60), at(60, SEA, sog=8.0))
    assert await linked(sessions) == [False]

    await add_transit(sessions, 70)
    await tracker.link(T0 + timedelta(minutes=75))

    assert await linked(sessions) == [True]
    assert tracker.stats.linked == 1


async def test_linking_is_idempotent(sessions: SessionFactory) -> None:
    tracker = await restored(sessions)
    await feed(sessions, tracker, *waiting(0, 60), at(60, SEA, sog=8.0))
    await add_transit(sessions, 70)

    await tracker.link(T0 + timedelta(minutes=75))
    await tracker.link(T0 + timedelta(minutes=76))

    assert tracker.stats.linked == 1


async def test_a_transit_on_the_wrong_side_is_not_linked(sessions: SessionFactory) -> None:
    tracker = await restored(sessions)
    await feed(sessions, tracker, *waiting(0, 60), at(60, SEA, sog=8.0))
    await add_transit(sessions, 70, direction="northbound")

    await tracker.link(T0 + timedelta(minutes=75))

    assert await linked(sessions) == [False]


async def test_nothing_happens_without_a_transit(sessions: SessionFactory) -> None:
    tracker = await restored(sessions)
    await feed(sessions, tracker, *waiting(0, 60), at(60, SEA, sog=8.0))

    await tracker.link(T0 + timedelta(minutes=75))

    assert await linked(sessions) == [False]
    assert tracker.stats.linked == 0


async def test_old_unlinked_visits_are_left_alone(sessions: SessionFactory) -> None:
    tracker = await restored(sessions)
    await feed(sessions, tracker, *waiting(0, 60), at(60, SEA, sog=8.0))
    await add_transit(sessions, 70)

    await tracker.link(
        T0 + timedelta(days=10)
    )  # la visita y el tránsito quedan fuera de la ventana

    assert await linked(sessions) == [False]


async def test_a_database_failure_while_linking_is_counted_and_not_raised(
    sessions: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    tracker = await restored(sessions)

    async def database_down(*_: Any, **__: Any) -> list[Any]:
        raise OSError("connection refused")

    monkeypatch.setattr(AnchorageRepository, "unlinked_visits", database_down)

    await tracker.link(T0)

    assert tracker.stats.last_error == "OSError"
    assert tracker.stats.linked == 0
