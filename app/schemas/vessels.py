"""Contrato de los endpoints de buques (docs/API_DESIGN.md, "Vessels")."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

MAX_PAGE_SIZE = 200
MAX_PAGE = 10_000
# Hasta dónde se puede mirar atrás con `seen_since`; más allá no aporta y obliga a recorrer más.
MAX_SEEN_SINCE_DAYS = 90

Mmsi = Annotated[int, Field(ge=100_000_000, le=999_999_999)]


class VesselFilters(BaseModel):
    """Parámetros de `GET /vessels`. Un parámetro desconocido se rechaza (422)."""

    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1, le=MAX_PAGE)
    size: int = Field(default=50, ge=1, le=MAX_PAGE_SIZE)
    ship_type: int | None = Field(default=None, ge=1, le=99, description="Tipo AIS (70 = carga)")
    seen_since: AwareDatetime | None = Field(
        default=None,
        description=(
            f"Solo buques vistos desde esta fecha (con zona; máx. {MAX_SEEN_SINCE_DAYS} días atrás)"
        ),
    )

    @field_validator("seen_since")
    @classmethod
    def bounded_seen_since(cls, value: datetime | None) -> datetime | None:
        if value is not None and value < datetime.now(UTC) - timedelta(days=MAX_SEEN_SINCE_DAYS):
            raise ValueError(f"seen_since no puede ser anterior a {MAX_SEEN_SINCE_DAYS} días")
        return value


class VesselResponse(BaseModel):
    """Datos estáticos del buque. `name` es texto AIS tal cual: se muestra como texto."""

    model_config = ConfigDict(from_attributes=True)

    mmsi: int
    name: str | None
    imo: int | None
    ship_type: int | None
    length_m: float | None
    beam_m: float | None
    last_seen_at: datetime | None


class PositionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    received_at: datetime
    lat: float
    lon: float
    sog: float | None
    cog: float | None
    heading: float | None
    nav_status: int | None


class VesselDetailResponse(VesselResponse):
    last_position: PositionResponse | None


class VesselPageResponse(BaseModel):
    items: list[VesselResponse]
    total: int
    page: int
    size: int
