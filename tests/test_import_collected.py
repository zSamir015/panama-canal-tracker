"""`scripts/import_collected.py`: lectura, buques, detección de solapes y eventos (issue #187)."""

import json
from datetime import UTC, datetime, timedelta

from app.services.ais_parser import PositionUpdate
from tests.scripts_loader import load_script

importer = load_script("import_collected")

T0 = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)
TIMEOUT = timedelta(minutes=30)
ENTRANCE = (-79.93, 9.39)  # entrada del Atlántico
LAKE = (-79.75, 9.15)  # interior del Canal
ANCHORAGE = (-79.85, 9.45)  # fondeadero del Atlántico
OUTSIDE = (-79.70, 9.60)


def at(
    minutes: float,
    point: tuple[float, float],
    mmsi: int = 352000001,
    sog: float | None = 8.0,
) -> PositionUpdate:
    lon, lat = point
    return PositionUpdate(
        mmsi=mmsi,
        received_at=T0 + timedelta(minutes=minutes),
        lat=lat,
        lon=lon,
        sog=sog,
        cog=None,
        heading=None,
        nav_status=None,
    )


def position_line(minutes: float = 0, mmsi: int = 352000001) -> str:
    return json.dumps(
        {
            "kind": "position",
            "mmsi": mmsi,
            "received_at": (T0 + timedelta(minutes=minutes)).isoformat(),
            "lat": 9.39,
            "lon": -79.93,
            "sog": 5.0,
        }
    )


def static_line(minutes: float = 0, mmsi: int = 352000001, **fields: object) -> str:
    record: dict[str, object] = {
        "kind": "static",
        "mmsi": mmsi,
        "received_at": (T0 + timedelta(minutes=minutes)).isoformat(),
        "ship_type": 70,
        "length_m": 294.0,
        "beam_m": 32.0,
    }
    return json.dumps(record | fields)


# --- Lectura -----------------------------------------------------------------------------------


def test_reads_positions_and_keeps_the_latest_static_data_of_each_vessel() -> None:
    collected = importer.read_collected(
        [
            position_line(0),
            static_line(5, ship_type=60, length_m=100.0),
            static_line(10, ship_type=70, length_m=294.0),
            static_line(2, ship_type=30, length_m=10.0),  # más vieja: no sustituye
            "no es json",
        ]
    )

    assert len(collected.positions) == 1
    info = collected.statics[352000001]
    assert (info.ship_type, info.length_m, info.beam_m) == (70, 294.0, 32.0)
    assert collected.skipped["invalid_json"] == 1


def test_discards_invalid_static_values_but_keeps_the_valid_ones() -> None:
    collected = importer.read_collected(
        [static_line(0, ship_type=999, length_m=-3, beam_m=True)]  # tipo fuera de rango, etc.
    )

    info = collected.statics[352000001]
    assert (info.ship_type, info.length_m, info.beam_m) == (None, None, None)


def test_ignores_static_records_with_bad_mmsi_or_date() -> None:
    collected = importer.read_collected(
        [
            static_line(0, mmsi=12345),
            static_line(0, mmsi=True),
            static_line(0, received_at="ayer"),
            json.dumps({"kind": "static", "received_at": T0.isoformat()}),
            json.dumps([1, 2]),
            '{"kind": "static", "mmsi": "x", "received_at": "' + T0.isoformat() + '"}',
        ]
    )

    assert collected.statics == {}


def test_merging_files_keeps_the_most_recent_static_data() -> None:
    first = importer.read_collected([static_line(0, ship_type=60)])
    second = importer.read_collected([static_line(60, ship_type=70), position_line(60)])

    total = importer.merge([second, first])

    assert total.statics[352000001].ship_type == 70
    assert len(total.positions) == 1


# --- Buques y posiciones -----------------------------------------------------------------------


def test_one_vessel_row_per_mmsi_with_its_last_signal_and_static_data() -> None:
    collected = importer.Collected(
        positions=[at(0, LAKE), at(30, LAKE), at(10, LAKE, mmsi=353000002)],
        statics={
            352000001: importer.StaticInfo(T0, 70, 294.0, 32.0),
        },
    )

    rows = importer.vessel_rows(collected)

    first, second = rows
    assert (first.mmsi, first.last_seen_at, first.ship_type, first.length_m) == (
        352000001,
        T0 + timedelta(minutes=30),
        70,
        294.0,
    )
    assert (second.mmsi, second.ship_type, second.length_m, second.beam_m) == (
        353000002,
        None,
        None,
        None,
    )


