"""Replay de posiciones grabadas por el detector (tarea 5.5)."""

import dataclasses
import json
import random
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.services.ais_parser import PositionUpdate, parse_message
from tests.scripts_loader import load_script

replay_script = load_script("transit_replay")
sim = load_script("ais_simulator")
collect = load_script("ais_collect")

T0 = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)
TIMEOUT = timedelta(minutes=30)
ATLANTIC = (-79.93, 9.39)
PACIFIC = (-79.552, 8.91)
LAKE = (-79.75, 9.15)


def at(minutes: float, point: tuple[float, float], mmsi: int = 352000001) -> PositionUpdate:
    lon, lat = point
    return PositionUpdate(
        mmsi=mmsi,
        received_at=T0 + timedelta(minutes=minutes),
        lat=lat,
        lon=lon,
        sog=None,
        cog=None,
        heading=None,
        nav_status=None,
    )


def simulated(scenario: str, *, minutes: int = 1440) -> list[PositionUpdate]:
    """Posiciones de un buque simulado que arranca de cero, pasadas por el parser real."""
    vessel = next(item for item in sim.DEFAULT_FLEET if item.scenario == scenario)
    vessel = dataclasses.replace(vessel, elapsed_at_start=timedelta(0))
    messages = sim.generate(start=T0, duration=timedelta(minutes=minutes), fleet=[vessel])
    parsed = [
        parse_message(message.raw, received_at=message.at)
        for message in messages
        if message.kind == "position"
    ]
    return [item for item in parsed if isinstance(item, PositionUpdate)]


# --- Trayectorias del simulador, de punta a punta -------------------------------------------


@pytest.mark.parametrize(
    ("scenario", "direction"),
    [("southbound", "southbound"), ("northbound", "northbound")],
)
def test_a_simulated_vessel_completes_the_transit_in_the_expected_direction(
    scenario: str, direction: str
) -> None:
    result = replay_script.replay(simulated(scenario), timeout=TIMEOUT)

    [transit] = result.transits
    assert (transit.direction, transit.status, transit.abort_reason) == (
        direction,
        "completed",
        None,
    )
    # El simulador tarda unas 7 horas de fondeadero a fondeadero; dentro de las dos entradas, algo
    # menos de 6.
    assert timedelta(hours=5, minutes=30) < transit.duration < timedelta(hours=6, minutes=15)


@pytest.mark.parametrize("scenario", ["anchored_atlantic", "anchored_pacific"])
def test_a_vessel_anchored_outside_the_entrances_never_opens_a_transit(scenario: str) -> None:
    result = replay_script.replay(simulated(scenario), timeout=TIMEOUT)

    assert result.transits == []
    assert result.positions > 100


def test_a_gap_in_the_middle_of_a_simulated_transit_is_survived_or_aborted_by_the_timeout() -> None:
    entered = simulated("southbound")[0].received_at
    gap_start, gap_end = entered + timedelta(hours=2), entered + timedelta(hours=2, minutes=40)
    # Se borran 40 minutos de señal dentro del tránsito, como si el buque saliera de cobertura.
    positions = [p for p in simulated("southbound") if not gap_start < p.received_at < gap_end]

    tolerant = replay_script.replay(positions, timeout=timedelta(minutes=60))
    strict = replay_script.replay(positions, timeout=TIMEOUT)

    assert [t.status for t in tolerant.transits] == ["completed"]
    assert strict.transits[0].status == "aborted"
    assert strict.transits[0].abort_reason == "timeout"


def test_the_simulated_signal_loss_vessel_still_completes_with_the_default_timeout() -> None:
    result = replay_script.replay(simulated("signal_loss"), timeout=TIMEOUT)

    assert [t.status for t in result.transits] == ["completed"]


# --- El detector sobre datos hechos a mano --------------------------------------------------


def test_the_result_does_not_depend_on_the_order_of_the_input() -> None:
    positions = [at(0, ATLANTIC), at(20, LAKE), at(40, PACIFIC), at(5, PACIFIC, mmsi=352000002)]
    shuffled = positions[:]
    random.Random(7).shuffle(shuffled)

    assert (
        replay_script.replay(shuffled, timeout=TIMEOUT).transits
        == replay_script.replay(positions, timeout=TIMEOUT).transits
    )


def test_vessels_are_tracked_independently() -> None:
    positions = [
        at(0, ATLANTIC, 352000001),
        at(1, PACIFIC, 352000002),
        at(20, LAKE, 352000001),
        at(21, LAKE, 352000002),
        at(40, PACIFIC, 352000001),
        at(41, ATLANTIC, 352000002),
    ]

    result = replay_script.replay(positions, timeout=TIMEOUT)

    assert [(t.mmsi, t.direction, t.status) for t in result.transits] == [
        (352000001, "southbound", "completed"),
        (352000002, "northbound", "completed"),
    ]
    assert result.vessels == 2


def test_a_transit_still_open_at_the_end_is_in_progress() -> None:
    result = replay_script.replay([at(0, ATLANTIC), at(20, LAKE)], timeout=TIMEOUT)

    [transit] = result.transits
    assert (transit.status, transit.exited_at, transit.duration) == ("in_progress", None, None)
    assert transit.direction == "southbound"


def test_a_vessel_that_went_silent_is_aborted_when_other_vessels_keep_the_file_going() -> None:
    positions = [
        at(0, ATLANTIC),
        at(20, LAKE),
        *(at(m, LAKE, 352000002) for m in range(0, 120, 10)),
    ]

    result = replay_script.replay(positions, timeout=TIMEOUT)

    silent = next(t for t in result.transits if t.mmsi == 352000001)
    assert (silent.status, silent.abort_reason) == ("aborted", "timeout")
    assert silent.exited_at == T0 + timedelta(minutes=50)


