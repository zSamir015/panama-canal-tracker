"""Parseo y validación de mensajes AIS de AISStream."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictBool, StrictInt, StrictStr

MAX_MESSAGE_BYTES = 8 * 1024
MAX_NAME_LENGTH = 128
# El protocolo AIS admite 20 caracteres de destino; el margen cubre el relleno de AISStream.
MAX_DESTINATION_LENGTH = 64
_POSITION_REPORT = "PositionReport"
_STATIC_REPORT = "ShipStaticData"
_INTERESTING_MESSAGE_TYPES = {_POSITION_REPORT, _STATIC_REPORT}
FiniteIntOrNone = StrictInt | None

AisRejectionReason = Literal[
    "message_too_large",
    "invalid_json",
    "invalid_schema",
    "missing_position_report",
    "missing_static_data",
    "invalid_mmsi",
    "mmsi_mismatch",
    "invalid_message",
    "invalid_position",
    "no_position",
    "invalid_sog",
    "invalid_cog",
    "invalid_heading",
    "invalid_nav_status",
    "invalid_imo",
    "invalid_ship_type",
    "invalid_name",
    "name_too_long",
    "invalid_dimension",
    "invalid_destination",
    "destination_too_long",
]


class AisMessageRejected(ValueError):  # noqa: N818
    """Indica que un mensaje AIS no cumple el contrato esperado."""

    def __init__(self, reason: AisRejectionReason) -> None:
        self.reason: AisRejectionReason = reason
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
    # Texto libre que escribe la tripulación (puerto o ruta, p. ej. "PA BLB" o "USHOU>PABLB").
    destination: str | None = None
    # ETA declarada. AIS no envía el año: se elige el que deja la fecha más cerca de la recepción.
    eta: datetime | None = None
    # Última posición conocida según AISStream (`MetaData`), no la del mensaje estático, que no
    # lleva posición. Sirve para situar a los buques que están lejos del Canal (#59).
    lat: float | None = None
    lon: float | None = None
    # Hora de recepción del mensaje (la del informe del destino).
    received_at: datetime | None = None


class _MetaData(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    mmsi: StrictInt = Field(alias="MMSI")
    ship_name: StrictStr | None = Field(default=None, alias="ShipName")
    latitude: FiniteFloat | None = Field(default=None, alias="latitude")
    longitude: FiniteFloat | None = Field(default=None, alias="longitude")


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


class _Eta(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    month: StrictInt = Field(alias="Month")
    day: StrictInt = Field(alias="Day")
    hour: StrictInt = Field(alias="Hour")
    minute: StrictInt = Field(alias="Minute")


class _ShipStaticData(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    user_id: StrictInt = Field(alias="UserID")
    valid: StrictBool | None = Field(default=None, alias="Valid")
    name: StrictStr | None = Field(default=None, alias="Name")
    imo_number: StrictInt | None = Field(default=None, alias="ImoNumber")
    type: StrictInt | None = Field(default=None, alias="Type")
    dimension: _Dimension | None = Field(default=None, alias="Dimension")
    destination: StrictStr | None = Field(default=None, alias="Destination")
    eta: _Eta | None = Field(default=None, alias="Eta")


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
    except (UnicodeDecodeError, ValueError):
        raise AisMessageRejected("invalid_json") from None
    if not isinstance(decoded, dict):
        raise AisMessageRejected("invalid_schema")

    message_type = decoded.get("MessageType")
    if not isinstance(message_type, str) or message_type not in _INTERESTING_MESSAGE_TYPES:
        return None

    try:
        envelope = _Envelope.model_validate(decoded)
    except ValueError:
        raise AisMessageRejected("invalid_schema") from None

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
    lat, lon = _metadata_position(envelope.metadata)
    return VesselStatic(
        mmsi=static.user_id,
        name=name,
        imo=_normalize_imo(static.imo_number),
        ship_type=_normalize_ship_type(static.type),
        length_m=length_m,
        beam_m=beam_m,
        destination=_normalize_destination(static.destination),
        eta=_resolve_eta(static.eta, received_at),
        lat=lat,
        lon=lon,
        received_at=received_at,
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
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise AisMessageRejected("invalid_name")
    if len(value) > MAX_NAME_LENGTH:
        raise AisMessageRejected("name_too_long")
    normalized = value.rstrip("@ ")
    return normalized or None


def _normalize_destination(value: str | None) -> str | None:
    if value is None:
        return None
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise AisMessageRejected("invalid_destination")
    if len(value) > MAX_DESTINATION_LENGTH:
        raise AisMessageRejected("destination_too_long")
    normalized = value.rstrip("@ ")
    return normalized or None


def _resolve_eta(eta: _Eta | None, received_at: datetime) -> datetime | None:
    """ETA AIS (mes, día, hora, minuto en UTC) como fecha completa; None si no está disponible.

    Los valores "no disponible" de AIS (mes 0, día 0, hora 24, minuto 60) y las fechas imposibles
    (30 de febrero) dan None: una ETA rota no invalida el resto del mensaje. Sin año, se prueba el
    anterior, el actual y el siguiente al de la recepción y gana la fecha más cercana: así una ETA
    del 2 de enero recibida el 30 de diciembre cae en el año siguiente.
    """
    if eta is None:
        return None
    if not (1 <= eta.month <= 12 and 1 <= eta.day <= 31 and 0 <= eta.hour <= 23):
        return None
    if not 0 <= eta.minute <= 59:
        return None
    candidates = []
    for year in (received_at.year - 1, received_at.year, received_at.year + 1):
        try:
            candidates.append(
                datetime(year, eta.month, eta.day, eta.hour, eta.minute, tzinfo=received_at.tzinfo)
            )
        except ValueError:  # 29 de febrero en un año no bisiesto, 31 de abril...
            continue
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: abs(candidate - received_at))


def _metadata_position(metadata: _MetaData) -> tuple[float | None, float | None]:
    """Posición de `MetaData`, o (None, None) si falta o no es válida (no invalida el mensaje)."""
    lat, lon = metadata.latitude, metadata.longitude
    if lat is None or lon is None:
        return None, None
    if not -90 <= lat <= 90 or not -180 <= lon <= 180 or (lat == 0 and lon == 0):
        return None, None
    return lat, lon


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
