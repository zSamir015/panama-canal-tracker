"""Buques con destino al Canal contra PostgreSQL real, con el rol de la app (`canal_app`)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.db import SessionFactory
from app.models.canal_bound_vessel import CanalBoundVessel
from app.models.position import Position
from app.repositories.canal_bound import CanalBoundRepository
from app.services.ais_parser import VesselStatic
from app.workers import canal_bound_writer
from app.workers.ais_consumer import run_worker
from app.workers.canal_bound_writer import CanalBoundWriter
from tests.scripts_loader import load_script

T0 = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


def static(mmsi: int = 636012345, seconds: int = 0, **overrides: Any) -> VesselStatic:
    values: dict[str, Any] = {
        "mmsi": mmsi,
        "name": "GULF TRADER",
        "imo": 9123456,
        "ship_type": 80,
        "length_m": 183.0,
        "beam_m": 32.0,
        "destination": "USHOU>PABLB",
        "eta": T0 + timedelta(days=5),
        "lat": 28.91,
        "lon": -94.62,
        "received_at": T0 + timedelta(seconds=seconds),
    }
    return VesselStatic(**(values | overrides))


@pytest.fixture
async def sessions(migrated: AsyncEngine, db_app: FastAPI) -> AsyncIterator[SessionFactory]:
    factory: SessionFactory = db_app.state.session_factory  # rol canal_app
    yield factory


def make_writer(sessions: SessionFactory, **kwargs: Any) -> CanalBoundWriter:
    options: dict[str, Any] = {
        "queue": asyncio.Queue(),
        "session_factory": sessions,
        "retry_base_seconds": 0.001,
        "retry_max_seconds": 0.01,
        "max_attempts": 3,
    }
    return CanalBoundWriter(**(options | kwargs))


async def stored(sessions: SessionFactory) -> list[Any]:
    async with sessions() as session:
        rows = await session.execute(
            select(
                CanalBoundVessel.mmsi,
                CanalBoundVessel.destination,
                CanalBoundVessel.port_locode,
                CanalBoundVessel.name,
                CanalBoundVessel.lat,
                CanalBoundVessel.lon,
                CanalBoundVessel.reported_at,
            ).order_by(CanalBoundVessel.mmsi)
        )
        return list(rows.all())


async def test_only_canal_bound_vessels_are_stored(sessions: SessionFactory) -> None:
    writer = make_writer(sessions)

    await writer.flush(
        [
            static(),
            static(mmsi=636000002, destination="CNSHA"),
            static(mmsi=636000003, destination="PAMIT>ITVDL"),  # sale de Panamá
            static(mmsi=636000004, destination="PANAMA CANAL"),
        ]
    )

    assert await stored(sessions) == [
        (636000004, "PANAMA CANAL", "PA", "GULF TRADER", 28.91, -94.62, T0),
        (636012345, "USHOU>PABLB", "PABLB", "GULF TRADER", 28.91, -94.62, T0),
    ]
    assert writer.stats.upserted == 2
    assert writer.stats.ports == {"PA": 1, "PABLB": 1}


async def test_a_new_report_replaces_destination_and_eta_but_keeps_known_data(
    sessions: SessionFactory,
) -> None:
    writer = make_writer(sessions)
    await writer.flush([static()])

    await writer.flush(
        [static(seconds=60, destination="PA CTB", eta=None, name=None, lat=None, lon=None)]
    )

    async with sessions() as session:
        row = (await session.execute(select(CanalBoundVessel))).scalar_one()
    assert (row.destination, row.port_locode, row.eta) == ("PA CTB", "PACTB", None)
    assert row.name == "GULF TRADER"
    assert (row.lat, row.lon) == (28.91, -94.62)
    assert row.reported_at == T0 + timedelta(seconds=60)


async def test_an_older_report_never_overwrites_a_newer_one(sessions: SessionFactory) -> None:
    writer = make_writer(sessions)
    await writer.flush([static(seconds=60, destination="PA CTB")])

    await writer.flush([static(seconds=0, destination="PA BLB")])

    [row] = await stored(sessions)
    assert row.destination == "PA CTB"


async def test_a_vessel_that_declares_another_destination_is_removed(
    sessions: SessionFactory,
) -> None:
    writer = make_writer(sessions)
    await writer.flush([static(), static(mmsi=636000002)])

    await writer.flush([static(seconds=60, destination="CNSHA")])

    assert [row.mmsi for row in await stored(sessions)] == [636000002]
    assert writer.stats.removed == 1


async def test_a_restarted_writer_still_removes_vessels_stored_before(
    sessions: SessionFactory,
) -> None:
    await make_writer(sessions).flush([static()])

    restarted = make_writer(sessions)
    await restarted.flush([static(seconds=60, destination=None)])

    assert await stored(sessions) == []


async def test_destinations_are_stored_literally_through_bound_parameters(
    sessions: SessionFactory,
) -> None:
    hostile = "PABLB'); DROP TABLE x;--"[:20]

    await make_writer(sessions).flush([static(destination=hostile, name="<b>X</b>")])

    [row] = await stored(sessions)
    assert (row.destination, row.name) == (hostile, "<b>X</b>")


async def test_database_down_retries_and_then_drops_the_batch(
    sessions: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken_upsert(self: CanalBoundRepository, rows: Any) -> None:
        raise OSError("conexión perdida")

    monkeypatch.setattr(CanalBoundRepository, "upsert", broken_upsert)
    writer = make_writer(sessions)

    await writer.flush([static()])

    assert writer.stats.batches_retried == 3
    assert writer.stats.batches_dropped == 1
    assert await stored(sessions) == []


async def test_writer_runs_as_the_app_role(sessions: SessionFactory) -> None:
    async with sessions() as session:
        role = (await session.execute(text("SELECT current_user"))).scalar_one()
    assert role == "canal_app"

    await make_writer(sessions).flush([static()])

    assert len(await stored(sessions)) == 1


def test_writer_module_never_builds_sql_from_strings() -> None:
    with open(canal_bound_writer.__file__, encoding="utf-8") as handle:
        content = handle.read()
    assert "text(" not in content
    assert "execute(" not in content


async def test_worker_stores_simulated_canal_bound_vessels_end_to_end(
    migrated: AsyncEngine, db_settings: Settings, sessions: SessionFactory
) -> None:
    # El simulador declara BALBOA o CRISTOBAL como destino: la segunda conexión debe guardarlos
    # mientras la primera sigue escribiendo posiciones.
    sim = load_script("ais_simulator")
    messages = sim.generate(start=T0, duration=timedelta(minutes=10), seed=1)
    server = await sim.start_server(messages, port=0, speed=0)
    port = next(iter(server.sockets)).getsockname()[1]
    settings = db_settings.model_copy(
        update={
            "aisstream_url": f"ws://127.0.0.1:{port}",
            "aisstream_api_key": SecretStr("clave-de-pruebas"),
            "ais_batch_size": 50,
            "ais_batch_flush_seconds": 0.05,
        }
    )
    stop = asyncio.Event()
    try:
        task = asyncio.create_task(run_worker(settings, stop))
        async with asyncio.timeout(15):
            while not await stored(sessions):
                if task.done():
                    task.result()
                await asyncio.sleep(0.1)
        stop.set()
        await asyncio.wait_for(task, timeout=10)
    finally:
        server.close()
        await server.wait_closed()

    rows = await stored(sessions)
    assert {row.port_locode for row in rows} <= {"PABLB", "PACTB"}
    assert all(row.lat is not None for row in rows)
    async with sessions() as session:
        positions = await session.scalar(select(func.count()).select_from(Position))
    assert positions and positions > 0
