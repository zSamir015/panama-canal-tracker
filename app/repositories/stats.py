"""Consultas de estadísticas sobre tránsitos y esperas (tarea 6.4, ADR-0013).

Se calculan en SQL en cada consulta: `transits` y `anchorage_visits` tienen decenas de filas al
día y no son hypertables. Solo SQL construido con SQLAlchemy y parámetros enlazados.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, case, cast, extract, func, select
from sqlalchemy.sql.elements import ColumnElement

from app.models.anchorage_visit import AnchorageVisit
from app.models.transit import Transit
from app.models.vessel import Vessel
from app.repositories.base import BaseRepository
from app.services.ship_categories import CATEGORY_RANGES


@dataclass(frozen=True, slots=True)
class DailyRow:
    day: date
    direction: str
    ship_category: str
    transits: int


@dataclass(frozen=True, slots=True)
class DistributionRow:
    """Resumen de una muestra en minutos. Con `count == 0` los demás valores son `None`."""

    key: str | None  # sentido o fondeadero; `None` en el total
    count: int
    mean: float | None
    p50: float | None
    p90: float | None


def category_expression() -> ColumnElement[str]:
    """`CASE` con las mismas reglas que `ship_category` (ver `app/services/ship_categories.py`)."""
    branches: list[tuple[Any, str]] = [(Vessel.ship_type.is_(None), "unknown")]
    for category, ranges in CATEGORY_RANGES:
        condition: Any = Vessel.ship_type.between(*ranges[0])
        for low, high in ranges[1:]:
            condition = condition | Vessel.ship_type.between(low, high)
        branches.append((condition, category))
    return case(*branches, else_="other")


def _distribution(minutes: Any) -> tuple[Any, ...]:
    return (
        func.count(),
        func.avg(minutes),
        func.percentile_cont(0.5).within_group(minutes),
        func.percentile_cont(0.9).within_group(minutes),
    )


def _row(key: str | None, count: int, mean: Any, p50: Any, p90: Any) -> DistributionRow:
    def one_decimal(value: Any) -> float | None:
        return None if value is None else round(float(value), 1)

    return DistributionRow(key, int(count), one_decimal(mean), one_decimal(p50), one_decimal(p90))


class StatsRepository(BaseRepository):
    async def daily_transits(self, start: datetime, end: datetime) -> list[DailyRow]:
        """Tránsitos completados por día (UTC de la salida), sentido y categoría de buque."""
        day = cast(func.timezone("UTC", Transit.exited_at), Date).label("day")
        category = category_expression().label("category")
        rows = await self._session.execute(
            select(day, Transit.direction, category, func.count())
            .join(Vessel, Vessel.mmsi == Transit.vessel_mmsi)
            .where(
                Transit.status == "completed",
                Transit.exited_at >= start,
                Transit.exited_at < end,
            )
            .group_by(day, Transit.direction, category)
            .order_by(day, Transit.direction, category)
        )
        return [DailyRow(*row) for row in rows]

    async def transit_durations(
        self, start: datetime, end: datetime
    ) -> tuple[DistributionRow, list[DistributionRow]]:
        """Duración de los tránsitos completados que salieron en la ventana: total y por sentido."""
        minutes = Transit.duration_minutes
        window = (
            Transit.status == "completed",
            Transit.exited_at >= start,
            Transit.exited_at < end,
        )
        total = (await self._session.execute(select(*_distribution(minutes)).where(*window))).one()
        by_direction = await self._session.execute(
            select(Transit.direction, *_distribution(minutes))
            .where(*window)
            .group_by(Transit.direction)
            .order_by(Transit.direction)
        )
        return _row(None, *tuple(total)), [_row(*tuple(row)) for row in by_direction]

    async def waiting_times(
        self, start: datetime, end: datetime
    ) -> tuple[DistributionRow, list[DistributionRow]]:
        """Espera en fondeo de los tránsitos que empezaron en la ventana: total y por fondeadero.

        Cuenta los tránsitos con una visita enlazada (6.2), sea cual sea su estado: un buque que
        esperó y luego abortó también esperó.
        """
        minutes = extract("epoch", Transit.entered_at - AnchorageVisit.arrived_at) / 60
        window = (Transit.entered_at >= start, Transit.entered_at < end)
        total = (
            await self._session.execute(
                select(*_distribution(minutes))
                .select_from(AnchorageVisit)
                .join(Transit, Transit.id == AnchorageVisit.transit_id)
                .where(*window)
            )
        ).one()
        by_anchorage = await self._session.execute(
            select(AnchorageVisit.anchorage, *_distribution(minutes))
            .select_from(AnchorageVisit)
            .join(Transit, Transit.id == AnchorageVisit.transit_id)
            .where(*window)
            .group_by(AnchorageVisit.anchorage)
            .order_by(AnchorageVisit.anchorage)
        )
        return _row(None, *tuple(total)), [_row(*tuple(row)) for row in by_anchorage]
