from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine


async def test_vessel_and_position_schema_uses_timescale_and_spatial_indexes(
    migrated: AsyncEngine,
) -> None:
    async with migrated.connect() as connection:
        hypertable = (
            await connection.execute(
                text(
                    "SELECT hypertable_name FROM timescaledb_information.hypertables "
                    "WHERE hypertable_name = 'positions'"
                )
            )
        ).scalar_one_or_none()
        indexes = {
            row.indexname
            for row in (
                await connection.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = 'public' AND tablename IN ('vessels', 'positions')"
                    )
                )
            )
        }

    assert hypertable == "positions"
    assert {
        "ix_vessels_last_seen_at",
        "ix_positions_geom",
        "ix_positions_vessel_mmsi_received_at",
    } <= indexes


async def test_app_role_can_write_valid_vessel_and_position(
    migrated: AsyncEngine, db_app: FastAPI
) -> None:
    timestamp = datetime.now(UTC)
    async with db_app.state.session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO vessels (mmsi, name, ship_type, last_seen_at) "
                "VALUES (:mmsi, :name, :ship_type, :last_seen_at)"
            ),
            {
                "mmsi": 352001234,
                "name": "PACIFIC STAR",
                "ship_type": 70,
                "last_seen_at": timestamp,
            },
        )
        await session.execute(
            text(
                "INSERT INTO positions "
                "(received_at, vessel_mmsi, geom, sog, cog, heading, nav_status) "
                "VALUES (:received_at, :mmsi, ST_GeogFromText(:point), :sog, :cog, "
                ":heading, :nav_status)"
            ),
            {
                "received_at": timestamp,
                "mmsi": 352001234,
                "point": "SRID=4326;POINT(-79.9 9.3)",
                "sog": 7.5,
                "cog": 180.0,
                "heading": 181,
                "nav_status": 0,
            },
        )
        await session.commit()

        position = (
            await session.execute(
                text(
                    "SELECT ST_AsText(geom), sog FROM positions "
                    "WHERE vessel_mmsi = :mmsi AND received_at = :received_at"
                ),
                {"mmsi": 352001234, "received_at": timestamp},
            )
        ).one()

    assert position == ("POINT(-79.9 9.3)", 7.5)


@pytest.mark.parametrize(
    ("table", "column", "value"),
    [
        ("vessels", "mmsi", 123),
        ("positions", "vessel_mmsi", 123),
    ],
)
async def test_mmsi_constraints_reject_invalid_values(
    migrated: AsyncEngine,
    table: str,
    column: str,
    value: int,
) -> None:
    statement = (
        text("INSERT INTO vessels (mmsi, name) VALUES (:value, 'BAD')")
        if table == "vessels"
        else text(
            "INSERT INTO positions (received_at, vessel_mmsi, geom) "
            "VALUES (:received_at, :value, ST_GeogFromText('SRID=4326;POINT(-79.9 9.3)'))"
        )
    )
    parameters = {"value": value, "received_at": datetime.now(UTC)}

    async with migrated.connect() as connection:
        with pytest.raises(IntegrityError):
            await connection.execute(statement, parameters)
