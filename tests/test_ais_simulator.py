"""Simulador AIS (`scripts/ais_simulator.py`): trayectorias, formato y servidor WebSocket.

El contrato más importante: todo lo que genera el simulador lo acepta el parser real (3.2), y
todo lo que inyecta como inválido el parser lo rechaza con el motivo esperado.
"""

import asyncio
import importlib.util
import itertools
import json
import sys
from collections import Counter, defaultdict
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from app.services.ais_parser import (
    AisMessageRejected,
    PositionUpdate,
    VesselStatic,
    parse_message,
)

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ais_simulator.py"
START = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
CANAL_BBOX = [[8.4, -80.2], [9.7, -79.2]]  # orden de AISStream: [lat, lon]


def load_simulator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ais_simulator", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ais_simulator"] = module
    spec.loader.exec_module(module)
    return module


sim = load_simulator()


def generate(**kwargs: Any) -> list[Any]:
    options: dict[str, Any] = {"start": START, "duration": timedelta(hours=2), "seed": 1}
    return list(sim.generate(**(options | kwargs)))


def positions_by_vessel(messages: list[Any]) -> dict[int, list[PositionUpdate]]:
    tracks: dict[int, list[PositionUpdate]] = defaultdict(list)
    for message in messages:
        if message.kind == "position":
            parsed = parse_message(message.raw, received_at=message.at)
            assert isinstance(parsed, PositionUpdate)
            tracks[message.mmsi].append(parsed)
    return tracks


def scenario_of(mmsi: int) -> str:
    return next(v.scenario for v in sim.DEFAULT_FLEET if v.mmsi == mmsi)


# --- Contrato con el parser -----------------------------------------------------------------


def test_every_generated_message_is_accepted_by_the_parser() -> None:
    messages = generate()

    parsed = [parse_message(message.raw, received_at=message.at) for message in messages]

    kinds = Counter(type(result).__name__ for result in parsed)
    assert kinds["PositionUpdate"] > 0
    assert kinds["VesselStatic"] > 0
    assert kinds["PositionUpdate"] + kinds["VesselStatic"] == len(messages)


def test_messages_carry_every_field_aisstream_marks_as_required() -> None:
    # Campos `required` del esquema OpenAPI de AISStream (aisstream/ais-message-models).
    required = {
        "PositionReport": {
            "MessageID",
            "RepeatIndicator",
            "UserID",
            "Valid",
            "NavigationalStatus",
            "RateOfTurn",
            "Sog",
            "PositionAccuracy",
            "Longitude",
            "Latitude",
            "Cog",
            "TrueHeading",
            "Timestamp",
            "SpecialManoeuvreIndicator",
            "Spare",
            "Raim",
            "CommunicationState",
        },
        "ShipStaticData": {
            "MessageID",
            "RepeatIndicator",
            "UserID",
            "Valid",
            "AisVersion",
            "ImoNumber",
            "CallSign",
            "Name",
            "Type",
            "Dimension",
            "FixType",
            "Eta",
            "MaximumStaticDraught",
            "Destination",
            "Dte",
            "Spare",
        },
    }
    for message in generate(duration=timedelta(minutes=10)):
        payload = json.loads(message.raw)
        message_type = payload["MessageType"]
        assert set(payload) == {"MessageType", "MetaData", "Message"}
        assert required[message_type] <= set(payload["Message"][message_type])
        assert payload["MetaData"]["MMSI"] == payload["Message"][message_type]["UserID"]


def test_injected_invalid_messages_are_rejected_with_the_expected_reason() -> None:
    messages = generate(duration=timedelta(hours=1), invalid_ratio=0.3)
    invalid = [message for message in messages if message.kind == "invalid"]

    reasons = []
    for message in invalid:
        with pytest.raises(AisMessageRejected) as caught:
            parse_message(message.raw, received_at=message.at)
        assert caught.value.reason == message.expected_reason
        reasons.append(message.expected_reason)

    # Con 0.3 de proporción salen todas las variantes.
    assert set(reasons) == {
        "invalid_json",
        "invalid_mmsi",
        "invalid_position",
        "no_position",
        "mmsi_mismatch",
        "invalid_message",
    }


