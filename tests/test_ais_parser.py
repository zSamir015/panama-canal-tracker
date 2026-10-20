import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.services.ais_parser import (
    AisMessageRejected,
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

    assert result == VesselStatic(352001234, "PACIFIC STAR", None, None, None, None)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("ImoNumber", 10_000_000, "invalid_imo"),
        ("Type", 100, "invalid_ship_type"),
        ("Dimension", {"A": -1, "B": 30, "C": 12, "D": 8}, "invalid_dimension"),
    ],
)
def test_static_invalid_values_are_rejected(
    field: str, value: int | dict[str, int], reason: str
) -> None:
    with pytest.raises(AisMessageRejected, match=reason):
        parse_message(message_with_static(**{field: value}), received_at=RECEIVED_AT)


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (message_with_position(UserID=123), "invalid_mmsi"),
        (message_with_position(UserID=1_000_000_000), "invalid_mmsi"),
        (message_with_position(Latitude=91), "invalid_position"),
        (message_with_position(Longitude=181), "invalid_position"),
        (message_with_position(Latitude=0, Longitude=0), "no_position"),
        (message_with_position(Valid=False), "invalid_message"),
        (message_with_position(UserID=352001235), "mmsi_mismatch"),
        ("not json", "invalid_json"),
        (message_with_position(Sog="rápido"), "invalid_schema"),
        (message_with_position(Latitude=float("nan")), "invalid_schema"),
    ],
)
def test_invalid_messages_are_rejected(payload: str, reason: str) -> None:
    with pytest.raises(AisMessageRejected) as error:
        parse_message(payload, received_at=RECEIVED_AT)

    assert error.value.reason == reason


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


def test_uninteresting_messages_are_ignored() -> None:
    payload = json.dumps({"MessageType": "SubscriptionConfirmation", "Data": "ignored"})

    assert parse_message(payload, received_at=RECEIVED_AT) is None


def test_name_is_preserved_but_control_characters_are_rejected() -> None:
    malicious = parse_message(
        message_with_static(Name="<img src=x onerror=alert(1)>"),
        received_at=RECEIVED_AT,
    )
    assert isinstance(malicious, VesselStatic)
    assert malicious.name == "<img src=x onerror=alert(1)>"

    with pytest.raises(AisMessageRejected, match="invalid_name"):
        parse_message(message_with_static(Name="BAD\nNAME"), received_at=RECEIVED_AT)


def test_parser_uses_supplied_timestamp() -> None:
    result = parse_message(fixture("position_report.json"), received_at=RECEIVED_AT)

    assert isinstance(result, PositionUpdate)
    assert result.received_at is RECEIVED_AT
