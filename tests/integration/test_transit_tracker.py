"""Detección de tránsitos en el worker (5.3) contra PostgreSQL real, con el rol de la app."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import SessionFactory
from app.models.transit import Transit
from app.repositories.transits import ClosedTransitRow, OpenTransitRow, TransitRepository
from app.services.ais_parser import PositionUpdate
from app.workers.ais_writer import AisWriter
from app.workers.transit_tracker import TransitTracker

T0 = datetime(2026, 11, 6, 6, 0, tzinfo=UTC)
TIMEOUT = timedelta(minutes=30)
MMSI = 352000001

ATLANTIC = (-79.93, 9.39)
PACIFIC = (-79.552, 8.91)
GATUN = (-79.75, 9.15)  # en el Canal, fuera de las dos entradas


def at(point: tuple[float, float], minutes: float, mmsi: int = MMSI) -> PositionUpdate:
    lon, lat = point
    return PositionUpdate(
        mmsi=mmsi,
        received_at=T0 + timedelta(minutes=minutes),
        lat=lat,
        lon=lon,
        sog=8.0,
        cog=180.0,
        heading=180,
        nav_status=0,
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
) -> TransitTracker:
    options: dict[str, Any] = {
        "session_factory": sessions,
        "timeout": TIMEOUT,
        "retry_base_seconds": 0.001,
        "retry_max_seconds": 0.01,
        "clock": clock or Clock(),
    }
    return TransitTracker(**(options | kwargs))


async def feed(
    sessions: SessionFactory, tracker: TransitTracker, *positions: PositionUpdate
) -> None:
    """Guarda las posiciones con el writer real, que avisa al tracker tras cada commit."""
    writer = AisWriter(
        queue=asyncio.Queue(), session_factory=sessions, on_committed=tracker.on_batch
    )
    for position in positions:
        await writer.flush([position])


async def transits(sessions: SessionFactory) -> list[Any]:
    async with sessions() as session:
        rows = await session.execute(
            select(
                Transit.vessel_mmsi,
                Transit.direction,
                Transit.status,
                Transit.abort_reason,
                Transit.entered_at,
                Transit.exited_at,
                Transit.duration_minutes,
            ).order_by(Transit.entered_at)
        )
        return list(rows.all())


async def restored(sessions: SessionFactory, clock: Clock | None = None) -> TransitTracker:
    tracker = make_tracker(sessions, clock)
    await tracker.restore()
    return tracker


# --- Eventos del detector en la base --------------------------------------------------------


async def test_atlantic_to_pacific_is_a_completed_southbound_transit(
    sessions: SessionFactory,
) -> None:
    tracker = await restored(sessions)

    # Cada posición, a menos del timeout de la anterior (si no, el tránsito se aborta).
    await feed(
        sessions,
        tracker,
        at(ATLANTIC, 0),
        *(at(GATUN, minutes) for minutes in range(25, 480, 25)),
        at(PACIFIC, 490),
    )

    assert await transits(sessions) == [
        (
            MMSI,
            "southbound",
            "completed",
            None,
            T0,
            T0 + timedelta(minutes=490),
            490,
        )
    ]
    assert tracker.stats.started == 1
    assert tracker.stats.completed == 1
    assert tracker.open_transits == 0


async def test_pacific_to_atlantic_is_northbound(sessions: SessionFactory) -> None:
    tracker = await restored(sessions)

    await feed(sessions, tracker, at(PACIFIC, 0), at(GATUN, 20), at(ATLANTIC, 40))

    [row] = await transits(sessions)
    assert row[1:4] == ("northbound", "completed", None)


async def test_an_open_transit_is_stored_as_in_progress(sessions: SessionFactory) -> None:
    tracker = await restored(sessions)

    await feed(sessions, tracker, at(ATLANTIC, 0), at(GATUN, 20))

    [row] = await transits(sessions)
    assert row == (MMSI, "southbound", "in_progress", None, T0, None, None)
    assert tracker.open_transits == 1


async def test_coming_back_to_the_origin_aborts_by_reversal(sessions: SessionFactory) -> None:
    tracker = await restored(sessions)

    await feed(sessions, tracker, at(ATLANTIC, 0), at(GATUN, 20), at(ATLANTIC, 40))

    [row] = await transits(sessions)
    assert row[1:6] == (
        "southbound",
        "aborted",
        "reversal",
        T0,
        T0 + timedelta(minutes=40),
    )
    assert row[6] is None  # un aborto no tiene duración de tránsito


async def test_expire_aborts_a_silent_transit_at_the_deadline(sessions: SessionFactory) -> None:
    tracker = await restored(sessions)
    await feed(sessions, tracker, at(ATLANTIC, 0), at(GATUN, 20))

    await tracker.expire(T0 + timedelta(minutes=20) + TIMEOUT)  # justo el límite: sigue abierto
    assert (await transits(sessions))[0][2] == "in_progress"

    await tracker.expire(T0 + timedelta(minutes=51))

    [row] = await transits(sessions)
    assert row[2:6] == ("aborted", "timeout", T0, T0 + timedelta(minutes=20) + TIMEOUT)
    assert tracker.open_transits == 0


async def test_expire_forgets_quiet_vessels_without_a_transit(sessions: SessionFactory) -> None:
    tracker = await restored(sessions)
    await feed(sessions, tracker, at(GATUN, 0, mmsi=352000002), at(ATLANTIC, 0))

    await tracker.expire(T0 + timedelta(minutes=31))

    # Los dos se olvidan: el de Gatún no tenía tránsito y el del Atlántico ya lo tiene abortado.
    assert tracker.tracks == {}
    assert [row[2] for row in await transits(sessions)] == ["aborted"]


async def test_batches_are_skipped_until_the_state_is_restored(sessions: SessionFactory) -> None:
    tracker = make_tracker(sessions)

    await feed(sessions, tracker, at(ATLANTIC, 0))

    assert await transits(sessions) == []
    assert tracker.stats.batches_skipped == 1


# --- Repositorio ----------------------------------------------------------------------------


async def test_a_vessel_has_at_most_one_open_transit(sessions: SessionFactory) -> None:
    tracker = await restored(sessions)
    await feed(sessions, tracker, at(GATUN, 0))
    row = OpenTransitRow(mmsi=MMSI, direction="southbound", entered_at=T0)

    async with sessions() as session:
        repository = TransitRepository(session)
        assert await repository.open_transit(row) is True
        assert await repository.open_transit(row) is False
        await session.commit()

    assert len(await transits(sessions)) == 1


async def test_a_close_without_its_open_row_stores_the_whole_transit(
    sessions: SessionFactory,
) -> None:
    tracker = await restored(sessions)
    await feed(sessions, tracker, at(GATUN, 0))

    async with sessions() as session:
        await TransitRepository(session).close_transit(
            ClosedTransitRow(
                mmsi=MMSI,
                direction="northbound",
                status="completed",
                abort_reason=None,
                entered_at=T0,
                exited_at=T0 + timedelta(hours=9),
            )
        )
        await session.commit()

    [row] = await transits(sessions)
    assert row == (MMSI, "northbound", "completed", None, T0, T0 + timedelta(hours=9), 540)


async def test_events_are_dropped_and_counted_when_the_database_is_down(
    sessions: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    tracker = await restored(sessions)

    async def database_down(*_: Any, **__: Any) -> bool:
        raise OSError("connection refused")

    monkeypatch.setattr(TransitRepository, "open_transit", database_down)
    await feed(sessions, tracker, at(ATLANTIC, 0))

    assert tracker.stats.events_dropped == 1
    assert tracker.stats.last_error == "OSError"
    assert await transits(sessions) == []
    # El detector sigue con su estado: el cierre guardará el tránsito completo.
    monkeypatch.undo()
    await feed(sessions, tracker, at(GATUN, 20), at(PACIFIC, 40))
    [row] = await transits(sessions)
    assert row[1:3] == ("southbound", "completed")


# --- Reinicio del worker --------------------------------------------------------------------


async def test_an_open_transit_survives_a_restart(sessions: SessionFactory) -> None:
    clock = Clock()
    first = await restored(sessions, clock)
    await feed(sessions, first, at(ATLANTIC, 0), at(GATUN, 20))

    clock.now = T0 + timedelta(minutes=25)
    second = await restored(sessions, clock)
    track = second.tracks[MMSI]
    assert track.transit is not None
    assert track.transit.left_origin is True
    assert track.last_seen_at == T0 + timedelta(minutes=20)

    await feed(sessions, second, at(PACIFIC, 40))
    [row] = await transits(sessions)
    assert row[2:7] == ("completed", None, T0, T0 + timedelta(minutes=40), 40)


async def test_a_restart_remembers_that_the_vessel_never_left_its_origin(
    sessions: SessionFactory,
) -> None:
    first = await restored(sessions)
    await feed(sessions, first, at(ATLANTIC, 0), at(ATLANTIC, 5))

    second = await restored(sessions)
    await feed(sessions, second, at(ATLANTIC, 10))  # sigue en la entrada: no es una reversa

    [row] = await transits(sessions)
    assert row[2] == "in_progress"


async def test_a_transit_that_expired_while_stopped_is_aborted_on_restart(
    sessions: SessionFactory,
) -> None:
    first = await restored(sessions)
    await feed(sessions, first, at(ATLANTIC, 0), at(GATUN, 20))

    clock = Clock()
    clock.now = T0 + timedelta(hours=3)
    second = await restored(sessions, clock)

    [row] = await transits(sessions)
    assert row[2:6] == ("aborted", "timeout", T0, T0 + timedelta(minutes=20) + TIMEOUT)
    assert second.open_transits == 0


async def test_a_vessel_still_in_its_exit_zone_does_not_open_a_new_transit_after_a_restart(
    sessions: SessionFactory,
) -> None:
    first = await restored(sessions)
    await feed(sessions, first, at(ATLANTIC, 0), at(GATUN, 20), at(PACIFIC, 40), at(PACIFIC, 45))

    clock = Clock()
    clock.now = T0 + timedelta(minutes=50)
    second = await restored(sessions, clock)
    assert second.tracks[MMSI].must_leave == "pacific_entrance"

    await feed(sessions, second, at(PACIFIC, 55))
    assert len(await transits(sessions)) == 1

    # Cuando sale y vuelve a entrar, sí abre otro (rumbo norte).
    await feed(sessions, second, at(GATUN, 70), at(PACIFIC, 90))
    rows = await transits(sessions)
    assert [row[2] for row in rows] == ["completed", "in_progress"]
    assert rows[1][1] == "northbound"


async def test_run_restores_retrying_and_stops_on_request(sessions: SessionFactory) -> None:
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
