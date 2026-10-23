"""`/ws/live` contra un servidor uvicorn real, PostgreSQL y Redis (base 15) (tarea 4.2).

Se usa un servidor de verdad y el cliente de `websockets`, como un navegador: así se prueban el
handshake (Origin), los códigos de cierre y el límite de tamaño de uvicorn, no solo el router.
"""

import asyncio
import io
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from app.core.config import Settings
from app.core.db import SessionFactory
from app.core.logging import configure_logging
from app.core.redis import LIVE_CHANNEL, create_redis
from app.core.security import create_access_token, create_refresh_token, hash_password
from app.main import WS_MAX_SIZE_BYTES, create_app
from app.models.user import User, UserRole
from app.repositories.ais import AisRepository, PositionRow, VesselRow
from app.repositories.user import UserRepository
from app.routers import live as live_router
from app.schemas.live import LiveUpdate, LiveVessel
from app.services.live import ConnectionLimiter
from app.workers.ais_consumer import run_worker
from tests.scripts_loader import load_script

ORIGIN = "https://tracker.example.com"  # el de `db_settings`
CANAL = [-80.2, 8.4, -79.2, 9.7]
NOW = datetime.now(UTC).replace(microsecond=0)


@pytest.fixture(autouse=True)
def fast_timers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_router, "AUTH_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(live_router, "FLUSH_INTERVAL_SECONDS", 0.05)


@pytest.fixture
async def redis(redis_url: SecretStr, redis_storage: Any) -> AsyncIterator[Redis]:
    client = create_redis(Settings(app_env="test", redis_url=redis_url))

    async def clean() -> None:
        # Límite de conexiones y estado del worker (prueba de extremo a extremo).
        async for key in client.scan_iter("canal:*"):
            await client.delete(key)

    await clean()
    try:
        yield client
    finally:
        await clean()
        await client.aclose()


@pytest.fixture
async def app(
    migrated: AsyncEngine, db_settings: Settings, redis_url: SecretStr, redis: Redis
) -> AsyncIterator[FastAPI]:
    app = create_app(db_settings.model_copy(update={"redis_url": redis_url}))
    yield app
    await app.state.live_hub.close()
    await app.state.engine.dispose()
    await app.state.redis.aclose()


@pytest.fixture
async def url(app: FastAPI) -> AsyncIterator[str]:
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=0,
        log_config=None,
        lifespan="off",
        ws_max_size=WS_MAX_SIZE_BYTES,
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    async with asyncio.timeout(5):
        while True:
            if server.started:
                break
            await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"ws://127.0.0.1:{port}/ws/live"
    finally:
        server.should_exit = True
        await task


@pytest.fixture
def sessions(app: FastAPI) -> SessionFactory:
    factory: SessionFactory = app.state.session_factory
    return factory


async def make_user(app: FastAPI, email: str = "ana@example.com") -> Any:
    factory: SessionFactory = app.state.session_factory
    async with factory() as session:
        user = await UserRepository(session).add(
            email=email,
            hashed_password=hash_password("una frase larga de prueba"),
            role=UserRole.USER,
        )
        await session.commit()
    return user


@pytest.fixture
async def token(app: FastAPI) -> str:
    user = await make_user(app)
    access, _ = create_access_token(user.id, app.state.settings)
    return access


def open_ws(url: str, origin: str | None = ORIGIN) -> Any:
    return connect(url, origin=origin, open_timeout=5)  # type: ignore[arg-type]


WAIT_SECONDS = 3.0


async def receive(ws: ClientConnection) -> dict[str, Any]:
    raw = await asyncio.wait_for(ws.recv(), timeout=WAIT_SECONDS)
    data: dict[str, Any] = json.loads(raw)
    return data


async def closed_with(ws: ClientConnection) -> int | None:
    with pytest.raises(ConnectionClosed) as error:
        async with asyncio.timeout(WAIT_SECONDS):
            while True:
                await ws.recv()
    return error.value.rcvd.code if error.value.rcvd else None


async def authenticated(url: str, token: str) -> Any:
    ws = await open_ws(url)
    await ws.send(json.dumps({"type": "auth", "token": token}))
    return ws