def test_no_invalid_messages_by_default() -> None:
    assert all(message.kind != "invalid" for message in generate())


# --- Reproducibilidad y límites -------------------------------------------------------------


def test_same_seed_same_messages() -> None:
    assert [m.raw for m in generate(seed=7)] == [m.raw for m in generate(seed=7)]


def test_different_seed_different_messages() -> None:
    assert [m.raw for m in generate(seed=7)] != [m.raw for m in generate(seed=8)]


def test_messages_are_ordered_and_inside_the_requested_window() -> None:
    messages = generate(duration=timedelta(minutes=30))

    times = [message.at for message in messages]
    assert times == sorted(times)
    assert START <= times[0]
    assert times[-1] < START + timedelta(minutes=30)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"duration": timedelta(0)},
        {"duration": timedelta(minutes=sim.MAX_MINUTES + 1)},
        {"invalid_ratio": -0.1},
        {"invalid_ratio": 1.1},
        {"start": datetime(2026, 10, 20, 12, 0)},  # sin zona horaria
    ],
    ids=["duracion_cero", "duracion_excesiva", "ratio_negativo", "ratio_mayor_1", "naive"],
)
def test_out_of_range_options_are_rejected(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        generate(**kwargs)


# --- Trayectorias realistas -----------------------------------------------------------------


def test_every_position_falls_inside_the_canal_bounding_box() -> None:
    for track in positions_by_vessel(generate(duration=timedelta(hours=8))).values():
        for fix in track:
            assert 8.4 <= fix.lat <= 9.7
            assert -80.2 <= fix.lon <= -79.2


def test_a_full_transit_takes_hours_not_minutes() -> None:
    # Un tránsito real ronda las 8 a 10 h; con nuestras velocidades por tramo, entre 6 y 12.
    assert timedelta(hours=6) < sim.transit_duration("southbound") < timedelta(hours=12)
    assert sim.transit_duration("northbound") == sim.transit_duration("southbound")


@pytest.mark.parametrize(("scenario", "direction"), [("southbound", -1), ("northbound", 1)])
def test_transits_move_in_their_direction(scenario: str, direction: int) -> None:
    # Hacia el sur (Pacífico) la latitud baja; hacia el norte (Atlántico) sube.
    tracks = positions_by_vessel(generate(duration=timedelta(hours=3)))

    for mmsi, track in tracks.items():
        if scenario_of(mmsi) == scenario:
            assert (track[-1].lat - track[0].lat) * direction > 0.05
            assert all(fix.nav_status == sim.NAV_UNDERWAY for fix in track)


def test_a_southbound_vessel_ends_anchored_in_the_pacific() -> None:
    vessel = sim.SimulatedVessel(
        999000001,
        "TEST TRANSIT",
        "TEST1",
        9999999,
        70,
        200,
        30,
        10.0,
        "southbound",
        timedelta(0),
    )
    duration = sim.transit_duration("southbound") + timedelta(minutes=30)

    track = positions_by_vessel(list(sim.generate(start=START, duration=duration, fleet=[vessel])))[
        vessel.mmsi
    ]

    assert track[0].lat == pytest.approx(sim.ATLANTIC_ANCHORAGE[0], abs=0.01)
    assert track[-1].lat == pytest.approx(sim.PACIFIC_ANCHORAGE[0], abs=0.01)
    assert track[-1].nav_status == sim.NAV_AT_ANCHOR


def test_locks_are_crossed_slowly() -> None:
    # En las esclusas el buque va a ~2 nudos; en el lago, a ~9.
    vessel = sim.SimulatedVessel(
        999000002,
        "TEST LOCKS",
        "TEST2",
        9999998,
        70,
        200,
        30,
        10.0,
        "southbound",
        timedelta(0),
    )
    track = positions_by_vessel(
        list(sim.generate(start=START, duration=sim.transit_duration(), fleet=[vessel]))
    )[vessel.mmsi]

    gatun_lat = (9.262, 9.282)
    in_locks = [fix.sog for fix in track if gatun_lat[0] <= fix.lat <= gatun_lat[1]]
    in_lake = [fix.sog for fix in track if 9.17 <= fix.lat <= 9.235]
    assert in_locks and max(in_locks) < 3.5
    assert in_lake and min(in_lake) > 7


@pytest.mark.parametrize("scenario", ["anchored_atlantic", "anchored_pacific"])
def test_anchored_vessels_stay_put(scenario: str) -> None:
    tracks = positions_by_vessel(generate(duration=timedelta(hours=2)))

    for mmsi, track in tracks.items():
        if scenario_of(mmsi) == scenario:
            assert all(fix.nav_status == sim.NAV_AT_ANCHOR for fix in track)
            assert all(fix.sog is not None and fix.sog < 1 for fix in track)
            assert max(f.lat for f in track) - min(f.lat for f in track) < 0.001
            # Fondeado emite cada 3 minutos, no cada 30 segundos.
            assert len(track) <= 2 * 60 // 3 + 1


def test_signal_loss_leaves_a_gap_in_the_track() -> None:
    messages = [m for m in generate() if scenario_of(m.mmsi) == "signal_loss"]

    gaps = [later.at - earlier.at for earlier, later in itertools.pairwise(messages)]
    assert max(gaps) >= timedelta(minutes=25)


def test_static_data_is_sent_regularly_with_padding_removed() -> None:
    messages = generate(duration=timedelta(minutes=30))

    statics = Counter(message.mmsi for message in messages if message.kind == "static")
    assert set(statics) == {vessel.mmsi for vessel in sim.DEFAULT_FLEET}
    # Cada 6 minutos; el buque sin señal calla a partir del minuto 10.
    for mmsi, count in statics.items():
        assert count >= (2 if scenario_of(mmsi) == "signal_loss" else 5)

    first = next(m for m in messages if m.kind == "static")
    assert "@" in json.loads(first.raw)["Message"]["ShipStaticData"]["Name"]
    parsed = parse_message(first.raw, received_at=first.at)
    assert isinstance(parsed, VesselStatic)
    assert parsed.name is not None and "@" not in parsed.name


# --- Suscripción ----------------------------------------------------------------------------


def subscription(**overrides: Any) -> str:
    data: dict[str, Any] = {"APIKey": "clave-de-pruebas", "BoundingBoxes": [CANAL_BBOX]}
    data.update(overrides)
    return json.dumps({key: value for key, value in data.items() if value is not None})


def test_valid_subscription_is_parsed_with_its_filters() -> None:
    parsed = sim.parse_subscription(
        subscription(
            BoundingBoxes=[[[9.7, -79.2], [8.4, -80.2]]],  # esquinas en cualquier orden
            FilterMessageTypes=["PositionReport"],
            FiltersShipMMSI=["352000001"],
        )
    )

    assert parsed is not None
    assert parsed.boxes == ((8.4, -80.2, 9.7, -79.2),)
    assert parsed.message_types == frozenset({"PositionReport"})
    assert parsed.mmsi == frozenset({352000001})


@pytest.mark.parametrize(
    "raw",
    [
        subscription(APIKey=None),
        subscription(APIKey=""),
        subscription(APIKey=123),
        subscription(BoundingBoxes=None),
        subscription(BoundingBoxes=[]),
        subscription(BoundingBoxes=[[[91, 0], [0, 0]]]),
        subscription(BoundingBoxes=[[[9.0, -79.0]]]),
        subscription(BoundingBoxes=[[["9", "-79"], [8, -80]]]),
        subscription(FilterMessageTypes="PositionReport"),
        subscription(FiltersShipMMSI=["12345"]),
        subscription(FiltersShipMMSI=[str(352000000 + i) for i in range(201)]),
        "no es json",
        "[]",
        "x" * (sim.MAX_SUBSCRIPTION_BYTES + 1),
    ],
    ids=[
        "sin_key",
        "key_vacia",
        "key_no_texto",
        "sin_cajas",
        "cajas_vacias",
        "lat_91",
        "una_esquina",
        "coordenadas_texto",
        "tipos_no_lista",
        "mmsi_corto",
        "mmsi_201",
        "no_json",
        "lista",
        "enorme",
    ],
)
def test_invalid_subscriptions_are_refused(raw: str) -> None:
    assert sim.parse_subscription(raw) is None


# --- Servidor WebSocket ---------------------------------------------------------------------


@pytest.fixture
async def server_url() -> AsyncIterator[str]:
    messages = generate(duration=timedelta(minutes=20), invalid_ratio=0.05)
    server = await sim.start_server(messages, port=0, speed=0, subscription_timeout=0.2)
    port = next(iter(server.sockets)).getsockname()[1]
    try:
        yield f"ws://127.0.0.1:{port}"
    finally:
        server.close()
        await server.wait_closed()


async def receive_all(client: ClientConnection) -> list[Any]:
    frames = []
    try:
        while True:
            frames.append(await asyncio.wait_for(client.recv(), timeout=5))
    except ConnectionClosed:
        return frames


async def test_server_confirms_the_subscription_and_streams_binary_json(server_url: str) -> None:
    async with connect(server_url) as client:
        await client.send(subscription(FilterMessageTypes=["PositionReport", "ShipStaticData"]))
        frames = await receive_all(client)

    assert all(isinstance(frame, bytes) for frame in frames)
    confirmation = json.loads(frames[0])
    assert confirmation["MessageType"] == "SubscriptionConfirmation"
    assert confirmation["Message"]["CompressionEnabled"] is True  # permessage-deflate
    results = []
    for frame in frames[1:]:
        try:
            results.append(type(parse_message(frame, received_at=START)).__name__)
        except AisMessageRejected:
            results.append("rechazado")
    assert {"PositionUpdate", "VesselStatic", "rechazado"} <= set(results)


async def test_server_applies_the_bounding_box(server_url: str) -> None:
    # Una caja en otro lugar del mundo: solo llegan los inválidos (no tienen posición).
    async with connect(server_url) as client:
        await client.send(subscription(BoundingBoxes=[[[25.0, -80.5], [26.0, -80.0]]]))
        frames = await receive_all(client)

    for frame in frames[1:]:
        with pytest.raises(AisMessageRejected):
            parse_message(frame, received_at=START)


async def test_server_applies_message_type_and_mmsi_filters(server_url: str) -> None:
    async with connect(server_url) as client:
        await client.send(
            subscription(FilterMessageTypes=["ShipStaticData"], FiltersShipMMSI=["352000001"])
        )
        frames = await receive_all(client)

    parsed = []
    for frame in frames[1:]:
        try:
            parsed.append(parse_message(frame, received_at=START))
        except AisMessageRejected:
            continue
    assert parsed
    assert all(isinstance(item, VesselStatic) and item.mmsi == 352000001 for item in parsed)


@pytest.mark.parametrize("raw", [subscription(APIKey=""), "no es json"])
async def test_invalid_subscription_is_closed_without_confirmation(
    server_url: str, raw: str
) -> None:
    async with connect(server_url) as client:
        await client.send(raw)
        frames = await receive_all(client)

    assert frames == []
    assert client.close_code == 1008


async def test_late_subscription_is_closed_without_confirmation(server_url: str) -> None:
    async with connect(server_url) as client:
        frames = await receive_all(client)  # no envía nada: el servidor cierra a los 0,2 s

    assert frames == []
    assert client.close_code == 1008


async def test_server_rejects_out_of_range_speed() -> None:
    with pytest.raises(ValueError, match="speed"):
        await sim.start_server([], port=0, speed=sim.MAX_SPEED + 1)


# --- CLI ------------------------------------------------------------------------------------


def test_cli_writes_one_parseable_json_message_per_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert sim.main(["jsonl", "--minutes", "5", "--seed", "3"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines
    for line in lines:
        assert parse_message(line, received_at=START) is not None


def test_cli_rejects_a_duration_over_the_limit(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        sim.main(["jsonl", "--minutes", str(sim.MAX_MINUTES + 1)])

    assert "duración" in capsys.readouterr().err
