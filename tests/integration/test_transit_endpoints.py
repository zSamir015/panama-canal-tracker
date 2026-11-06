"""`GET /api/v1/transits` contra PostgreSQL real."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import SessionFactory
from app.core.security import create_access_token, hash_password
from app.models.user import UserRole
from app.repositories.ais import AisRepository, VesselRow
from app.repositories.anchorages import AnchorageRepository, ClosedVisitRow
from app.repositories.transits import ClosedTransitRow, OpenTransitRow, TransitRepository
from app.repositories.user import UserRepository

TRANSITS = "/api/v1/transits"
NOW = datetime.now(UTC).replace(microsecond=0)
FIELDS = {
    "id",
    "mmsi",
    "vessel_name",
    "ship_type",
    "direction",
    "status",
    "abort_reason",
    "entered_at",
    "exited_at",
    "duration_minutes",
}


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


def ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


async def seed(
    sessions: SessionFactory,
    *,
    completed: list[tuple[int, str, float, float]] = (),  # type: ignore[assignment]
    aborted: list[tuple[int, str, str, float, float]] = (),  # type: ignore[assignment]
    open_: list[tuple[int, str, float]] = (),  # type: ignore[assignment]
) -> None:
    """Crea los buques y sus tránsitos. Los tiempos son horas atrás: (entrada, salida)."""
    mmsis = {m for m, *_ in completed} | {m for m, *_ in aborted} | {m for m, *_ in open_}
    async with sessions() as session:
        await AisRepository(session).upsert_vessels(
            [
                VesselRow(mmsi=m, name=f"VESSEL {m}", ship_type=70, last_seen_at=NOW)
                for m in sorted(mmsis)
            ]
        )
        repository = TransitRepository(session)
        for mmsi, direction, entered, exited in completed:
            await repository.close_transit(
                ClosedTransitRow(mmsi, direction, "completed", None, ago(entered), ago(exited))
            )
        for mmsi, direction, reason, entered, exited in aborted:
            await repository.close_transit(
                ClosedTransitRow(mmsi, direction, "aborted", reason, ago(entered), ago(exited))
            )
        for mmsi, direction, entered in open_:
            await repository.open_transit(OpenTransitRow(mmsi, direction, ago(entered)))
        await session.commit()


async def get(client: AsyncClient, url: str, **params: Any) -> Any:
    response = await client.get(url, params=params)
    return response


# --- Auth -----------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["", "/current", f"/{uuid4()}"])
async def test_every_transit_route_requires_a_token(app: FastAPI, path: str) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as anonymous:
        response = await anonymous.get(f"{TRANSITS}{path}")

    assert response.status_code == 401


# --- GET /transits --------------------------------------------------------------------------


async def test_lists_transits_most_recent_entry_first_with_vessel_data(
    client: AsyncClient, sessions: SessionFactory
) -> None:
    await seed(
        sessions,
        completed=[(352000001, "southbound", 30, 22), (352000002, "northbound", 10, 2)],
        aborted=[(352000003, "southbound", "timeout", 20, 19)],
        open_=[(352000004, "northbound", 1)],
    )

    response = await get(client, TRANSITS)

    assert response.status_code == 200
    body = response.json()
    assert (body["total"], body["page"], body["size"]) == (4, 1, 50)
    assert [item["mmsi"] for item in body["items"]] == [352000004, 352000002, 352000003, 352000001]
    assert set(body["items"][0]) == FIELDS
    done = body["items"][3]
    assert (done["status"], done["direction"], done["duration_minutes"]) == (
        "completed",
        "southbound",
        480,
    )
    assert (done["vessel_name"], done["ship_type"], done["abort_reason"]) == (
        "VESSEL 352000001",
        70,
        None,
    )
    assert body["items"][2]["abort_reason"] == "timeout"
    assert body["items"][2]["duration_minutes"] is None
    assert body["items"][0]["exited_at"] is None


async def test_filters_by_direction_and_status(
    client: AsyncClient, sessions: SessionFactory
) -> None:
    await seed(
        sessions,
        completed=[(352000001, "southbound", 30, 22), (352000002, "northbound", 10, 2)],
        aborted=[(352000003, "southbound", "reversal", 20, 19)],
    )

    south = (await get(client, TRANSITS, direction="southbound")).json()
    aborted = (await get(client, TRANSITS, status="aborted")).json()
    both = (await get(client, TRANSITS, direction="southbound", status="completed")).json()

    assert {item["mmsi"] for item in south["items"]} == {352000001, 352000003}
    assert [item["mmsi"] for item in aborted["items"]] == [352000003]
    assert [item["mmsi"] for item in both["items"]] == [352000001]


async def test_default_window_is_seven_days_and_from_to_widen_or_narrow_it(
    client: AsyncClient, sessions: SessionFactory
) -> None:
    await seed(
        sessions,
        completed=[
            (352000001, "southbound", 24 * 10, 24 * 10 - 8),  # hace 10 días
            (352000002, "southbound", 24 * 2, 24 * 2 - 8),  # hace 2 días
        ],
    )

    default = (await get(client, TRANSITS)).json()
    wide = (await get(client, TRANSITS, **{"from": ago(24 * 20).isoformat()})).json()
    narrow = (
        await get(
            client,
            TRANSITS,
            **{"from": ago(24 * 12).isoformat(), "to": ago(24 * 5).isoformat()},
        )
    ).json()

    assert [item["mmsi"] for item in default["items"]] == [352000002]
    assert {item["mmsi"] for item in wide["items"]} == {352000001, 352000002}
    assert [item["mmsi"] for item in narrow["items"]] == [352000001]


async def test_paginates(client: AsyncClient, sessions: SessionFactory) -> None:
    await seed(
        sessions,
        completed=[(352000000 + n, "southbound", 40 - n * 2, 38 - n * 2) for n in range(1, 6)],
    )

    first = (await get(client, TRANSITS, size=2, page=1)).json()
    last = (await get(client, TRANSITS, size=2, page=3)).json()

    assert first["total"] == 5
    assert [item["mmsi"] for item in first["items"]] == [352000005, 352000004]
    assert [item["mmsi"] for item in last["items"]] == [352000001]


@pytest.mark.parametrize(
    "params",
    [
        {"direction": "sideways"},
        {"status": "done"},
        {"size": 201},
        {"size": 0},
        {"page": 0},
        {"unknown": "x"},
        {"from": "2026-11-01T00:00:00"},  # sin zona horaria
        {"from": (NOW + timedelta(days=1)).isoformat()},  # empieza después de `to` (ahora)
        {"from": (NOW - timedelta(days=91)).isoformat()},  # ventana de más de 90 días
    ],
)
async def test_invalid_parameters_are_422(client: AsyncClient, params: dict[str, Any]) -> None:
    response = await get(client, TRANSITS, **params)

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


# --- GET /transits/current ------------------------------------------------------------------


async def test_current_lists_only_open_transits_oldest_entry_first(
    client: AsyncClient, sessions: SessionFactory
) -> None:
    await seed(
        sessions,
        completed=[(352000001, "southbound", 30, 22)],
        aborted=[(352000002, "southbound", "timeout", 20, 19)],
        open_=[(352000003, "northbound", 2), (352000004, "southbound", 5)],
    )

    response = await get(client, f"{TRANSITS}/current")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["mmsi"] for item in body["items"]] == [352000004, 352000003]
    assert all(item["status"] == "in_progress" for item in body["items"])
    assert set(body["items"][0]) == FIELDS


async def test_current_is_empty_without_open_transits(client: AsyncClient) -> None:
    response = await get(client, f"{TRANSITS}/current")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


# --- GET /transits/{id} ---------------------------------------------------------------------


async def test_get_one_transit(client: AsyncClient, sessions: SessionFactory) -> None:
    await seed(sessions, completed=[(352000001, "northbound", 30, 22)])
    [item] = (await get(client, TRANSITS)).json()["items"]

    response = await get(client, f"{TRANSITS}/{item['id']}")

    assert response.status_code == 200
    assert response.json() == {**item, "anchorage_wait": None}


async def test_unknown_transit_is_404(client: AsyncClient) -> None:
    response = await get(client, f"{TRANSITS}/{uuid4()}")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["detail"] == "Tránsito no encontrado"


async def test_malformed_transit_id_is_422(client: AsyncClient) -> None:
    response = await get(client, f"{TRANSITS}/not-a-uuid")

    assert response.status_code == 422


async def test_a_vessel_name_with_markup_is_returned_as_plain_text(
    client: AsyncClient, sessions: SessionFactory
) -> None:
    async with sessions() as session:
        await AisRepository(session).upsert_vessels(
            [VesselRow(mmsi=352000001, name="<img src=x onerror=alert(1)>", last_seen_at=NOW)]
        )
        await TransitRepository(session).open_transit(
            OpenTransitRow(352000001, "southbound", ago(1))
        )
        await session.commit()

    response = await get(client, f"{TRANSITS}/current")

    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["items"][0]["vessel_name"] == "<img src=x onerror=alert(1)>"


# --- Espera en fondeo previa (6.2) ----------------------------------------------------------


async def test_the_detail_includes_the_wait_at_the_anchorage(
    client: AsyncClient, sessions: SessionFactory
) -> None:
    await seed(sessions, completed=[(352000001, "southbound", 10, 2)])
    [item] = (await get(client, TRANSITS)).json()["items"]
    async with sessions() as session:
        repository = AnchorageRepository(session)
        await repository.close_visit(ClosedVisitRow(352000001, "atlantic", ago(34), ago(10.1)))
        [visit] = await repository.unlinked_visits(ago(100))
        assert await repository.link(visit.id, UUID(item["id"]))
        await session.commit()

    detail = (await get(client, f"{TRANSITS}/{item['id']}")).json()

    assert detail["anchorage_wait"] == {
        "anchorage": "atlantic",
        "arrived_at": ago(34).isoformat().replace("+00:00", "Z"),
        "departed_at": ago(10.1).isoformat().replace("+00:00", "Z"),
        "wait_minutes": 24 * 60,
    }
    assert {key: detail[key] for key in FIELDS} == item