async def store(sessions: SessionFactory, *positions: tuple[int, float, float, int]) -> None:
    """(mmsi, lon, lat, minutos atrás)."""
    async with sessions() as session:
        repository = AisRepository(session)
        await repository.upsert_vessels(
            [
                VesselRow(mmsi=mmsi, name=f"VESSEL {mmsi}", ship_type=70)
                for mmsi in {p[0] for p in positions}
            ]
        )
        await repository.insert_positions(
            [
                PositionRow(
                    received_at=NOW - timedelta(minutes=minutes),
                    mmsi=mmsi,
                    lat=lat,
                    lon=lon,
                    sog=7.5,
                    cog=180.0,
                    heading=181,
                    nav_status=0,
                )
                for mmsi, lon, lat, minutes in positions
            ]
        )
        await session.commit()


def live_vessel(mmsi: int, lon: float = -79.9, lat: float = 9.3, seconds: int = 0) -> LiveVessel:
    return LiveVessel(
        mmsi=mmsi,
        lon=lon,
        lat=lat,
        cog=90.0,
        sog=8.0,
        ship_type=70,
        name="<img src=x onerror=alert(1)>",
        ts=NOW + timedelta(seconds=seconds),
    )


async def publish(redis: Redis, *vessels: LiveVessel) -> None:
    await redis.publish(LIVE_CHANNEL, LiveUpdate(vessels=list(vessels)).model_dump_json())


async def eventually(condition: Callable[[], Awaitable[bool]]) -> None:
    async with asyncio.timeout(5):
        while True:
            if await condition():
                return
            await asyncio.sleep(0.05)


# --- Handshake y autenticación --------------------------------------------------------------


@pytest.mark.parametrize("origin", ["https://evil.example.com", None], ids=["ajeno", "sin_origin"])
async def test_handshake_from_another_origin_is_rejected(url: str, origin: str | None) -> None:
    with pytest.raises(InvalidStatus) as error:
        async with open_ws(url, origin=origin):
            pass

    assert error.value.response.status_code == 403


async def test_no_auth_message_in_time_closes_with_4401(url: str) -> None:
    async with open_ws(url) as ws:
        assert await closed_with(ws) == 4401


@pytest.mark.parametrize(
    "first_message",
    [
        {"type": "auth", "token": "no-es-un-jwt"},
        {"type": "subscribe", "bbox": CANAL},  # sin auth antes
        {"type": "auth"},
        "esto no es JSON",
    ],
    ids=["token_falso", "subscribe_sin_auth", "sin_token", "no_json"],
)
async def test_invalid_first_message_closes_with_4401(url: str, first_message: Any) -> None:
    async with open_ws(url) as ws:
        payload = first_message if isinstance(first_message, str) else json.dumps(first_message)
        await ws.send(payload)

        assert await closed_with(ws) == 4401


async def test_a_refresh_token_is_not_an_access_token(url: str, app: FastAPI) -> None:
    user = await make_user(app)
    refresh, _ = create_refresh_token(user.id, uuid.uuid4(), app.state.settings)

    async with await authenticated(url, refresh) as ws:
        assert await closed_with(ws) == 4401


async def test_token_of_a_deleted_user_closes_with_4401(
    url: str, app: FastAPI, sessions: SessionFactory
) -> None:
    user = await make_user(app)
    access, _ = create_access_token(user.id, app.state.settings)
    async with sessions() as session:
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()

    async with await authenticated(url, access) as ws:
        assert await closed_with(ws) == 4401


# --- Snapshot y tiempo real -----------------------------------------------------------------


async def test_subscribe_returns_the_latest_position_of_each_vessel_in_the_viewport(
    url: str, token: str, sessions: SessionFactory
) -> None:
    await store(
        sessions,
        (352000001, -79.9, 9.3, 1),  # dentro
        (352000002, -78.0, 9.3, 1),  # fuera
        (352000003, -79.9, 9.3, 45),  # dentro, pero sin señal en 30 min
        (352000004, -79.9, 9.3, 10),  # estuvo dentro...
        (352000004, -78.0, 9.3, 2),  # ...pero su última posición está fuera
        (352000005, -79.8, 9.2, 20),
        (352000005, -79.7, 9.1, 5),  # dos dentro: cuenta la última
    )

    async with await authenticated(url, token) as ws:
        await ws.send(json.dumps({"type": "subscribe", "bbox": CANAL}))
        message = await receive(ws)

    assert message["type"] == "snapshot"
    vessels = {v["mmsi"]: v for v in message["vessels"]}
    assert set(vessels) == {352000001, 352000005}
    assert (vessels[352000005]["lon"], vessels[352000005]["lat"]) == pytest.approx((-79.7, 9.1))
    assert set(vessels[352000001]) == {
        "mmsi",
        "lon",
        "lat",
        "cog",
        "sog",
        "ship_type",
        "name",
        "ts",
    }
    assert vessels[352000001]["name"] == "VESSEL 352000001"


