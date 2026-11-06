"""Agregado continuo `positions_hourly` (6.3) contra TimescaleDB real."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import SessionFactory
from app.repositories.ais import AisRepository, PositionRow, VesselRow

HOUR = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
QUERY = text(
    "SELECT bucket, vessel_mmsi, positions, avg_sog, max_sog "
    "FROM positions_hourly ORDER BY bucket, vessel_mmsi"
)


@pytest.fixture
async def sessions(migrated: AsyncEngine, db_app: FastAPI) -> AsyncIterator[SessionFactory]:
    factory: SessionFactory = db_app.state.session_factory  # rol canal_app
    yield factory


def row(mmsi: int, minutes: int, sog: float | None) -> PositionRow:
    return PositionRow(
        received_at=HOUR + timedelta(minutes=minutes),
        mmsi=mmsi,
        lat=9.35,
        lon=-79.91,
        sog=sog,
        cog=180.0,
        heading=180,
        nav_status=0,
    )


async def seed(sessions: SessionFactory, rows: list[PositionRow]) -> None:
    async with sessions() as session:
        repository = AisRepository(session)
        await repository.upsert_vessels(
            [VesselRow(mmsi=mmsi) for mmsi in sorted({item.mmsi for item in rows})]
        )
        await repository.insert_positions(rows)
        await session.commit()


async def hourly(sessions: SessionFactory) -> list[Any]:
    async with sessions() as session:
        return [tuple(item) for item in (await session.execute(QUERY)).all()]


SAMPLE = [
    row(352000001, 5, 6.0),
    row(352000001, 25, 8.0),
    row(352000001, 70, 4.0),  # la hora siguiente
    row(352000002, 10, 0.0),
    row(352000002, 20, None),  # sin velocidad: no cuenta para la media
]


async def test_the_hourly_view_groups_by_vessel_and_hour_before_any_refresh(
    sessions: SessionFactory,
) -> None:
    # Con `materialized_only = false` lo que aún no se ha materializado también se ve.
    await seed(sessions, SAMPLE)

    assert await hourly(sessions) == [
        (HOUR, 352000001, 2, 7.0, 8.0),
        (HOUR, 352000002, 2, 0.0, 0.0),
        (HOUR + timedelta(hours=1), 352000001, 1, 4.0, 4.0),
    ]


WATERMARK_PASSED_SAMPLE = text(
    "SELECT _timescaledb_functions.to_timestamp(_timescaledb_functions.cagg_watermark("
    "(SELECT (config->>'mat_hypertable_id')::int FROM timescaledb_information.jobs "
    "WHERE proc_name = 'policy_refresh_continuous_aggregate' "
    "AND hypertable_name = 'positions_hourly'))) > :hour"
)


async def refresh(migrated: AsyncEngine) -> None:
    # `refresh_continuous_aggregate` no puede correr dentro de una transacción.
    async with migrated.connect() as connection:
        connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await connection.execute(
            text("CALL refresh_continuous_aggregate('positions_hourly', NULL, NULL)")
        )


async def watermark_passed_the_sample(migrated: AsyncEngine) -> bool:
    async with migrated.connect() as connection:
        return bool(
            (await connection.execute(WATERMARK_PASSED_SAMPLE, {"hour": HOUR})).scalar_one()
        )


async def test_a_refresh_materializes_the_same_numbers(
    sessions: SessionFactory, migrated: AsyncEngine
) -> None:
    await seed(sessions, SAMPLE)
    before = await hourly(sessions)
    assert not await watermark_passed_the_sample(migrated)

    await refresh(migrated)

    # Ahora lo calculado sale de la tabla materializada (la marca de agua avanzó) y da lo mismo.
    assert await watermark_passed_the_sample(migrated)
    assert await hourly(sessions) == before


async def test_positions_after_the_watermark_are_added_in_real_time(
    sessions: SessionFactory, migrated: AsyncEngine
) -> None:
    await seed(sessions, SAMPLE)
    await refresh(migrated)

    # Una posición en una hora posterior a la marca de agua: sin refrescar, ya se ve.
    await seed(sessions, [row(352000001, 60 * 5 + 10, 10.0)])

    assert (await hourly(sessions))[-1] == (HOUR + timedelta(hours=5), 352000001, 1, 10.0, 10.0)


async def test_a_late_position_in_a_materialized_hour_shows_up_at_the_next_refresh(
    sessions: SessionFactory, migrated: AsyncEngine
) -> None:
    # Límite conocido: el tiempo real solo suma lo posterior a la marca de agua. Una posición que
    # llega tarde a una hora ya materializada espera al siguiente refresco (cada 30 minutos).
    await seed(sessions, SAMPLE)
    await refresh(migrated)

    await seed(sessions, [row(352000001, 45, 10.0)])
    assert (await hourly(sessions))[0] == (HOUR, 352000001, 2, 7.0, 8.0)

    await refresh(migrated)
    assert (await hourly(sessions))[0] == (HOUR, 352000001, 3, 8.0, 10.0)


async def test_the_view_is_real_time_with_a_refresh_policy(migrated: AsyncEngine) -> None:
    async with migrated.connect() as connection:
        view = (
            await connection.execute(
                text(
                    "SELECT materialized_only FROM timescaledb_information.continuous_aggregates "
                    "WHERE view_name = 'positions_hourly'"
                )
            )
        ).one()
        jobs = (
            await connection.execute(
                text(
                    "SELECT schedule_interval, config->>'start_offset', config->>'end_offset' "
                    "FROM timescaledb_information.jobs "
                    "WHERE proc_name = 'policy_refresh_continuous_aggregate' "
                    "AND hypertable_name = 'positions_hourly'"
                )
            )
        ).all()

    assert view.materialized_only is False
    [job] = jobs
    assert job[0] == timedelta(minutes=30)
    assert job[1] is None  # sin límite por detrás: el primer refresco cubre todo el histórico
    assert job[2] == "01:00:00"


async def test_the_app_role_reads_the_view_but_cannot_change_it(
    sessions: SessionFactory,
) -> None:
    await seed(sessions, SAMPLE)

    with pytest.raises(ProgrammingError, match=r"must be owner"):
        async with sessions() as session:
            await session.execute(text("DROP MATERIALIZED VIEW positions_hourly"))

    assert len(await hourly(sessions)) == 3
