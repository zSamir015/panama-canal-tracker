"""Writer AIS contra PostgreSQL real, con el rol de la app (`canal_app`, sin DDL)."""

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
from app.models.position import Position
from app.models.vessel import Vessel
from app.repositories.ais import AisRepository
from app.services.ais_parser import PositionUpdate, VesselStatic
from app.workers import ais_writer
from app.workers.ais_consumer import run_worker
from app.workers.ais_writer import AisWriter
from tests.scripts_loader import load_script

T0 = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


def position(mmsi: int = 352000001, seconds: int = 0, **overrides: Any) -> PositionUpdate:
    values: dict[str, Any] = {
        "mmsi": mmsi,
        "received_at": T0 + timedelta(seconds=seconds),
        "lat": 9.35,
        "lon": -79.91,
        "sog": 7.5,
        "cog": 180.0,
        "heading": 181,
        "nav_status": 0,
    }
    return PositionUpdate(**(values | overrides))


def static(mmsi: int = 352000001, **overrides: Any) -> VesselStatic:
    values: dict[str, Any] = {
        "mmsi": mmsi,
        "name": "PACIFIC STAR",
        "imo": 9100001,
        "ship_type": 70,
        "length_m": 225.0,
        "beam_m": 32.0,
    }
    return VesselStatic(**(values | overrides))


@pytest.fixture
async def sessions(migrated: AsyncEngine, db_app: FastAPI) -> AsyncIterator[SessionFactory]:
    factory: SessionFactory = db_app.state.session_factory  # rol canal_app
    yield factory


def make_writer(sessions: SessionFactory, **kwargs: Any) -> AisWriter:
    options: dict[str, Any] = {
        "queue": asyncio.Queue(),
        "session_factory": sessions,
        "retry_base_seconds": 0.001,
        "retry_max_seconds": 0.01,
        "max_attempts": 3,
    }
    return AisWriter(**(options | kwargs))


async def fetch(sessions: SessionFactory, statement: Any) -> list[Any]:
    async with sessions() as session:
        return list((await session.execute(statement)).all())


# --- Escritura ------------------------------------------------------------------------------


async def test_positions_and_vessels_are_written_with_lon_lat_in_order(
    sessions: SessionFactory,
) -> None:
    writer = make_writer(sessions)

    await writer.flush([static(), position(seconds=0), position(seconds=30)])

    rows = await fetch(
        sessions,
        select(
            Position.vessel_mmsi,
            func.ST_X(func.ST_GeomFromWKB(func.ST_AsBinary(Position.geom))),
            func.ST_Y(func.ST_GeomFromWKB(func.ST_AsBinary(Position.geom))),
            Position.sog,
            Position.heading,
        ).order_by(Position.received_at),
    )
    assert len(rows) == 2
    mmsi, x, y, sog, heading = rows[0]
    assert (mmsi, sog, heading) == (352000001, 7.5, 181)
    assert x == pytest.approx(-79.91)  # longitud
    assert y == pytest.approx(9.35)  # latitud
    [vessel] = await fetch(sessions, select(Vessel.name, Vessel.length_m, Vessel.last_seen_at))
    assert vessel == ("PACIFIC STAR", 225.0, T0 + timedelta(seconds=30))
    assert writer.stats.positions_written == 2
    assert writer.stats.vessels_upserted == 1


async def test_a_position_creates_its_vessel_when_it_is_unknown(sessions: SessionFactory) -> None:
    await make_writer(sessions).flush([position(mmsi=636000002)])

    [vessel] = await fetch(sessions, select(Vessel.mmsi, Vessel.name, Vessel.last_seen_at))
    assert vessel == (636000002, None, T0)


async def test_static_data_without_a_name_keeps_the_known_name(sessions: SessionFactory) -> None:
    writer = make_writer(sessions)
    await writer.flush([static(name="PACIFIC STAR")])

    await writer.flush([static(name=None, length_m=None, ship_type=80)])

    [vessel] = await fetch(sessions, select(Vessel.name, Vessel.length_m, Vessel.ship_type))
    assert vessel == ("PACIFIC STAR", 225.0, 80)  # lo nuevo sustituye; lo ausente no borra


async def test_last_seen_only_moves_forward(sessions: SessionFactory) -> None:
    writer = make_writer(sessions)
    await writer.flush([position(seconds=60)])

    await writer.flush([position(seconds=10)])  # llega tarde un mensaje antiguo

    [(last_seen,)] = await fetch(sessions, select(Vessel.last_seen_at))
    assert last_seen == T0 + timedelta(seconds=60)


async def test_repeated_positions_are_ignored_across_batches(sessions: SessionFactory) -> None:
    writer = make_writer(sessions)
    await writer.flush([position(seconds=0), position(seconds=10)])

    await writer.flush([position(seconds=10), position(seconds=20)])

    [(count,)] = await fetch(sessions, select(func.count()).select_from(Position))
    assert count == 3
    assert writer.stats.positions_written == 3
    assert writer.stats.positions_duplicated == 1


async def test_names_are_stored_literally_through_bound_parameters(
    sessions: SessionFactory,
) -> None:
    hostile = "X'); DROP TABLE vessels;--"

    await make_writer(sessions).flush([static(name=hostile)])

    assert await fetch(sessions, select(Vessel.name)) == [(hostile,)]