def test_position_rows_keep_every_field() -> None:
    [row] = importer.position_rows([at(0, LAKE, sog=3.5)])

    assert (row.mmsi, row.lat, row.lon, row.sog, row.received_at) == (
        352000001,
        9.15,
        -79.75,
        3.5,
        T0,
    )


# --- Solapes con lo ya guardado ----------------------------------------------------------------


def test_overlap_rules() -> None:
    other = (1, T0 + timedelta(hours=1), T0 + timedelta(hours=2))
    hour = timedelta(hours=1)

    assert not importer.overlaps(T0, T0 + timedelta(minutes=30), other)  # antes
    assert not importer.overlaps(T0 + 3 * hour, T0 + 4 * hour, other)  # después
    assert importer.overlaps(T0, T0 + 90 * timedelta(minutes=1), other)  # empieza antes, entra
    assert importer.overlaps(T0 + hour, T0 + 2 * hour, other)  # mismo intervalo
    assert importer.overlaps(T0 + 90 * timedelta(minutes=1), None, other)  # candidato abierto


def test_an_open_row_overlaps_everything_after_it_starts() -> None:
    open_row = (1, T0 + timedelta(hours=5), None)

    assert not importer.overlaps(T0, T0 + timedelta(hours=1), open_row)
    assert importer.overlaps(T0 + timedelta(hours=6), T0 + timedelta(hours=7), open_row)


def test_split_overlapping_only_compares_rows_of_the_same_vessel() -> None:
    existing = [(1, T0, T0 + timedelta(hours=2))]
    candidates = [
        (1, T0 + timedelta(hours=1), T0 + timedelta(hours=3)),  # solapa, mismo buque
        (2, T0 + timedelta(hours=1), T0 + timedelta(hours=3)),  # otro buque: nuevo
        (1, T0 + timedelta(hours=5), T0 + timedelta(hours=6)),  # mismo buque, sin solape
    ]

    new, skipped = importer.split_overlapping(candidates, existing)

    assert (new, skipped) == ([1, 2], [0])


# --- Eventos recalculados con los detectores del worker ----------------------------------------


def test_only_closed_transits_are_kept_and_the_open_one_is_counted() -> None:
    positions = [
        at(0, ENTRANCE, 352000001),
        at(20, LAKE, 352000001),  # entra y se queda en silencio: se aborta por timeout
        *(at(m, LAKE, 352000002) for m in range(0, 120, 10)),  # mantiene el fichero vivo
        at(110, ENTRANCE, 352000003),  # abierto al terminar: no se importa
    ]

    derived = importer.derive_events(positions, timeout=TIMEOUT)

    assert [(t.mmsi, t.status, t.abort_reason) for t in derived.transits] == [
        (352000001, "aborted", "timeout")
    ]
    assert derived.open_transits == 1


def test_a_finished_anchorage_stay_is_a_closed_visit_and_an_ongoing_one_is_not() -> None:
    positions = [
        *(at(m, ANCHORAGE, 352000001, sog=0.1) for m in range(0, 25, 5)),
        at(30, OUTSIDE, 352000001, sog=9.0),  # se va
        *(at(m, ANCHORAGE, 352000002, sog=0.1) for m in range(0, 60, 5)),  # sigue allí
    ]

    derived = importer.derive_events(positions, timeout=TIMEOUT)

    [visit] = derived.visits
    assert (visit.mmsi, visit.anchorage) == (352000001, "atlantic")
    assert visit.departed_at > visit.arrived_at
    assert derived.open_visits == 1


def test_a_stay_whose_vessel_went_silent_is_closed_once_the_timeout_passes() -> None:
    positions = [
        *(at(m, ANCHORAGE, 352000001, sog=0.1) for m in range(0, 25, 5)),
        *(at(m, LAKE, 352000002, sog=8.0) for m in range(0, 120, 10)),  # fichero largo
    ]

    derived = importer.derive_events(positions, timeout=TIMEOUT)

    assert [v.mmsi for v in derived.visits] == [352000001]
    assert derived.open_visits == 0


def test_no_positions_means_no_events() -> None:
    derived = importer.derive_events([], timeout=TIMEOUT)

    assert (derived.transits, derived.visits, derived.open_transits, derived.open_visits) == (
        [],
        [],
        0,
        0,
    )
