import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.services.ais_parser import (
    AisMessageRejected,
    AisRejectionReason,
    PositionUpdate,
    VesselStatic,
    parse_message,
)

FIXTURES = Path(__file__).parent / "fixtures" / "ais_messages"
RECEIVED_AT = datetime(2026, 10, 20, 21, 0, tzinfo=UTC)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def message_with_position(**overrides: Any) -> str:
    message = json.loads(fixture("position_report.json"))
    message["Message"]["PositionReport"].update(overrides)
    return json.dumps(message)


def message_with_static(**overrides: Any) -> str:
    message = json.loads(fixture("ship_static_data.json"))
    message["Message"]["ShipStaticData"].update(overrides)
    return json.dumps(message)


def test_position_report_is_normalized_without_swapping_coordinates() -> None:
    result = parse_message(fixture("position_report.json"), received_at=RECEIVED_AT)

    assert result == PositionUpdate(
        mmsi=352001234,
        received_at=RECEIVED_AT,
        lat=9.35,
        lon=-79.91,
        sog=7.8,
        cog=145.2,
        heading=146,
        nav_status=0,
    )


def test_ship_static_data_calculates_dimensions_and_removes_padding() -> None:
    result = parse_message(fixture("ship_static_data.json"), received_at=RECEIVED_AT)

    assert result == VesselStatic(
        mmsi=352001234,
        name="PACIFIC STAR",
        imo=9876543,
        ship_type=70,
        length_m=150,
        beam_m=20,
        received_at=RECEIVED_AT,
    )


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("Sog", 102.3, None),
        ("Cog", 360, None),
        ("TrueHeading", 511, None),
        ("NavigationalStatus", 15, None),
    ],
)
def test_position_unavailable_values_become_none(
    field: str, value: float | int, expected: None
) -> None:
    result = parse_message(message_with_position(**{field: value}), received_at=RECEIVED_AT)

    assert isinstance(result, PositionUpdate)
    result_field = {
        "Sog": "sog",
        "Cog": "cog",
        "TrueHeading": "heading",
        "NavigationalStatus": "nav_status",
    }[field]
    assert getattr(result, result_field) == expected


def test_position_valid_boundary_values_are_preserved() -> None:
    result = parse_message(
        message_with_position(Sog=102.2, Cog=359.9, TrueHeading=359),
        received_at=RECEIVED_AT,
    )

    assert result == PositionUpdate(
        mmsi=352001234,
        received_at=RECEIVED_AT,
        lat=9.35,
        lon=-79.91,
        sog=102.2,
        cog=359.9,
        heading=359,
        nav_status=0,
    )


def test_static_unavailable_values_become_none() -> None:
    result = parse_message(
        message_with_static(ImoNumber=0, Type=0, Dimension={"A": 0, "B": 0, "C": 0, "D": 0}),
        received_at=RECEIVED_AT,
    )

    assert result == VesselStatic(
        352001234, "PACIFIC STAR", None, None, None, None, received_at=RECEIVED_AT
    )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("ImoNumber", 10_000_000, "invalid_imo"),
        ("Type", 100, "invalid_ship_type"),
        ("Dimension", {"A": -1, "B": 30, "C": 12, "D": 8}, "invalid_dimension"),
        ("Dimension", {"A": 10, "B": 30, "C": -1, "D": 8}, "invalid_dimension"),
        ("Dimension", {"A": 10, "B": 30, "C": 12, "D": -1}, "invalid_dimension"),
    ],
)
def test_static_invalid_values_are_rejected(
    field: str, value: int | dict[str, int], reason: AisRejectionReason
) -> None:
    with pytest.raises(AisMessageRejected, match=reason):
        parse_message(message_with_static(**{field: value}), received_at=RECEIVED_AT)


def test_static_none_name_is_handled() -> None:
    result = parse_message(message_with_static(Name=None), received_at=RECEIVED_AT)
    assert isinstance(result, VesselStatic)
    assert result.name is None


