"""Compresión de `positions` y agregado `positions_5min` (6.5) contra TimescaleDB real."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from alembic import command
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import SessionFactory
from app.repositories.ais import AisRepository, PositionRow, VesselRow
from app.repositories.vessels import VesselRepository
from tests.integration.alembic_helpers import alembic

MMSI = 352000001
OLD = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(days=30)


@pytest.fixture
async def sessions(migrated: AsyncEngine, db_app: FastAPI) -> AsyncIterator[SessionFactory]:
    factory: SessionFactory = db_app.state.session_factory  # rol canal_app
    yield factory


def row(minutes: int, *, mmsi: int = MMSI, sog: float = 5.0, lon: float = -79.9) -> PositionRow:
    return PositionRow(
        received_at=OLD + timedelta(minutes=minutes),
        mmsi=mmsi,
        lat=9.3,
        lon=lon,
        sog=sog,
        cog=180.0,
        heading=180,
        nav_status=0,
    )


async def seed(sessions: SessionFactory, rows: list[PositionRow]) -> int:
    async with sessions() as session:
        repository = AisRepository(session)
        await repository.upsert_vessels(
            [VesselRow(mmsi=mmsi) for mmsi in sorted({item.mmsi for item in rows})]
        )
        written = await repository.insert_positions(rows)
        await session.commit()
    return written


async def autocommit(engine: AsyncEngine, statement: str) -> Any:
    async with engine.connect() as connection:
        connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
        result = await connection.execute(text(statement))
        return result.all() if result.returns_rows else None


async def compress(engine: AsyncEngine) -> None:
    # La política de compresión (recién creada por la migración) puede adelantarse y comprimir el
    # chunk viejo antes que el test: por eso `if_not_compressed`.
    await autocommit(
        engine,
        "SELECT compress_chunk(c, if_not_compressed => true) FROM show_chunks('positions') AS c",
    )


async def compressed_chunks(engine: AsyncEngine) -> int:
    rows = await autocommit(
        engine,
        "SELECT count(*) FROM timescaledb_information.chunks "
        "WHERE hypertable_name = 'positions' AND is_compressed",
    )
    return int(rows[0][0])


async def stored(sessions: SessionFactory) -> list[tuple[Any, ...]]:
    async with sessions() as session:
        result = await session.execute(
            text(
                "SELECT received_at, vessel_mmsi, ST_X(geom::geometry), ST_Y(geom::geometry), "
                "sog, cog, heading, nav_status FROM positions ORDER BY vessel_mmsi, received_at"
            )
        )
        return [tuple(item) for item in result.all()]


SAMPLE = [row(m) for m in range(0, 60, 5)] + [row(m, mmsi=352000002, sog=0.0) for m in (0, 30)]


# --- Configuración --------------------------------------------------------------------------


async def test_compression_is_configured_by_vessel_with_a_seven_day_policy(
    migrated: AsyncEngine,
) -> None:
    enabled = await autocommit(
        migrated,
        "SELECT compression_enabled FROM timescaledb_information.hypertables "
        "WHERE hypertable_name = 'positions'",
    )
    policy = await autocommit(
        migrated,
        "SELECT config->>'compress_after' FROM timescaledb_information.jobs "
        "WHERE proc_name = 'policy_compression' AND hypertable_name = 'positions'",
    )
    segmentby = await autocommit(
        migrated,
        "SELECT attname FROM timescaledb_information.compression_settings "
        "WHERE hypertable_name = 'positions' AND segmentby_column_index IS NOT NULL",
    )

    assert enabled == [(True,)]
    assert policy == [("7 days",)]
    assert segmentby == [("vessel_mmsi",)]


# --- Leer y escribir sobre chunks comprimidos -----------------------------------------------


async def test_compressing_a_chunk_loses_nothing(
    sessions: SessionFactory, migrated: AsyncEngine
) -> None:
    await seed(sessions, SAMPLE)
    before = await stored(sessions)

    await compress(migrated)

    assert await compressed_chunks(migrated) >= 1
    assert await stored(sessions) == before
    assert len(before) == len(SAMPLE)


async def test_the_api_queries_still_read_compressed_chunks(
    sessions: SessionFactory, migrated: AsyncEngine
) -> None:
    await seed(sessions, SAMPLE)
    await compress(migrated)

    async with sessions() as session:
        points, truncated = await VesselRepository(session).track(
            MMSI, start=OLD - timedelta(hours=1), end=OLD + timedelta(hours=2), limit=100
        )
        last = await VesselRepository(session).last_position(MMSI)

    assert [point.received_at for point in points] == [row(m).received_at for m in range(0, 60, 5)]
    assert truncated is False
    assert last is not None and last.received_at == row(55).received_at


async def test_a_duplicate_in_a_compressed_chunk_is_ignored_like_in_a_normal_one(
    sessions: SessionFactory, migrated: AsyncEngine
) -> None:
    await seed(sessions, SAMPLE)
    await compress(migrated)

    written = await seed(sessions, [row(0), row(5, sog=99.0)])  # los dos ya existían

    assert written == 0
    assert len(await stored(sessions)) == len(SAMPLE)
    assert all(item[4] != 99.0 for item in await stored(sessions))  # el original no se pisa


async def test_a_new_position_is_accepted_in_a_compressed_chunk(
    sessions: SessionFactory, migrated: AsyncEngine
) -> None:
    await seed(sessions, SAMPLE)
    await compress(migrated)

    # Una posición repetida y otra nueva en el mismo lote: solo entra la nueva.
    written = await seed(sessions, [row(0), row(7, sog=3.0)])

    assert written == 1
    rows = await stored(sessions)
    assert len(rows) == len(SAMPLE) + 1
    assert [item[0] for item in rows if item[1] == MMSI][:3] == [
        OLD,
        OLD + timedelta(minutes=5),
        OLD + timedelta(minutes=7),
    ]


# --- positions_5min -------------------------------------------------------------------------


async def refresh_5min(engine: AsyncEngine) -> None:
    await autocommit(engine, "CALL refresh_continuous_aggregate('positions_5min', NULL, NULL)")


async def five_minutes(sessions: SessionFactory) -> list[tuple[Any, ...]]:
    async with sessions() as session:
        result = await session.execute(
            text(
                "SELECT bucket, vessel_mmsi, positions, ST_X(geom::geometry), sog, cog, "
                "nav_status FROM positions_5min ORDER BY vessel_mmsi, bucket"
            )
        )
        return [tuple(item) for item in result.all()]


async def test_the_five_minute_history_keeps_the_last_position_of_each_vessel_and_bucket(
    sessions: SessionFactory, migrated: AsyncEngine
) -> None:
    await seed(
        sessions,
        [
            row(0, sog=1.0, lon=-79.90),
            row(2, sog=2.0, lon=-79.91),
            row(4, sog=3.0, lon=-79.92),  # la última del tramo 0-5
            row(5, sog=4.0, lon=-79.93),
            row(0, mmsi=352000002, sog=9.0, lon=-79.50),
        ],
    )

    await refresh_5min(migrated)

    rows = await five_minutes(sessions)
    assert [(item[0], item[1], item[2], item[3], item[4]) for item in rows] == [
        (OLD, MMSI, 3, pytest.approx(-79.92), 3.0),
        (OLD + timedelta(minutes=5), MMSI, 1, pytest.approx(-79.93), 4.0),
        (OLD, 352000002, 1, pytest.approx(-79.50), 9.0),
    ]
    assert rows[0][5:] == (180.0, 0)


async def test_the_five_minute_history_is_materialized_only_and_has_a_policy(
    migrated: AsyncEngine,
) -> None:
    view = await autocommit(
        migrated,
        "SELECT materialized_only FROM timescaledb_information.continuous_aggregates "
        "WHERE view_name = 'positions_5min'",
    )
    job = await autocommit(
        migrated,
        "SELECT schedule_interval, config->>'start_offset', config->>'end_offset' "
        "FROM timescaledb_information.jobs "
        "WHERE proc_name = 'policy_refresh_continuous_aggregate' "
        "AND hypertable_name = 'positions_5min'",
    )

    assert view == [(True,)]
    assert job == [(timedelta(hours=1), None, "01:00:00")]


async def test_the_five_minute_history_survives_compressing_the_source(
    sessions: SessionFactory, migrated: AsyncEngine
) -> None:
    await seed(sessions, SAMPLE)
    await refresh_5min(migrated)
    before = await five_minutes(sessions)

    await compress(migrated)
    await refresh_5min(migrated)

    assert await five_minutes(sessions) == before


# --- Migración ------------------------------------------------------------------------------


async def test_downgrading_with_compressed_chunks_keeps_the_data(
    sessions: SessionFactory, migrated: AsyncEngine
) -> None:
    await seed(sessions, SAMPLE)
    await compress(migrated)
    before = await stored(sessions)
    assert await compressed_chunks(migrated) >= 1

    async with migrated.begin() as connection:
        await connection.run_sync(alembic(command.downgrade, "20261106_0006"))

    assert await compressed_chunks(migrated) == 0
    assert await stored(sessions) == before
    enabled = await autocommit(
        migrated,
        "SELECT compression_enabled FROM timescaledb_information.hypertables "
        "WHERE hypertable_name = 'positions'",
    )
    views = await autocommit(
        migrated,
        "SELECT view_name FROM timescaledb_information.continuous_aggregates ORDER BY view_name",
    )
    assert enabled == [(False,)]
    assert views == [("positions_hourly",)]

    # Y se puede volver a subir sin perder nada.
    async with migrated.begin() as connection:
        await connection.run_sync(alembic(command.upgrade, "head"))
    assert await stored(sessions) == before
    await compress(migrated)
    assert await compressed_chunks(migrated) >= 1