async def test_live_updates_are_filtered_by_viewport_and_removed_when_leaving(
    url: str, token: str, redis: Redis, app: FastAPI
) -> None:
    async with await authenticated(url, token) as ws:
        await ws.send(json.dumps({"type": "subscribe", "bbox": CANAL}))
        assert (await receive(ws))["vessels"] == []
        await eventually(lambda: _subscribed(app))

        await publish(redis, live_vessel(352000001), live_vessel(352000002, lon=-78.0))
        update = await receive(ws)
        await publish(redis, live_vessel(352000001, lon=-78.0, seconds=10))
        remove = await receive(ws)

    assert update["type"] == "update"
    assert [v["mmsi"] for v in update["vessels"]] == [352000001]
    # El nombre AIS llega como texto JSON tal cual; el navegador lo pinta como texto.
    assert update["vessels"][0]["name"] == "<img src=x onerror=alert(1)>"
    assert remove == {"type": "remove", "mmsi": [352000001]}


async def _subscribed(app: FastAPI) -> bool:
    return bool(app.state.live_hub.stats.subscribed)


async def test_an_invalid_message_on_the_channel_is_ignored(
    url: str, token: str, redis: Redis, app: FastAPI
) -> None:
    async with await authenticated(url, token) as ws:
        await ws.send(json.dumps({"type": "subscribe", "bbox": CANAL}))
        await receive(ws)
        await eventually(lambda: _subscribed(app))

        await redis.publish(LIVE_CHANNEL, b'{"type": "update", "vessels": [{"mmsi": 1}]}')
        await publish(redis, live_vessel(352000001))

        update = await receive(ws)

    assert [v["mmsi"] for v in update["vessels"]] == [352000001]
    assert app.state.live_hub.stats.invalid == 1


async def test_a_new_viewport_gets_a_new_snapshot(
    url: str, token: str, sessions: SessionFactory
) -> None:
    await store(sessions, (352000001, -79.9, 9.3, 1), (352000002, -78.0, 9.3, 1))

    async with await authenticated(url, token) as ws:
        await ws.send(json.dumps({"type": "subscribe", "bbox": CANAL}))
        first = await receive(ws)
        await ws.send(json.dumps({"type": "subscribe", "bbox": [-78.5, 9.0, -77.5, 9.5]}))
        second = await receive(ws)

    assert [v["mmsi"] for v in first["vessels"]] == [352000001]
    assert second["type"] == "snapshot"
    assert [v["mmsi"] for v in second["vessels"]] == [352000002]


# --- Límites y mensajes inválidos -----------------------------------------------------------


async def test_a_sixth_connection_of_the_same_user_is_rejected(url: str, token: str) -> None:
    open_connections = []
    try:
        for _ in range(5):
            ws = await authenticated(url, token)
            await ws.send(json.dumps({"type": "subscribe", "bbox": CANAL}))
            assert (await receive(ws))["type"] == "snapshot"
            open_connections.append(ws)

        async with await authenticated(url, token) as sixth:
            assert await closed_with(sixth) == 4429

        # Al cerrar una, vuelve a haber hueco.
        await open_connections.pop().close()
        await asyncio.sleep(0.2)
        async with await authenticated(url, token) as again:
            await again.send(json.dumps({"type": "subscribe", "bbox": CANAL}))
            assert (await receive(again))["type"] == "snapshot"
    finally:
        for ws in open_connections:
            await ws.close()


async def test_another_user_is_not_affected_by_the_limit(
    url: str, token: str, app: FastAPI
) -> None:
    other = await make_user(app, "luis@example.com")
    other_token, _ = create_access_token(other.id, app.state.settings)
    mine = [await authenticated(url, token) for _ in range(5)]
    try:
        async with await authenticated(url, other_token) as ws:
            await ws.send(json.dumps({"type": "subscribe", "bbox": CANAL}))
            assert (await receive(ws))["type"] == "snapshot"
    finally:
        for ws in mine:
            await ws.close()