def test_parser_accepts_raw_bytes() -> None:
    raw = fixture("position_report.json").encode("utf-8")
    result = parse_message(raw, received_at=RECEIVED_AT)
    assert isinstance(result, PositionUpdate)


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (message_with_position(UserID=123), "invalid_mmsi"),
        (message_with_position(UserID=99_999_999), "invalid_mmsi"),
        (message_with_position(UserID=1_000_000_000), "invalid_mmsi"),
        (message_with_position(Latitude=91), "invalid_position"),
        (message_with_position(Latitude=-90.1), "invalid_position"),
        (message_with_position(Longitude=181), "invalid_position"),
        (message_with_position(Longitude=-180.1), "invalid_position"),
        (message_with_position(Latitude=0, Longitude=0), "no_position"),
        (message_with_position(Valid=False), "invalid_message"),
        (message_with_position(UserID=352001235), "mmsi_mismatch"),
        ("not json", "invalid_json"),
        ("9" * 5000, "invalid_json"),
        (message_with_position(Sog="rápido"), "invalid_schema"),
        (message_with_position(Latitude=float("nan")), "invalid_schema"),
        (message_with_position(Sog=-0.1), "invalid_sog"),
        (message_with_position(Sog=102.4), "invalid_sog"),
        (message_with_position(Sog=150), "invalid_sog"),
        (message_with_position(Cog=-0.1), "invalid_cog"),
        (message_with_position(Cog=360.1), "invalid_cog"),
        (message_with_position(Cog=400), "invalid_cog"),
        (message_with_position(TrueHeading=-1), "invalid_heading"),
        (message_with_position(TrueHeading=360), "invalid_heading"),
        (message_with_position(TrueHeading=400), "invalid_heading"),
        (message_with_position(NavigationalStatus=-1), "invalid_nav_status"),
        (message_with_position(NavigationalStatus=16), "invalid_nav_status"),
        (message_with_position(NavigationalStatus=20), "invalid_nav_status"),
        ("[1, 2, 3]", "invalid_schema"),
        (
            json.dumps(
                {
                    "MessageType": "PositionReport",
                    "MetaData": {"MMSI": 352001234},
                    "Message": {},
                }
            ),
            "missing_position_report",
        ),
        (
            json.dumps(
                {
                    "MessageType": "ShipStaticData",
                    "MetaData": {"MMSI": 352001234},
                    "Message": {},
                }
            ),
            "missing_static_data",
        ),
    ],
)
def test_invalid_messages_are_rejected(payload: str, reason: AisRejectionReason) -> None:
    with pytest.raises(AisMessageRejected) as error:
        parse_message(payload, received_at=RECEIVED_AT)

    assert error.value.reason == reason


def test_mmsi_valid_boundaries_are_accepted() -> None:
    msg_low = json.loads(fixture("position_report.json"))
    msg_low["MetaData"]["MMSI"] = 100_000_000
    msg_low["Message"]["PositionReport"]["UserID"] = 100_000_000
    res_low = parse_message(json.dumps(msg_low), received_at=RECEIVED_AT)
    assert isinstance(res_low, PositionUpdate)
    assert res_low.mmsi == 100_000_000

    msg_high = json.loads(fixture("position_report.json"))
    msg_high["MetaData"]["MMSI"] = 999_999_999
    msg_high["Message"]["PositionReport"]["UserID"] = 999_999_999
    res_high = parse_message(json.dumps(msg_high), received_at=RECEIVED_AT)
    assert isinstance(res_high, PositionUpdate)
    assert res_high.mmsi == 999_999_999


def test_oversized_messages_are_rejected() -> None:
    with pytest.raises(AisMessageRejected, match="message_too_large"):
        parse_message("x" * (8 * 1024 + 1), received_at=RECEIVED_AT)