# --- Fallos ---------------------------------------------------------------------------------


async def test_failed_batch_leaves_nothing_behind(
    sessions: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Los buques ya se upsertaron cuando fallan las posiciones: el rollback debe deshacerlos.
    async def broken_insert(self: AisRepository, rows: Any) -> int:
        raise OSError("conexión perdida")

    monkeypatch.setattr(AisRepository, "insert_positions", broken_insert)
    writer = make_writer(sessions)

    await writer.flush([static(), position()])

    assert await fetch(sessions, select(Vessel.mmsi)) == []
    assert writer.stats.batches_dropped == 1
    assert writer.stats.batches_retried == 3


async def test_a_row_the_database_refuses_does_not_lose_the_rest_of_the_batch(
    sessions: SessionFactory,
) -> None:
    # heading 400 no pasa el parser, pero si se colara, el CHECK de la base lo rechaza.
    writer = make_writer(sessions)

    await writer.flush(
        [position(seconds=0), position(seconds=10, heading=400), position(seconds=20)]
    )

    rows = await fetch(sessions, select(Position.heading).order_by(Position.received_at))
    assert rows == [(181,), (181,)]
    assert writer.stats.rows_rejected_by_db == 1
    assert writer.stats.positions_written == 2
    assert writer.stats.batches_dropped == 0


async def test_a_vessel_the_database_refuses_drops_only_its_positions(
    sessions: SessionFactory,
) -> None:
    writer = make_writer(sessions)

    await writer.flush(
        [
            static(mmsi=352000001, ship_type=150),  # fuera del CHECK de vessels
            position(mmsi=352000001),
            position(mmsi=636000002),
        ]
    )

    assert await fetch(sessions, select(Position.vessel_mmsi)) == [(636000002,)]
    assert writer.stats.rows_rejected_by_db == 2  # el buque y su posición


# --- Permisos -------------------------------------------------------------------------------


async def test_writer_runs_as_the_app_role_without_ddl(sessions: SessionFactory) -> None:
    [(role,)] = await fetch(sessions, text("SELECT current_user"))
    assert role == "canal_app"

    await make_writer(sessions).flush([static(), position()])

    assert await fetch(sessions, select(Vessel.mmsi)) == [(352000001,)]


# --- Worker completo: simulador → consumer → writer → PostgreSQL ----------------------------


async def test_worker_stores_simulated_traffic_end_to_end(
    migrated: AsyncEngine, db_settings: Settings, sessions: SessionFactory
) -> None:
    sim = load_script("ais_simulator")
    messages = sim.generate(start=T0, duration=timedelta(minutes=10), seed=1, invalid_ratio=0.05)
    server = await sim.start_server(messages, port=0, speed=0)
    port = next(iter(server.sockets)).getsockname()[1]
    settings = db_settings.model_copy(
        update={
            "aisstream_url": f"ws://127.0.0.1:{port}",
            # model_copy no valida: la key tiene que llegar ya como SecretStr.
            "aisstream_api_key": SecretStr("clave-de-pruebas"),
            "ais_batch_size": 50,
            "ais_batch_flush_seconds": 0.05,
        }
    )
    stop = asyncio.Event()
    try:
        task = asyncio.create_task(run_worker(settings, stop))
        async with asyncio.timeout(10):
            while True:
                if task.done():
                    task.result()  # si el worker murió, que el test diga por qué
                [(count,)] = await fetch(sessions, select(func.count()).select_from(Position))
                if count >= 100:
                    break
                await asyncio.sleep(0.05)
        stop.set()
        stats = await asyncio.wait_for(task, timeout=10)
    finally:
        server.close()
        await server.wait_closed()

    [(positions,)] = await fetch(sessions, select(func.count()).select_from(Position))
    [(vessels,)] = await fetch(sessions, select(func.count()).select_from(Vessel))
    assert positions >= 100
    assert vessels == len(sim.DEFAULT_FLEET)
    assert sum(stats.rejected.values()) > 0  # los inválidos no llegan a la base
    [(names,)] = await fetch(sessions, select(func.count()).where(Vessel.name.is_not(None)))
    assert names == len(sim.DEFAULT_FLEET)  # nombres sin el relleno '@'
    assert await fetch(sessions, select(Vessel.name).where(Vessel.name.contains("@"))) == []


def test_writer_module_never_builds_sql_from_strings() -> None:
    # Refuerzo local del test de arquitectura: el writer solo usa el repositorio.
    source = ais_writer.__file__
    with open(source, encoding="utf-8") as handle:
        content = handle.read()
    assert "text(" not in content
    assert "execute(" not in content


async def test_a_failing_commit_hook_never_undoes_or_retries_the_batch(
    sessions: SessionFactory,
) -> None:
    calls = 0

    async def broken_hook(batch: Any) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("fallo inesperado del publisher")

    writer = make_writer(sessions, on_committed=broken_hook)

    await writer.flush([static(), position()])

    assert calls == 1  # ni reintentos ni nada que rehacer: la base ya tiene los datos
    assert await fetch(sessions, select(Position.vessel_mmsi)) == [(352000001,)]
    assert writer.stats.batches_retried == 0
    assert writer.stats.batches_dropped == 0
