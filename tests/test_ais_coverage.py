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