@pytest.mark.parametrize(
    "payload",
    [
        json.dumps({"MessageType": "PositionReport"}),
        json.dumps(
            {
                "MessageType": "PositionReport",
                "MetaData": {"MMSI": 352001234},
                "Message": {"PositionReport": {"UserID": 352001234}},
            }
        ),
    ],
)
def test_required_fields_are_validated(payload: str) -> None:
    with pytest.raises(AisMessageRejected, match="invalid_schema"):
        parse_message(payload, received_at=RECEIVED_AT)


@pytest.mark.parametrize(
    "payload",
    [
        json.dumps({"MessageType": "SubscriptionConfirmation", "Data": "ignored"}),
        json.dumps({"MessageType": []}),
        json.dumps({"MessageType": {}}),
        json.dumps({"MessageType": 12345}),
    ],
)
def test_uninteresting_messages_are_ignored(payload: str) -> None:
    assert parse_message(payload, received_at=RECEIVED_AT) is None


def test_name_is_preserved() -> None:
    malicious = parse_message(
        message_with_static(Name="<img src=x onerror=alert(1)>"),
        received_at=RECEIVED_AT,
    )
    assert isinstance(malicious, VesselStatic)
    assert malicious.name == "<img src=x onerror=alert(1)>"


def test_name_maximum_valid_length_is_accepted() -> None:
    max_name = "A" * 128
    result = parse_message(message_with_static(Name=max_name), received_at=RECEIVED_AT)
    assert isinstance(result, VesselStatic)
    assert result.name == max_name


@pytest.mark.parametrize(
    ("bad_name", "reason"),
    [
        ("BAD\nNAME", "invalid_name"),
        ("DEL\x7fNAME", "invalid_name"),
        ("C1\x85NAME", "invalid_name"),
        ("PACIFIC\u202eRATS", "invalid_name"),
        ("A" * 129, "name_too_long"),
        ("A" * 4000, "name_too_long"),
    ],
)
def test_name_control_characters_and_length_are_rejected(
    bad_name: str, reason: AisRejectionReason
) -> None:
    with pytest.raises(AisMessageRejected) as error:
        parse_message(message_with_static(Name=bad_name), received_at=RECEIVED_AT)

    assert error.value.reason == reason


def test_parser_uses_supplied_timestamp() -> None:
    result = parse_message(fixture("position_report.json"), received_at=RECEIVED_AT)

    assert isinstance(result, PositionUpdate)
    assert result.received_at is RECEIVED_AT


# --- Destino, ETA y posición de `MetaData` (#59) --------------------------------------------


def message_with_canal_bound(metadata: dict[str, Any] | None = None, **overrides: Any) -> str:
    message = json.loads(fixture("ship_static_data_canal_bound.json"))
    message["Message"]["ShipStaticData"].update(overrides)
    message["MetaData"].update(metadata or {})
    return json.dumps(message)


def test_static_destination_eta_and_metadata_position_are_parsed() -> None:
    result = parse_message(fixture("ship_static_data_canal_bound.json"), received_at=RECEIVED_AT)

    assert result == VesselStatic(
        mmsi=636012345,
        name="GULF TRADER",
        imo=9123456,
        ship_type=80,
        length_m=183,
        beam_m=32,
        destination="USHOU>PABLB",
        eta=datetime(2026, 10, 27, 6, 30, tzinfo=UTC),
        lat=28.91,
        lon=-94.62,
        received_at=RECEIVED_AT,
    )


@pytest.mark.parametrize("destination", [None, "", "                    ", "@@@@@@@@@@@@@@@@@@@@"])
def test_static_empty_destination_becomes_none(destination: str | None) -> None:
    result = parse_message(
        message_with_canal_bound(Destination=destination), received_at=RECEIVED_AT
    )

    assert isinstance(result, VesselStatic)
    assert result.destination is None


