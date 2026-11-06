"""`GET /api/v1/stats/*` contra PostgreSQL real."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import SessionFactory
from app.core.security import create_access_token, hash_password
from app.models.user import UserRole
from app.models.vessel import Vessel
from app.repositories.ais import AisRepository, VesselRow
from app.repositories.anchorages import AnchorageRepository, ClosedVisitRow
from app.repositories.stats import category_expression
from app.repositories.transits import ClosedTransitRow, OpenTransitRow, TransitRepository
from app.repositories.user import UserRepository
from app.services.ship_categories import ship_category

STATS = "/api/v1/stats"
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


@pytest.fixture
async def app(migrated: AsyncEngine, db_app: FastAPI) -> AsyncIterator[FastAPI]:
    yield db_app


@pytest.fixture
def sessions(app: FastAPI) -> SessionFactory:
    factory: SessionFactory = app.state.session_factory
    return factory


@pytest.fixture
async def client(app: FastAPI, sessions: SessionFactory) -> AsyncIterator[AsyncClient]:
    async with sessions() as session:
        user = await UserRepository(session).add(
            email="ana@example.com",
            hashed_password=hash_password("una frase larga de prueba"),
            role=UserRole.USER,
        )
        await session.commit()
    token, _ = create_access_token(user.id, app.state.settings)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        yield c


def at(day: int, hour: float = 0) -> datetime:
    """`day` días antes de `NOW` a medianoche UTC, más `hour` horas."""
    return NOW.replace(hour=0) - timedelta(days=day) + timedelta(hours=hour)


async def add_vessels(sessions: SessionFactory, types: dict[int, int | None]) -> None:
    async with sessions() as session:
        await AisRepository(session).upsert_vessels(
            [VesselRow(mmsi=mmsi, ship_type=ship_type) for mmsi, ship_type in types.items()]
        )
        await session.commit()


async def add_transit(
    sessions: SessionFactory,
    mmsi: int,
    direction: str,
    entered: datetime,
    minutes: int | None,
    *,
    status: str = "completed",
) -> None:
    """Un tránsito que dura `minutes` (o abierto si es `None`)."""
    async with sessions() as session:
        repository = TransitRepository(session)
        if minutes is None:
            await repository.open_transit(OpenTransitRow(mmsi, direction, entered))
        else:
            await repository.close_transit(
                ClosedTransitRow(
                    mmsi,
                    direction,
                    status,
                    "timeout" if status == "aborted" else None,
                    entered,
                    entered + timedelta(minutes=minutes),
                )
            )
        await session.commit()


async def get(client: AsyncClient, path: str, **params: Any) -> Any:
    return await client.get(f"{STATS}{path}", params=params)


def window(start: datetime, end: datetime) -> dict[str, str]:
    return {"from": start.isoformat(), "to": end.isoformat()}


# --- Auth y ventana -------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/daily", "/transit-durations", "/waiting-times"])
async def test_every_stats_route_requires_a_token(app: FastAPI, path: str) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as anonymous:
        response = await anonymous.get(f"{STATS}{path}")

    assert response.status_code == 401


@pytest.mark.parametrize("path", ["/daily", "/transit-durations", "/waiting-times"])
@pytest.mark.parametrize(
    "params",
    [
        {"unknown": "x"},
        {"from": "2026-11-01T00:00:00"},  # sin zona horaria
        {"from": (datetime.now(UTC) + timedelta(days=1)).isoformat()},  # después de `to`
        {"from": (datetime.now(UTC) - timedelta(days=366)).isoformat()},  # más de 365 días
        {"to": "ayer"},
    ],
)
async def test_invalid_windows_are_422(
    client: AsyncClient, path: str, params: dict[str, Any]
) -> None:
    response = await get(client, path, **params)

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize("path", ["/daily", "/transit-durations", "/waiting-times"])
async def test_the_default_window_is_the_last_30_days_and_is_echoed(
    client: AsyncClient, path: str
) -> None:
    body = (await get(client, path)).json()

    start = datetime.fromisoformat(body["from"])
    end = datetime.fromisoformat(body["to"])
    assert end - start == timedelta(days=30)
    assert abs(end - datetime.now(UTC)) < timedelta(minutes=1)


# --- /stats/daily ---------------------------------------------------------------------------


async def test_daily_counts_completed_transits_by_exit_day_direction_and_category(
    client: AsyncClient, sessions: SessionFactory
) -> None:
    await add_vessels(sessions, {352000001: 70, 352000002: 70, 352000003: 80, 352000004: None})
    await add_transit(sessions, 352000001, "southbound", at(3, 2), 480)
    await add_transit(sessions, 352000002, "southbound", at(3, 5), 480)
    await add_transit(sessions, 352000003, "northbound", at(3, 6), 400)
    # Entra el día 3 y sale pasada la medianoche UTC: cuenta en el día de la salida (el 2).
    await add_transit(sessions, 352000004, "southbound", at(3, 20), 480)

    response = await get(client, "/daily", **window(at(10), at(0)))

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "date": at(3).date().isoformat(),
            "direction": "northbound",
            "ship_category": "tanker",
            "transits": 1,
        },
        {
            "date": at(3).date().isoformat(),
            "direction": "southbound",
            "ship_category": "cargo",
            "transits": 2,
        },
        {
            "date": at(2).date().isoformat(),
            "direction": "southbound",
            "ship_category": "unknown",
            "transits": 1,
        },
    ]


async def test_daily_ignores_open_and_aborted_transits_and_other_windows(
    client: AsyncClient, sessions: SessionFactory
) -> None:
    await add_vessels(sessions, {352000001: 70, 352000002: 70, 352000003: 70, 352000004: 70})
    await add_transit(sessions, 352000001, "southbound", at(3), None)  # abierto
    await add_transit(sessions, 352000002, "southbound", at(3), 60, status="aborted")
    await add_transit(sessions, 352000003, "southbound", at(40), 480)  # fuera de la ventana
    await add_transit(sessions, 352000004, "southbound", at(3), 480)

    body = (await get(client, "/daily", **window(at(10), at(0)))).json()

    assert [(item["ship_category"], item["transits"]) for item in body["items"]] == [("cargo", 1)]


async def test_daily_window_is_half_open_on_the_exit_time(
    client: AsyncClient, sessions: SessionFactory
) -> None:
    await add_vessels(sessions, {352000001: 70, 352000002: 70})
    await add_transit(sessions, 352000001, "southbound", at(5), 60)  # sale en at(5, 1)
    await add_transit(sessions, 352000002, "southbound", at(4), 60)  # sale en at(4, 1)

    inclusive_start = (await get(client, "/daily", **window(at(5, 1), at(4, 1)))).json()
    assert [item["transits"] for item in inclusive_start["items"]] == [
        1
    ]  # el primero, no el segundo


async def test_daily_is_empty_without_transits(client: AsyncClient) -> None:
    body = (await get(client, "/daily")).json()

    assert body["items"] == []


# --- /stats/transit-durations ---------------------------------------------------------------


async def test_durations_have_mean_and_percentiles_in_total_and_per_direction(
    client: AsyncClient, sessions: SessionFactory
) -> None:
    await add_vessels(sessions, {352000000 + n: 70 for n in range(1, 8)})
    south = [60, 120, 180, 240, 300]
    for n, minutes in enumerate(south, start=1):
        await add_transit(sessions, 352000000 + n, "southbound", at(3, n), minutes)
    await add_transit(sessions, 352000006, "northbound", at(3, 1), 500)
    await add_transit(sessions, 352000007, "northbound", at(3, 2), 400)

    body = (await get(client, "/transit-durations", **window(at(10), at(0)))).json()

    assert body["by_direction"]["southbound"] == {
        "count": 5,
        "mean_minutes": 180.0,
        "p50_minutes": 180.0,
        "p90_minutes": 276.0,
    }
    assert body["by_direction"]["northbound"] == {
        "count": 2,
        "mean_minutes": 450.0,
        "p50_minutes": 450.0,
        "p90_minutes": 490.0,
    }
    assert body["overall"]["count"] == 7
    assert body["overall"]["mean_minutes"] == pytest.approx(257.1)
    assert body["overall"]["p50_minutes"] == 240.0


async def test_durations_without_transits_give_zero_counts_and_nulls_for_both_directions(
    client: AsyncClient,
) -> None:
    body = (await get(client, "/transit-durations")).json()

    empty = {"count": 0, "mean_minutes": None, "p50_minutes": None, "p90_minutes": None}
    assert body["overall"] == empty
    assert body["by_direction"] == {"northbound": empty, "southbound": empty}


async def test_durations_with_one_direction_still_list_the_other_as_empty(
    client: AsyncClient, sessions: SessionFactory
) -> None:
    await add_vessels(sessions, {352000001: 70})
    await add_transit(sessions, 352000001, "southbound", at(3), 360)

    body = (await get(client, "/transit-durations", **window(at(10), at(0)))).json()

    assert body["by_direction"]["southbound"]["count"] == 1
    assert body["by_direction"]["northbound"]["count"] == 0
    assert body["by_direction"]["northbound"]["p90_minutes"] is None


# --- /stats/waiting-times -------------------------------------------------------------------


async def add_wait(
    sessions: SessionFactory,
    mmsi: int,
    anchorage: str,
    direction: str,
    entered: datetime,
    wait_minutes: int,
    *,
    status: str = "completed",
) -> None:
    """Una visita de `wait_minutes` enlazada con el tránsito que empieza en `entered`."""
    await add_transit(sessions, mmsi, direction, entered, 480, status=status)
    async with sessions() as session:
        repository = AnchorageRepository(session)
        await repository.close_visit(
            ClosedVisitRow(
                mmsi,
                anchorage,
                entered - timedelta(minutes=wait_minutes),
                entered - timedelta(minutes=1),
            )
        )
        [visit] = [v for v in await repository.unlinked_visits(at(100)) if v.mmsi == mmsi]
        [candidate] = [t for t in await repository.unlinked_transits(at(100)) if t.mmsi == mmsi]
        assert await repository.link(visit.id, candidate.id)
        await session.commit()


async def test_waiting_times_have_mean_and_percentiles_in_total_and_per_anchorage(
    client: AsyncClient, sessions: SessionFactory
) -> None:
    await add_vessels(sessions, {352000000 + n: 70 for n in range(1, 8)})
    for n, minutes in enumerate([60, 120, 180, 240, 300], start=1):
        await add_wait(sessions, 352000000 + n, "atlantic", "southbound", at(3, n), minutes)
    await add_wait(sessions, 352000006, "pacific", "northbound", at(3, 1), 600)
    await add_wait(sessions, 352000007, "pacific", "northbound", at(3, 2), 800, status="aborted")

    body = (await get(client, "/waiting-times", **window(at(10), at(0)))).json()

    assert body["by_anchorage"]["atlantic"] == {
        "count": 5,
        "mean_minutes": 180.0,
        "p50_minutes": 180.0,
        "p90_minutes": 276.0,
    }
    # Cuenta también el abortado.
    assert body["by_anchorage"]["pacific"] == {
        "count": 2,
        "mean_minutes": 700.0,
        "p50_minutes": 700.0,
        "p90_minutes": 780.0,
    }
    assert body["overall"]["count"] == 7


async def test_waiting_times_ignore_transits_without_a_linked_visit_and_other_windows(
    client: AsyncClient, sessions: SessionFactory
) -> None:
    await add_vessels(sessions, {352000001: 70, 352000002: 70})
    await add_transit(sessions, 352000001, "southbound", at(3), 480)  # sin visita
    await add_wait(sessions, 352000002, "atlantic", "southbound", at(40), 90)  # otra ventana

    body = (await get(client, "/waiting-times", **window(at(10), at(0)))).json()

    assert body["overall"]["count"] == 0
    assert body["by_anchorage"]["atlantic"]["count"] == 0


# --- Categorías -----------------------------------------------------------------------------


async def test_the_sql_categories_match_the_python_rules_for_every_ship_type(
    sessions: SessionFactory,
) -> None:
    types: dict[int, int | None] = {352000000 + code: code for code in range(100)}
    types[353000000] = None
    await add_vessels(sessions, types)

    async with sessions() as session:
        rows = (
            await session.execute(select(Vessel.mmsi, Vessel.ship_type, category_expression()))
        ).all()

    assert len(rows) == 101
    assert {(ship_type, category) for _, ship_type, category in rows} == {
        (ship_type, ship_category(ship_type)) for ship_type in types.values()
    }
