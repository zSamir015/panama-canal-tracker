"""`GET /api/v1/vessels` y `GET /api/v1/vessels/{mmsi}` contra PostgreSQL real."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import SessionFactory
from app.core.security import create_access_token, hash_password
from app.models.user import UserRole
from app.repositories.ais import AisRepository, PositionRow, VesselRow
from app.repositories.user import UserRepository

VESSELS = "/api/v1/vessels"
NOW = datetime.now(UTC).replace(microsecond=0)
VESSEL_FIELDS = {"mmsi", "name", "imo", "ship_type", "length_m", "beam_m", "last_seen_at"}
POSITION_FIELDS = {"received_at", "lat", "lon", "sog", "cog", "heading", "nav_status"}


@pytest.fixture
async def app(migrated: AsyncEngine, db_app: FastAPI) -> AsyncIterator[FastAPI]:
    yield db_app


@pytest.fixture
def sessions(app: FastAPI) -> SessionFactory:
    factory: SessionFactory = app.state.session_factory
    return factory


@pytest.fixture
async def client(app: FastAPI, sessions: SessionFactory) -> AsyncIterator[AsyncClient]:
    # Un usuario normal: los buques son de lectura para cualquier usuario autenticado (§8.5).
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


async def store(
    sessions: SessionFactory,
    vessels: list[VesselRow],
    positions: list[PositionRow] | None = None,
) -> None:
    async with sessions() as session:
        repository = AisRepository(session)
        await repository.upsert_vessels(vessels)
        await repository.insert_positions(positions or [])
        await session.commit()


def vessel(mmsi: int, minutes_ago: int | None = None, **overrides: Any) -> VesselRow:
    last_seen = None if minutes_ago is None else NOW - timedelta(minutes=minutes_ago)
    values: dict[str, Any] = {
        "mmsi": mmsi,
        "last_seen_at": last_seen,
        "name": f"VESSEL {mmsi}",
        "ship_type": 70,
        "length_m": 200.0,
        "beam_m": 32.0,
    }
    return VesselRow(**(values | overrides))


def position(mmsi: int, minutes_ago: int, lat: float = 9.35, lon: float = -79.91) -> PositionRow:
    return PositionRow(
        received_at=NOW - timedelta(minutes=minutes_ago),
        mmsi=mmsi,
        lat=lat,
        lon=lon,
        sog=7.8,
        cog=145.2,
        heading=146,
        nav_status=0,
    )


# --- GET /vessels ---------------------------------------------------------------------------


async def test_lists_vessels_most_recently_seen_first(
    client: AsyncClient, sessions: SessionFactory
) -> None:
    # El empate se inserta al revés (primero el MMSI mayor, en otra transacción): sin desempate
    # explícito por MMSI, el orden físico de la tabla decidiría y no sería el esperado.
    await store(sessions, [vessel(352000004, minutes_ago=5)])
    await store(
        sessions,
        [
            vessel(352000001, minutes_ago=30),
            vessel(352000002, minutes_ago=5),
            vessel(352000003),  # nunca visto: al final
        ],
    )

    response = await client.get(VESSELS)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    assert set(body) == {"items", "total", "page", "size"}
    assert [item["mmsi"] for item in body["items"]] == [352000002, 352000004, 352000001, 352000003]
    assert (body["total"], body["page"], body["size"]) == (4, 1, 50)
    assert set(body["items"][0]) == VESSEL_FIELDS


async def test_pages_do_not_overlap(client: AsyncClient, sessions: SessionFactory) -> None:
    await store(sessions, [vessel(352000000 + i, minutes_ago=i) for i in range(1, 8)])

    first = (await client.get(VESSELS, params={"size": 3})).json()
    second = (await client.get(VESSELS, params={"size": 3, "page": 2})).json()
    last = (await client.get(VESSELS, params={"size": 3, "page": 3})).json()
    beyond = (await client.get(VESSELS, params={"size": 3, "page": 9})).json()

    pages = [[item["mmsi"] for item in page["items"]] for page in (first, second, last)]
    assert [len(page) for page in pages] == [3, 3, 1]
    assert len({mmsi for page in pages for mmsi in page}) == 7
    assert beyond["items"] == []
    assert beyond["total"] == 7


async def test_filters_by_ship_type_and_last_seen(
    client: AsyncClient, sessions: SessionFactory
) -> None:
    await store(
        sessions,
        [
            vessel(352000001, minutes_ago=10, ship_type=70),
            vessel(352000002, minutes_ago=10, ship_type=80),
            vessel(352000003, minutes_ago=600, ship_type=70),
        ],
    )

    by_type = (await client.get(VESSELS, params={"ship_type": 70})).json()
    since = NOW - timedelta(hours=1)
    recent = (await client.get(VESSELS, params={"seen_since": since.isoformat()})).json()
    both = (
        await client.get(VESSELS, params={"ship_type": 70, "seen_since": since.isoformat()})
    ).json()

    assert {item["mmsi"] for item in by_type["items"]} == {352000001, 352000003}
    assert {item["mmsi"] for item in recent["items"]} == {352000001, 352000002}
    assert [item["mmsi"] for item in both["items"]] == [352000001]
    assert both["total"] == 1


@pytest.mark.parametrize(
    "params",
    [
        {"size": 201},
        {"size": 0},
        {"page": 0},
        {"ship_type": 0},
        {"ship_type": 100},
        {"seen_since": "2026-10-21T12:00:00"},  # sin zona horaria
        {"seen_since": (NOW - timedelta(days=91)).isoformat()},
        {"seen_since": "ayer"},
        {"order_by": "name"},  # parámetro desconocido
    ],
    ids=[
        "size_201",
        "size_0",
        "page_0",
        "tipo_0",
        "tipo_100",
        "fecha_sin_zona",
        "fecha_91_dias",
        "fecha_texto",
        "parametro_desconocido",
    ],
)
async def test_invalid_query_parameters_are_rejected(
    client: AsyncClient, params: dict[str, Any]
) -> None:
    response = await client.get(VESSELS, params=params)

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"


async def test_listing_requires_a_token(app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        response = await c.get(VESSELS)

    assert response.status_code == 401


# --- GET /vessels/{mmsi} --------------------------------------------------------------------


async def test_detail_includes_the_latest_position(
    client: AsyncClient, sessions: SessionFactory
) -> None:
    await store(
        sessions,
        [vessel(352000001, minutes_ago=1, name="PACIFIC STAR")],
        [position(352000001, 30, lat=9.10, lon=-79.70), position(352000001, 1, lat=9.35)],
    )

    response = await client.get(f"{VESSELS}/352000001")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == VESSEL_FIELDS | {"last_position"}
    assert body["name"] == "PACIFIC STAR"
    last = body["last_position"]
    assert set(last) == POSITION_FIELDS
    assert last["lat"] == pytest.approx(9.35)  # la más reciente, con lat y lon en su sitio
    assert last["lon"] == pytest.approx(-79.91)
    assert datetime.fromisoformat(last["received_at"]) == NOW - timedelta(minutes=1)


async def test_vessel_without_positions_has_a_null_last_position(
    client: AsyncClient, sessions: SessionFactory
) -> None:
    await store(sessions, [vessel(352000001)])

    response = await client.get(f"{VESSELS}/352000001")

    assert response.status_code == 200
    assert response.json()["last_position"] is None


async def test_unknown_vessel_is_404(client: AsyncClient) -> None:
    response = await client.get(f"{VESSELS}/352999999")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["detail"] == "Buque no encontrado"


@pytest.mark.parametrize("mmsi", ["12345678", "1000000000", "abc", "352000001.5"])
async def test_invalid_mmsi_is_422(client: AsyncClient, mmsi: str) -> None:
    response = await client.get(f"{VESSELS}/{mmsi}")

    assert response.status_code == 422


async def test_detail_requires_a_token(app: FastAPI, sessions: SessionFactory) -> None:
    await store(sessions, [vessel(352000001)])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        response = await c.get(f"{VESSELS}/352000001")

    assert response.status_code == 401


# --- Datos AIS como JSON seguro -------------------------------------------------------------


async def test_hostile_vessel_names_are_returned_as_json_text(
    client: AsyncClient, sessions: SessionFactory
) -> None:
    name = "<img src=x onerror=alert(1)>"
    await store(sessions, [vessel(352000001, minutes_ago=1, name=name)])

    listing = await client.get(VESSELS)
    detail = await client.get(f"{VESSELS}/352000001")

    for response in (listing, detail):
        assert response.headers["content-type"] == "application/json"
        assert response.headers["x-content-type-options"] == "nosniff"
    assert listing.json()["items"][0]["name"] == name
    assert detail.json()["name"] == name
