"""Contrato de los endpoints de estadísticas (docs/API_DESIGN.md, "Stats")."""

from datetime import UTC, date, datetime, timedelta
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.schemas import examples
from app.schemas.examples import with_example
from app.services.ship_categories import ShipCategory

DEFAULT_WINDOW_DAYS = 30
MAX_WINDOW_DAYS = 365

Direction = Literal["northbound", "southbound"]
AnchorageName = Literal["atlantic", "pacific"]


class StatsWindow(BaseModel):
    """Parámetros de los endpoints de estadísticas. Un parámetro desconocido se rechaza (422)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    # `from` es palabra reservada en Python: el atributo es `start` y el parámetro, `from`.
    start: AwareDatetime | None = Field(
        default=None,
        alias="from",
        description=f"Inicio (con zona). Por defecto, `to` menos {DEFAULT_WINDOW_DAYS} días",
    )
    end: AwareDatetime | None = Field(
        default=None, alias="to", description="Fin, excluido (con zona). Por defecto, ahora"
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


class Window(BaseModel):
    """La ventana que se aplicó, con los valores por defecto ya resueltos."""

    start: datetime = Field(serialization_alias="from")
    end: datetime = Field(serialization_alias="to")


class DailyItem(BaseModel):
    day: date = Field(serialization_alias="date", description="Día UTC de la salida del Canal")
    direction: Direction
    ship_category: ShipCategory
    transits: int


@with_example(examples.DAILY_STATS)
class DailyStatsResponse(Window):
    items: list[DailyItem] = Field(description="Solo las combinaciones con algún tránsito")


class Distribution(BaseModel):
    """Resumen de una muestra, en minutos. Con `count` 0, los demás valores son `null`."""

    count: int
    mean_minutes: float | None
    p50_minutes: float | None
    p90_minutes: float | None


@with_example(examples.TRANSIT_DURATIONS)
class TransitDurationsResponse(Window):
    overall: Distribution
    by_direction: dict[Direction, Distribution]


@with_example(examples.WAITING_TIMES)
class WaitingTimesResponse(Window):
    overall: Distribution
    by_anchorage: dict[AnchorageName, Distribution]
