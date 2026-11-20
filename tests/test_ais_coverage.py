"""`scripts/ais_coverage.py`: el recuento, con frames del simulador (sin AISStream)."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from tests.scripts_loader import load_script

coverage = load_script("ais_coverage")
sim = load_script("ais_simulator")
START = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
CONFIRMATION = json.dumps(
    {"MessageType": "SubscriptionConfirmation", "Message": {"CompressionEnabled": True}}
)


def test_counts_positions_statics_vessels_and_rejections() -> None:
    messages = sim.generate(start=START, duration=timedelta(minutes=10), seed=1, invalid_ratio=0.1)
    frames = [CONFIRMATION, *(message.raw for message in messages)]

    sample = coverage.summarize(frames, started_at=START, seconds=600)

    kinds = [message.kind for message in messages]
    assert sample.confirmed is True
    assert sample.positions == kinds.count("position")
    assert sample.statics == kinds.count("static")
    assert sum(sample.rejected.values()) == kinds.count("invalid")
    assert sample.vessels == len(sim.DEFAULT_FLEET)
    assert sample.positions_in_canal == sample.positions  # la ruta del simulador está dentro


def test_positions_outside_the_canal_box_are_counted_apart() -> None:
    messages = sim.generate(start=START, duration=timedelta(minutes=5), seed=1)
    raw = next(m.raw for m in messages if m.kind == "position")
    outside = json.loads(raw)
    outside["Message"]["PositionReport"].update(Latitude=8.97, Longitude=-82.11)  # Chiriquí

    sample = coverage.summarize([raw, json.dumps(outside)], started_at=START, seconds=60)

    assert (sample.positions, sample.positions_in_canal) == (2, 1)


def test_no_traffic_is_a_valid_sample() -> None:
    # Lo que se vio el 2026-10-21: confirmación y nada más.
    sample = coverage.summarize([CONFIRMATION], started_at=START, seconds=180)

    assert sample.confirmed is True
    assert (sample.positions, sample.statics, sample.vessels) == (0, 0, 0)


def test_sample_line_never_contains_message_content() -> None:
    messages = sim.generate(start=START, duration=timedelta(minutes=5), seed=1)

    sample = coverage.summarize([m.raw for m in messages], started_at=START, seconds=300)

    line = json.dumps(sample.__dict__)
    assert "PACIFIC STAR" not in line  # solo recuentos, ni nombres ni MMSI
    assert "352000001" not in line


@pytest.mark.parametrize("minutes", ["0", "31", "-1"])
def test_duration_is_bounded(minutes: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        coverage.main(["--minutes", minutes])

    assert "--minutes" in capsys.readouterr().err


def test_counts_by_type_and_wide_bbox_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    type27 = json.dumps(
        {
            "MessageType": "LongRangeAisBroadcastMessage",
            "MetaData": {"MMSI": 636022111},
            "Message": {
                "LongRangeAisBroadcastMessage": {
                    "UserID": 636022111,
                    "Latitude": 8.05,  # Golfo de Panamá (fuera de bbox estrecha, dentro de wide)
                    "Longitude": -79.45,
                    "Sog": 12,
                    "Cog": 10,
                    "NavigationalStatus": 0,
                }
            },
        }
    )
    messages = sim.generate(start=START, duration=timedelta(minutes=2), seed=1)
    first_pos = next(m.raw for m in messages if m.kind == "position")

    sample = coverage.summarize(
        [CONFIRMATION, first_pos, type27], started_at=START, seconds=60, bbox="wide"
    )

    assert sample.bbox == "wide"
    assert sample.by_type == {"PositionReport": 1, "LongRangeAisBroadcastMessage": 1}
    assert (sample.positions, sample.positions_in_canal) == (2, 1)

    recorded_boxes: list[object] = []

    async def fake_collect(url: str, api_key: str, seconds: float, *, boxes: object) -> list[str]:
        recorded_boxes.append(boxes)
        return [CONFIRMATION, type27]

    from pydantic import SecretStr

    class _FakeSettings:
        aisstream_api_key = SecretStr("test-key")
        aisstream_url = "ws://127.0.0.1:8765"

    monkeypatch.setattr(coverage, "get_settings", _FakeSettings)
    monkeypatch.setattr(coverage, "collect", fake_collect)
    assert coverage.main(["--minutes", "1", "--bbox", "wide"]) == 0
    assert recorded_boxes == [coverage.BOUNDING_BOX_PRESETS["wide"]]


def test_worker_does_not_subscribe_type27_but_coverage_probe_does() -> None:
    # El Tipo 27 da la velocidad en nudos enteros: en el worker podría cerrar visitas a fondeo
    # (umbrales 0,5/1,0 nudos). Solo se mide con el script hasta decidirlo (issue #168).
    from app.workers.ais_consumer import MESSAGE_TYPES

    assert "LongRangeAisBroadcastMessage" not in MESSAGE_TYPES
    assert coverage.COVERAGE_MESSAGE_TYPES == (*MESSAGE_TYPES, "LongRangeAisBroadcastMessage")


def test_collect_subscribes_with_coverage_message_types(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    sent: list[str] = []

    class _FakeConnection:
        async def send(self, message: str) -> None:
            sent.append(message)

        async def recv(self) -> str:
            await asyncio.sleep(3600)
            return ""

    class _FakeConnect:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _FakeConnection:
            return _FakeConnection()

        async def __aexit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(coverage, "connect", _FakeConnect)
    boxes = coverage.BOUNDING_BOX_PRESETS["wide"]
    assert asyncio.run(coverage.collect("ws://x", "key", 0.01, boxes=boxes)) == []
    subscription = json.loads(sent[0])
    assert subscription["FilterMessageTypes"] == list(coverage.COVERAGE_MESSAGE_TYPES)
    assert subscription["BoundingBoxes"] == [[[7.8, -80.6], [10.2, -78.8]]]
