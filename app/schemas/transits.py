"""Contrato de los endpoints de tránsitos (docs/API_DESIGN.md, "Transits")."""

from datetime import UTC, datetime, timedelta
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

MAX_PAGE_SIZE = 200
MAX_PAGE = 10_000
DEFAULT_WINDOW_DAYS = 7
MAX_WINDOW_DAYS = 90
# `/transits/current` no se pagina: hay como mucho un tránsito abierto por buque. El tope solo
# evita devolver una tabla entera si algún día hubiera cientos.
MAX_CURRENT = 200

Direction = Literal["northbound", "southbound"]
Status = Literal["in_progress", "completed", "aborted"]
AbortReason = Literal["timeout", "reversal"]


class TransitFilters(BaseModel):
    """Parámetros de `GET /transits`. Un parámetro desconocido se rechaza (422)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    page: int = Field(default=1, ge=1, le=MAX_PAGE)
    size: int = Field(default=50, ge=1, le=MAX_PAGE_SIZE)
    direction: Direction | None = None
    status: Status | None = None
    # `from` es palabra reservada en Python: el atributo es `start` y el parámetro, `from`.
    start: AwareDatetime | None = Field(
        default=None,
        alias="from",
        description=(
            f"Entrada al Canal desde esta fecha (con zona). Por defecto, `to` menos "
            f"{DEFAULT_WINDOW_DAYS} días"
        ),
    )
    end: AwareDatetime | None = Field(
        default=None,
        alias="to",
        description="Entrada al Canal antes de esta fecha (con zona). Por defecto, ahora",
    )

    def window(self, now: datetime) -> tuple[datetime, datetime]:
        """`(from, to)` con los valores por defecto aplicados."""
        end = self.end or now
        return self.start or end - timedelta(days=DEFAULT_WINDOW_DAYS), end

    @model_validator(mode="after")
    def bounded_window(self) -> Self:
        start, end = self.window(datetime.now(UTC))
        if start >= end:
            raise ValueError("from debe ser anterior a to")
        if end - start > timedelta(days=MAX_WINDOW_DAYS):
            raise ValueError(f"la ventana entre from y to no puede pasar de {MAX_WINDOW_DAYS} días")
        return self


class TransitResponse(BaseModel):
    """Un tránsito. `vessel_name` es texto AIS tal cual: el cliente lo muestra como texto."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mmsi: int
    vessel_name: str | None
    ship_type: int | None
    direction: Direction
    status: Status
    abort_reason: AbortReason | None = Field(description="Solo en los `aborted`")
    entered_at: datetime
    exited_at: datetime | None = Field(
        description="Salida (`completed`) o aborto (`aborted`); `null` mientras está en curso"
    )
    duration_minutes: int | None = Field(description="Solo en los `completed`")


class TransitPageResponse(BaseModel):
    items: list[TransitResponse]
    total: int
    page: int
    size: int


class CurrentTransitsResponse(BaseModel):
    items: list[TransitResponse]
    total: int = Field(description="Tránsitos en curso; puede superar `items` si pasa del tope")
