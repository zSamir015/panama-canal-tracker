"""Estadísticas de tránsitos y esperas para la API (tarea 6.4). Solo lectura."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.stats import DailyRow, DistributionRow, StatsRepository


@dataclass(frozen=True, slots=True)
class Summary:
    """Resumen de una muestra en minutos. Con `count == 0` los demás valores son `None`."""

    count: int
    mean: float | None
    p50: float | None
    p90: float | None


@dataclass(frozen=True, slots=True)
class Breakdown:
    overall: Summary
    by_key: dict[str, Summary]


def _summary(row: DistributionRow) -> Summary:
    return Summary(count=row.count, mean=row.mean, p50=row.p50, p90=row.p90)


def _complete(keys: tuple[str, ...], rows: list[DistributionRow]) -> dict[str, Summary]:
    """Una entrada por cada clave posible, con 0 muestras donde no hubo ninguna."""
    found = {row.key: _summary(row) for row in rows if row.key is not None}
    return {key: found.get(key, Summary(0, None, None, None)) for key in keys}


class StatsService:
    def __init__(self, session: AsyncSession) -> None:
        self._stats = StatsRepository(session)

    async def daily(self, start: datetime, end: datetime) -> list[DailyRow]:
        return await self._stats.daily_transits(start, end)

    async def transit_durations(self, start: datetime, end: datetime) -> Breakdown:
        overall, rows = await self._stats.transit_durations(start, end)
        return Breakdown(_summary(overall), _complete(("northbound", "southbound"), rows))

    async def waiting_times(self, start: datetime, end: datetime) -> Breakdown:
        overall, rows = await self._stats.waiting_times(start, end)
        return Breakdown(_summary(overall), _complete(("atlantic", "pacific"), rows))
