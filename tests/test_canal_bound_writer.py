"""Writer de destinos al Canal sin base de datos: qué se guarda y qué se borra (#59)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.ais_parser import PositionUpdate, VesselStatic
from app.workers.canal_bound_writer import build_canal_bound_batch

T0 = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


def static(mmsi: int = 636012345, seconds: int = 0, **overrides: Any) -> VesselStatic:
    values: dict[str, Any] = {
        "mmsi": mmsi,
        "name": "GULF TRADER",
        "imo": 9123456,
        "ship_type": 80,
        "length_m": 183.0,
        "beam_m": 32.0,
        "destination": "USHOU>PABLB",
        "eta": T0 + timedelta(days=5),
        "lat": 28.91,
        "lon": -94.62,
        "received_at": T0 + timedelta(seconds=seconds),
    }
    return VesselStatic(**(values | overrides))


def test_canal_bound_vessel_is_stored_with_its_port_and_report_time() -> None:
    batch = build_canal_bound_batch([static()], tracked=set())

    assert batch.removals == []
    [row] = batch.upserts
    assert (row.mmsi, row.destination, row.port_locode) == (636012345, "USHOU>PABLB", "PABLB")
    assert row.reported_at == T0
    assert row.eta == T0 + timedelta(days=5)
    assert (row.lat, row.lon) == (28.91, -94.62)


def test_other_destinations_are_ignored_without_touching_the_database() -> None:
    batch = build_canal_bound_batch(
        [static(destination="CNSHA"), static(mmsi=636000002, destination=None)], tracked=set()
    )

    assert batch.upserts == []
    assert batch.removals == []


def test_a_stored_vessel_that_changes_destination_is_removed() -> None:
    batch = build_canal_bound_batch(
        [static(destination="CNSHA"), static(mmsi=636000002, destination=None)],
        tracked={636012345, 636000002},
    )

    assert batch.upserts == []
    assert batch.removals == [636000002, 636012345]


def test_the_last_message_of_each_vessel_in_the_batch_wins() -> None:
    arrived = build_canal_bound_batch(
        [static(destination="CNSHA"), static(seconds=10)], tracked=set()
    )
    left = build_canal_bound_batch(
        [static(), static(seconds=10, destination="CNSHA")], tracked={636012345}
    )

    assert [row.reported_at for row in arrived.upserts] == [T0 + timedelta(seconds=10)]
    assert left.upserts == []
    assert left.removals == [636012345]


def test_positions_on_the_queue_are_ignored() -> None:
    position = PositionUpdate(636012345, T0, 9.0, -79.5, None, None, None, None)

    batch = build_canal_bound_batch([position], tracked={636012345})

    assert batch.upserts == []
    assert batch.removals == []