def test_reversal_is_reported_as_aborted() -> None:
    result = replay_script.replay(
        [at(0, ATLANTIC), at(20, LAKE), at(40, ATLANTIC)], timeout=TIMEOUT
    )

    [transit] = result.transits
    assert (transit.status, transit.abort_reason, transit.direction) == (
        "aborted",
        "reversal",
        "southbound",
    )


def test_an_empty_input_gives_an_empty_result() -> None:
    result = replay_script.replay([], timeout=TIMEOUT)

    assert (result.transits, result.positions, result.vessels) == ([], 0, 0)
    assert "ninguno" in replay_script.render(result)


def test_completed_per_day_counts_by_exit_day_and_direction() -> None:
    day2 = 24 * 60
    positions = [
        at(0, ATLANTIC, 352000001),
        at(30, LAKE, 352000001),
        at(60, PACIFIC, 352000001),  # sale el día 1
        at(day2, PACIFIC, 352000002),
        at(day2 + 20, LAKE, 352000002),
        at(day2 + 40, ATLANTIC, 352000002),  # sale el día 2, hacia el norte
    ]

    result = replay_script.replay(positions, timeout=TIMEOUT)

    days = result.completed_per_day()
    assert list(days) == [date(2026, 11, 6), date(2026, 11, 7)]
    assert days[date(2026, 11, 6)] == Counter(southbound=1)
    assert days[date(2026, 11, 7)] == Counter(northbound=1)


# --- Lectura del fichero --------------------------------------------------------------------


def line(**changes: Any) -> str:
    record: dict[str, Any] = {
        "kind": "position",
        "mmsi": 352000001,
        "received_at": T0.isoformat(),
        "lat": 9.39,
        "lon": -79.93,
        "sog": 8.0,
        "cog": 180.0,
        "heading": 180,
        "nav_status": 0,
    }
    return json.dumps(record | changes)


def test_the_collector_output_is_read_back_as_positions() -> None:
    parsed = parse_message(
        json.dumps(
            {
                "MessageType": "PositionReport",
                "MetaData": {
                    "MMSI": 352000001,
                    "time_utc": "2026-11-06 00:00:00.000000000 +0000 UTC",
                },
                "Message": {
                    "PositionReport": {
                        "UserID": 352000001,
                        "Latitude": 9.39,
                        "Longitude": -79.93,
                        "Sog": 8.0,
                        "Cog": 180.0,
                        "TrueHeading": 180,
                        "NavigationalStatus": 0,
                        "MessageID": 1,
                        "Valid": True,
                    }
                },
            }
        ),
        received_at=T0,
    )
    written = collect.to_record(parsed)
    skipped: Counter[str] = Counter()

    [read] = replay_script.read_positions([json.dumps(written)], skipped)

    assert (read.mmsi, read.lat, read.lon, read.received_at) == (352000001, 9.39, -79.93, T0)
    assert not skipped


def test_bad_lines_are_skipped_and_counted_by_reason() -> None:
    lines = [
        line(),
        "",
        "   ",
        "not json",
        "[1, 2]",
        json.dumps({"kind": "static", "mmsi": 352000001}),
        line(mmsi=1234),
        line(mmsi=True),
        line(mmsi="352000001"),
        line(lat=91),
        line(lon=-181),
        line(lat="9.3"),
        line(lat=None),
        line(received_at="2026-11-06T00:00:00"),  # sin zona horaria
        line(received_at="ayer"),
        json.dumps({"kind": "position", "mmsi": 352000001}),
    ]
    skipped: Counter[str] = Counter()

    positions = replay_script.read_positions(lines, skipped)

    assert len(positions) == 1
    assert skipped == Counter(
        invalid_json=1, invalid_record=1, not_a_position=1, invalid_position=10
    )


# --- CLI ------------------------------------------------------------------------------------


def write_route(path: Path) -> None:
    route = [at(0, ATLANTIC), at(20, LAKE), at(40, PACIFIC)]
    path.write_text(
        "\n".join(line(received_at=p.received_at.isoformat(), lat=p.lat, lon=p.lon) for p in route)
        + "\nbasura\n"
    )


def test_main_prints_a_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file = tmp_path / "ais.jsonl"
    write_route(file)

    assert replay_script.main([str(file)]) == 0

    out = capsys.readouterr().out
    assert "Posiciones: 3  Buques: 1" in out
    assert "completed=1" in out
    assert "invalid_json=1" in out
    assert "southbound=1" in out


def test_main_json_prints_one_transit_per_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = tmp_path / "ais.jsonl"
    write_route(file)

    assert replay_script.main([str(file), "--json"]) == 0

    [row] = [json.loads(item) for item in capsys.readouterr().out.splitlines()]
    assert (row["mmsi"], row["direction"], row["status"], row["duration_minutes"]) == (
        352000001,
        "southbound",
        "completed",
        40,
    )


def test_main_reads_several_files_as_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    first.write_text(line() + "\n")
    second.write_text(
        line(received_at=(T0 + timedelta(minutes=20)).isoformat(), lat=9.15, lon=-79.75) + "\n"
    )

    assert replay_script.main([str(first), str(second), "--json"]) == 0

    [row] = [json.loads(item) for item in capsys.readouterr().out.splitlines()]
    assert row["status"] == "in_progress"


def test_main_reports_an_unreadable_file_without_its_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert replay_script.main([str(tmp_path / "missing.jsonl")]) == 1

    err = capsys.readouterr().err
    assert "missing.jsonl" in err
    assert str(tmp_path) not in err


def test_main_rejects_an_out_of_range_timeout(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as error:
        replay_script.main([str(tmp_path / "x.jsonl"), "--timeout-minutes", "1"])

    assert error.value.code == 2
