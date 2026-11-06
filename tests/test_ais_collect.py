"""`scripts/ais_collect.py`: qué se guarda de cada mensaje y cómo se comporta la conexión."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from websockets.asyncio.server import ServerConnection, serve

from app.services.ais_parser import PositionUpdate, VesselStatic
from tests.scripts_loader import load_script

collect_script = load_script("ais_collect")
sim = load_script("ais_simulator")

START = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
API_KEY = "clave-de-prueba-que-no-debe-aparecer"


@asynccontextmanager
async def simulator() -> AsyncIterator[str]:
    messages = sim.generate(start=START, duration=timedelta(minutes=10), seed=1)
    server = await sim.start_server(messages, port=0, speed=0)
    port = next(iter(server.sockets)).getsockname()[1]
    try:
        yield f"ws://127.0.0.1:{port}"
    finally:
        server.close()
        await server.wait_closed()


def test_position_record_keeps_only_what_the_detector_needs() -> None:
    position = PositionUpdate(
        mmsi=353_123_000,
        received_at=START,
        lat=9.3,
        lon=-79.9,
        sog=12.5,
        cog=181.0,
        heading=180,
        nav_status=0,
    )

    record = collect_script.to_record(position)

    assert record == {
        "kind": "position",
        "mmsi": 353_123_000,
        "received_at": "2026-11-06T12:00:00+00:00",
        "lat": 9.3,
        "lon": -79.9,
        "sog": 12.5,
        "cog": 181.0,
        "heading": 180,
        "nav_status": 0,
    }


def test_static_record_drops_names_and_destinations() -> None:
    static = VesselStatic(
        mmsi=353_123_000,
        name="NOMBRE DEL BUQUE",
        imo=9_123_456,
        ship_type=70,
        length_m=294.0,
        beam_m=32.0,
        destination="BALBOA",
        received_at=START,
    )

    record = collect_script.to_record(static)

    assert record == {
        "kind": "static",
        "mmsi": 353_123_000,
        "received_at": "2026-11-06T12:00:00+00:00",
        "ship_type": 70,
        "length_m": 294.0,
        "beam_m": 32.0,
    }
    assert "NOMBRE" not in json.dumps(record)


def test_nothing_to_store_for_ignored_messages() -> None:
    assert collect_script.to_record(None) is None


def test_recorder_writes_valid_lines_and_counts_each_kind() -> None:
    messages = sim.generate(start=START, duration=timedelta(minutes=10), seed=1, invalid_ratio=0.1)
    lines: list[str] = []
    recorder = collect_script.Recorder(lines.append)
    confirmation = json.dumps({"MessageType": "SubscriptionConfirmation", "Message": {}})

    for frame in [confirmation, *(message.raw for message in messages)]:
        recorder.handle(frame, received_at=START)

    kinds = [message.kind for message in messages]
    assert recorder.counts["position"] == kinds.count("position")
    assert recorder.counts["static"] == kinds.count("static")
    assert sum(v for k, v in recorder.counts.items() if k.startswith("rejected:")) == kinds.count(
        "invalid"
    )
    assert len(lines) == recorder.counts["position"] + recorder.counts["static"]
    for line in lines:
        assert line.endswith("\n")
        assert json.loads(line)["kind"] in {"position", "static"}


def test_subscription_uses_the_canal_boxes_and_the_worker_message_types() -> None:
    message = json.loads(collect_script.subscription_message(API_KEY))

    assert message["APIKey"] == API_KEY
    assert message["BoundingBoxes"]
    assert message["FilterMessageTypes"] == ["PositionReport", "ShipStaticData"]


async def test_collects_from_the_simulator_and_reconnects_when_the_stream_ends() -> None:
    lines: list[str] = []
    recorder = collect_script.Recorder(lines.append)

    async with simulator() as url:
        connections = await collect_script.collect(
            url, API_KEY, 1.0, recorder, reconnect_min=0.01, reconnect_max=0.05
        )

    assert recorder.counts["position"] > 0
    assert connections >= 2  # el simulador cierra al terminar y el recolector vuelve a entrar
    assert all(json.loads(line)["kind"] in {"position", "static"} for line in lines)


async def test_connection_errors_are_retried_and_never_print_the_key(
    capsys: pytest.CaptureFixture[str],
) -> None:
    recorder = collect_script.Recorder(lambda _line: None)

    # Un puerto sin nadie escuchando: rechaza la conexión.
    connections = await collect_script.collect(
        "ws://127.0.0.1:1", API_KEY, 0.3, recorder, reconnect_min=0.01, reconnect_max=0.05
    )

    captured = capsys.readouterr()
    assert connections == 0
    assert "Conexión perdida" in captured.err
    assert API_KEY not in captured.err
    assert API_KEY not in captured.out


async def test_a_server_that_closes_at_once_gets_growing_waits_not_a_flood() -> None:
    accepted = 0

    async def close_at_once(connection: ServerConnection) -> None:
        nonlocal accepted
        accepted += 1
        await connection.close()

    recorder = collect_script.Recorder(lambda _line: None)
    async with serve(close_at_once, "127.0.0.1", 0) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        connections = await collect_script.collect(
            f"ws://127.0.0.1:{port}",
            API_KEY,
            1.0,
            recorder,
            reconnect_min=0.05,
            reconnect_max=1.0,
            stable_after=60,
        )

    # Esperas de 0,05 + 0,1 + 0,2 + 0,4 s: unas 5 conexiones, no la veintena de un bucle sin freno.
    assert 3 <= accepted <= 7
    assert connections == 0  # cerró antes de que la suscripción llegara a enviarse
