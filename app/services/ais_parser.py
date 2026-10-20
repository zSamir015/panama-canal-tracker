"""Parseo y validación de mensajes AIS de AISStream."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictBool, StrictInt, StrictStr

MAX_MESSAGE_BYTES = 8 * 1024
_POSITION_REPORT = "PositionReport"
_STATIC_REPORT = "ShipStaticData"
_INTERESTING_MESSAGE_TYPES = {_POSITION_REPORT, _STATIC_REPORT}
FiniteIntOrNone = StrictInt | None


class AisMessageRejected(ValueError):  # noqa: N818
    """Indica que un mensaje AIS no cumple el contrato esperado."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class PositionUpdate:
    """Posición AIS normalizada para persistencia."""

    mmsi: int
    received_at: datetime
    lat: float
    lon: float
    sog: float | None
    cog: float | None
    heading: int | None
    nav_status: int | None


@dataclass(frozen=True, slots=True)
class VesselStatic:
    """Datos estáticos AIS normalizados para persistencia."""

    mmsi: int
    name: str | None
    imo: int | None
    ship_type: int | None
    length_m: float | None
    beam_m: float | None


class _MetaData(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    mmsi: StrictInt = Field(alias="MMSI")
    ship_name: StrictStr | None = Field(default=None, alias="ShipName")


class _PositionReport(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    user_id: StrictInt = Field(alias="UserID")
    valid: StrictBool | None = Field(default=None, alias="Valid")
    latitude: FiniteFloat = Field(alias="Latitude")
    longitude: FiniteFloat = Field(alias="Longitude")
    sog: FiniteFloat | None = Field(default=None, alias="Sog")
    cog: FiniteFloat | None = Field(default=None, alias="Cog")
    true_heading: FiniteIntOrNone = Field(default=None, alias="TrueHeading")
    navigational_status: FiniteIntOrNone = Field(default=None, alias="NavigationalStatus")


class _Dimension(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    a: FiniteFloat | None = Field(default=None, alias="A")
    b: FiniteFloat | None = Field(default=None, alias="B")
    c: FiniteFloat | None = Field(default=None, alias="C")
    d: FiniteFloat | None = Field(default=None, alias="D")


class _ShipStaticData(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    user_id: StrictInt = Field(alias="UserID")
    valid: StrictBool | None = Field(default=None, alias="Valid")
    name: StrictStr | None = Field(default=None, alias="Name")
    imo_number: StrictInt | None = Field(default=None, alias="ImoNumber")
    type: StrictInt | None = Field(default=None, alias="Type")
    dimension: _Dimension | None = Field(default=None, alias="Dimension")


class _Message(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    position_report: _PositionReport | None = Field(default=None, alias="PositionReport")
    ship_static_data: _ShipStaticData | None = Field(default=None, alias="ShipStaticData")


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    message_type: StrictStr = Field(alias="MessageType")
    metadata: _MetaData = Field(alias="MetaData")
    message: _Message = Field(alias="Message")


def parse_message(
    raw: str | bytes,
    *,
    received_at: datetime,
) -> PositionUpdate | VesselStatic | None:
    """Convierte un mensaje AISStream en un objeto de dominio inmutable."""
    if isinstance(raw, str):
        raw_bytes = raw.encode("utf-8")
    else:
        raw_bytes = raw
    if len(raw_bytes) > MAX_MESSAGE_BYTES:
        raise AisMessageRejected("message_too_large")

    try:
        decoded: Any = json.loads(raw_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AisMessageRejected("invalid_json") from exc
    if not isinstance(decoded, dict):
        raise AisMessageRejected("invalid_schema")

    message_type = decoded.get("MessageType")
    if message_type not in _INTERESTING_MESSAGE_TYPES:
        return None

    try:
        envelope = _Envelope.model_validate(decoded)
    except ValueError as exc:
        raise AisMessageRejected("invalid_schema") from exc

    if envelope.message_type == _POSITION_REPORT:
        report = envelope.message.position_report
        if report is None:
            raise AisMessageRejected("missing_position_report")
        _validate_common(envelope.metadata.mmsi, report.user_id, report.valid)
        _validate_coordinates(report.latitude, report.longitude)
        return PositionUpdate(
            mmsi=report.user_id,
            received_at=received_at,
            lat=report.latitude,
            lon=report.longitude,
            sog=_normalize_sog(report.sog),
            cog=_normalize_cog(report.cog),
            heading=_normalize_heading(report.true_heading),
            nav_status=_normalize_nav_status(report.navigational_status),
        )

    static = envelope.message.ship_static_data
    if static is None:
        raise AisMessageRejected("missing_static_data")
    _validate_common(envelope.metadata.mmsi, static.user_id, static.valid)
    name = _normalize_name(static.name)
    length_m = _dimension_sum(static.dimension, "a", "b")
    beam_m = _dimension_sum(static.dimension, "c", "d")
    return VesselStatic(
        mmsi=static.user_id,
        name=name,
        imo=_normalize_imo(static.imo_number),
        ship_type=_normalize_ship_type(static.type),
        length_m=length_m,
        beam_m=beam_m,
    )


def _validate_common(metadata_mmsi: int, user_id: int, valid: bool | None) -> None:
    if not _is_valid_mmsi(user_id) or not _is_valid_mmsi(metadata_mmsi):
        raise AisMessageRejected("invalid_mmsi")
    if metadata_mmsi != user_id:
        raise AisMessageRejected("mmsi_mismatch")
    if valid is False:
        raise AisMessageRejected("invalid_message")


def _validate_coordinates(latitude: float, longitude: float) -> None:
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise AisMessageRejected("invalid_position")
    if latitude == 0 and longitude == 0:
        raise AisMessageRejected("no_position")


def _is_valid_mmsi(mmsi: int) -> bool:
    return 100_000_000 <= mmsi <= 999_999_999


def _normalize_sog(value: float | None) -> float | None:
    if value is None or value == 102.3:
        return None
    if not 0 <= value < 102.3:
        raise AisMessageRejected("invalid_sog")
    return value


def _normalize_cog(value: float | None) -> float | None:
    if value is None or value == 360:
        return None
    if not 0 <= value < 360:
        raise AisMessageRejected("invalid_cog")
    return value


def _normalize_heading(value: int | None) -> int | None:
    if value is None or value == 511:
        return None
    if not 0 <= value < 360:
        raise AisMessageRejected("invalid_heading")
    return value


def _normalize_nav_status(value: int | None) -> int | None:
    if value is None or value == 15:
        return None
    if not 0 <= value <= 14:
        raise AisMessageRejected("invalid_nav_status")
    return value


def _normalize_zero(value: int | None) -> int | None:
    return None if value in (None, 0) else value


def _normalize_imo(value: int | None) -> int | None:
    normalized = _normalize_zero(value)
    if normalized is not None and not 1 <= normalized <= 9_999_999:
        raise AisMessageRejected("invalid_imo")
    return normalized


def _normalize_ship_type(value: int | None) -> int | None:
    normalized = _normalize_zero(value)
    if normalized is not None and not 1 <= normalized <= 99:
        raise AisMessageRejected("invalid_ship_type")
    return normalized


def _normalize_name(value: str | None) -> str | None:
    if value is None:
        return None
    if any(ord(character) < 32 for character in value):
        raise AisMessageRejected("invalid_name")
    normalized = value.rstrip("@ ")
    return normalized or None


def _dimension_sum(
    dimension: _Dimension | None,
    first: Literal["a", "c"],
    second: Literal["b", "d"],
) -> float | None:
    if dimension is None:
        return None
    left = dimension.a if first == "a" else dimension.c
    right = dimension.b if second == "b" else dimension.d
    if (left is not None and left < 0) or (right is not None and right < 0):
        raise AisMessageRejected("invalid_dimension")
    if left is None or right is None or left == 0 or right == 0:
        return None
    return left + right