def test_static_destination_is_preserved_as_text() -> None:
    result = parse_message(
        message_with_canal_bound(Destination="<b>PA BLB</b>"), received_at=RECEIVED_AT
    )

    assert isinstance(result, VesselStatic)
    assert result.destination == "<b>PA BLB</b>"


@pytest.mark.parametrize(
    ("destination", "reason"),
    [
        ("PA\nBLB", "invalid_destination"),
        ("PA‮BLB", "invalid_destination"),
        ("A" * 65, "destination_too_long"),
    ],
)
def test_static_invalid_destination_is_rejected(
    destination: str, reason: AisRejectionReason
) -> None:
    with pytest.raises(AisMessageRejected) as error:
        parse_message(message_with_canal_bound(Destination=destination), received_at=RECEIVED_AT)

    assert error.value.reason == reason


@pytest.mark.parametrize(
    "eta",
    [
        {"Month": 0, "Day": 0, "Hour": 24, "Minute": 60},  # "no disponible" según AIS
        {"Month": 10, "Day": 0, "Hour": 6, "Minute": 30},
        {"Month": 10, "Day": 27, "Hour": 24, "Minute": 0},
        {"Month": 10, "Day": 27, "Hour": 6, "Minute": 60},
        {"Month": 13, "Day": 1, "Hour": 0, "Minute": 0},
        {"Month": 2, "Day": 30, "Hour": 0, "Minute": 0},
        {"Month": 4, "Day": 31, "Hour": 0, "Minute": 0},
    ],
)
def test_static_unavailable_or_impossible_eta_becomes_none(eta: dict[str, int]) -> None:
    result = parse_message(message_with_canal_bound(Eta=eta), received_at=RECEIVED_AT)

    assert isinstance(result, VesselStatic)
    assert result.eta is None
    assert result.destination == "USHOU>PABLB"


@pytest.mark.parametrize(
    ("received_at", "eta", "expected"),
    [
        # ETA a principios de enero recibida a final de diciembre: año siguiente.
        (
            datetime(2026, 12, 30, 12, 0, tzinfo=UTC),
            {"Month": 1, "Day": 2, "Hour": 8, "Minute": 0},
            datetime(2027, 1, 2, 8, 0, tzinfo=UTC),
        ),
        # ETA ya pasada de final de diciembre recibida en enero: año anterior.
        (
            datetime(2027, 1, 2, 12, 0, tzinfo=UTC),
            {"Month": 12, "Day": 30, "Hour": 8, "Minute": 0},
            datetime(2026, 12, 30, 8, 0, tzinfo=UTC),
        ),
        # 29 de febrero: solo existe en el año bisiesto cercano.
        (
            datetime(2028, 2, 20, 0, 0, tzinfo=UTC),
            {"Month": 2, "Day": 29, "Hour": 0, "Minute": 0},
            datetime(2028, 2, 29, 0, 0, tzinfo=UTC),
        ),
    ],
)
def test_static_eta_year_is_closest_to_reception(
    received_at: datetime, eta: dict[str, int], expected: datetime
) -> None:
    result = parse_message(message_with_canal_bound(Eta=eta), received_at=received_at)

    assert isinstance(result, VesselStatic)
    assert result.eta == expected


@pytest.mark.parametrize(
    "position",
    [
        {"latitude": None, "longitude": None},
        {"latitude": 28.91, "longitude": None},
        {"latitude": 91.0, "longitude": -94.62},
        {"latitude": 28.91, "longitude": 181.0},
        {"latitude": 0.0, "longitude": 0.0},
    ],
)
def test_static_missing_or_invalid_metadata_position_becomes_none(
    position: dict[str, float | None],
) -> None:
    result = parse_message(message_with_canal_bound(metadata=position), received_at=RECEIVED_AT)

    assert isinstance(result, VesselStatic)
    assert (result.lat, result.lon) == (None, None)
    assert result.destination == "USHOU>PABLB"