@pytest.mark.parametrize(
    ("message", "code"),
    [
        (json.dumps({"type": "subscribe", "bbox": [-79.2, 8.4, -80.2, 9.7]}), 4400),
        (json.dumps({"type": "subscribe", "bbox": CANAL, "extra": True}), 4400),
        (json.dumps({"type": "auth", "token": "otra vez"}), 4400),
        ("no es JSON", 4400),
        (json.dumps({"type": "subscribe", "bbox": CANAL, "pad": "x" * 5000}), 1009),
    ],
    ids=["bbox_al_reves", "campo_extra", "auth_repetido", "no_json", "mas_de_4kb"],
)
async def test_invalid_messages_close_the_connection(
    url: str, token: str, message: str, code: int
) -> None:
    async with await authenticated(url, token) as ws:
        await ws.send(json.dumps({"type": "subscribe", "bbox": CANAL}))
        await receive(ws)
        await ws.send(message)

        assert await closed_with(ws) == code


async def test_frames_beyond_the_server_limit_are_cut_by_uvicorn(url: str, token: str) -> None:
    async with await authenticated(url, token) as ws:
        await ws.send("x" * (WS_MAX_SIZE_BYTES + 1))

        assert await closed_with(ws) == 1009


async def test_too_many_messages_close_with_4429(
    url: str, token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(live_router, "MAX_CLIENT_MESSAGES", 3)

    async with await authenticated(url, token) as ws:
        for _ in range(4):
            await ws.send(json.dumps({"type": "subscribe", "bbox": CANAL}))

        with pytest.raises(ConnectionClosed) as error:
            async with asyncio.timeout(3):
                while True:
                    await ws.recv()
    assert error.value.rcvd is not None
    assert error.value.rcvd.code == 4429


# --- Logs -----------------------------------------------------------------------------------


async def test_the_token_never_reaches_the_logs_even_in_debug(url: str, token: str) -> None:
    stream = io.StringIO()
    configure_logging("DEBUG", stream=stream)

    async with await authenticated(url, token) as ws:
        await ws.send(json.dumps({"type": "subscribe", "bbox": CANAL}))
        await receive(ws)
    async with await authenticated(url, token + "x") as ws:
        await closed_with(ws)

    logs = stream.getvalue()
    assert "ws_connected" in logs
    assert '"code": 4401' in logs
    assert token not in logs
    assert token.split(".")[-1] not in logs  # ni siquiera la firma


# --- Límite de conexiones con Redis real ----------------------------------------------------


async def test_a_connection_that_stops_beating_frees_its_slot(redis: Redis) -> None:
    # Una réplica que muere no llama a `release`: su entrada caduca si no late.
    clock = [1_000.0]
    limiter = ConnectionLimiter(redis, max_per_user=1, ttl_seconds=90, clock=lambda: clock[0])

    assert await limiter.acquire("user-a", "vivo")
    clock[0] += 60
    await limiter.refresh("user-a", "vivo")  # late: sigue contando
    clock[0] += 60
    assert not await limiter.acquire("user-a", "otro")

    clock[0] += 120  # ya no late: a los 90 s deja de contar
    assert await limiter.acquire("user-a", "otro")


# --- Extremo a extremo: simulador → worker → Redis → /ws/live -------------------------------


async def test_simulated_traffic_reaches_the_browser_end_to_end(
    url: str, token: str, db_settings: Settings, redis_url: SecretStr
) -> None:
    sim = load_script("ais_simulator")
    messages = sim.generate(start=NOW, duration=timedelta(minutes=10), seed=1)
    # speed alto pero no 0: el tráfico sigue llegando mientras el navegador está conectado.
    sim_server = await sim.start_server(messages, port=0, speed=600)
    sim_port = next(iter(sim_server.sockets)).getsockname()[1]
    settings = db_settings.model_copy(
        update={
            "aisstream_url": f"ws://127.0.0.1:{sim_port}",
            "aisstream_api_key": SecretStr("clave-de-pruebas"),
            "redis_url": redis_url,
            "ais_canal_bound_enabled": False,
            "ais_batch_size": 20,
            "ais_batch_flush_seconds": 0.05,
        }
    )
    stop = asyncio.Event()
    worker = asyncio.create_task(run_worker(settings, stop))
    try:
        async with await authenticated(url, token) as ws:
            await ws.send(json.dumps({"type": "subscribe", "bbox": CANAL}))
            assert (await receive(ws))["type"] == "snapshot"
            update = await receive(ws)
    finally:
        stop.set()
        await asyncio.wait_for(worker, timeout=10)
        sim_server.close()
        await sim_server.wait_closed()

    assert update["type"] == "update"
    assert update["vessels"]
    assert all(-80.2 <= v["lon"] <= -79.2 and 8.4 <= v["lat"] <= 9.7 for v in update["vessels"])
