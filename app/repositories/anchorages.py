"""Acceso a la tabla `anchorage_visits` (tarea 6.1).

Escrituras del worker (abrir y cerrar visitas) y lecturas para reconstruir el estado del detector
al arrancar. Solo SQL construido con SQLAlchemy y parámetros enlazados (AGENTS.md §8.6).
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.models.anchorage_visit import AnchorageVisit
from app.models.position import Position
from app.repositories.base import BaseRepository


@dataclass(frozen=True, slots=True)
class OpenVisitRow:
    mmsi: int
    anchorage: str
    arrived_at: datetime


@dataclass(frozen=True, slots=True)
class ClosedVisitRow:
    mmsi: int
    anchorage: str
    arrived_at: datetime
    departed_at: datetime


class AnchorageRepository(BaseRepository):
    async def open_visit(self, row: OpenVisitRow) -> bool:
        """Crea una visita abierta. Devuelve False si el buque ya tenía una abierta.

        El índice único parcial garantiza una abierta por buque; un evento repetido no falla.
        """
        statement = (
            insert(AnchorageVisit)
            .values(vessel_mmsi=row.mmsi, anchorage=row.anchorage, arrived_at=row.arrived_at)
            .on_conflict_do_nothing(
                index_elements=[AnchorageVisit.vessel_mmsi],
                index_where=AnchorageVisit.departed_at.is_(None),
            )
        )
        result = await self._session.execute(statement)
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def close_visit(self, row: ClosedVisitRow) -> None:
        """Cierra la visita abierta del buque; si no la hay, la guarda ya cerrada.

        Lo segundo pasa si la apertura no llegó a guardarse (la base no respondía): el cierre trae
        todo lo necesario y así no se pierde la visita.
        """
        result = await self._session.execute(
            update(AnchorageVisit)
            .where(AnchorageVisit.vessel_mmsi == row.mmsi, AnchorageVisit.departed_at.is_(None))
            .values(departed_at=row.departed_at, updated_at=func.now())
        )
        if result.rowcount:  # type: ignore[attr-defined]
            return
        await self._session.execute(
            insert(AnchorageVisit).values(
                vessel_mmsi=row.mmsi,
                anchorage=row.anchorage,
                arrived_at=row.arrived_at,
                departed_at=row.departed_at,
            )
        )

    async def open_visits(self) -> list[OpenVisitRow]:
        """Todas las visitas abiertas (como mucho una por buque)."""
        rows = await self._session.execute(
            select(
                AnchorageVisit.vessel_mmsi, AnchorageVisit.anchorage, AnchorageVisit.arrived_at
            ).where(AnchorageVisit.departed_at.is_(None))
        )
        return [OpenVisitRow(mmsi=m, anchorage=a, arrived_at=t) for m, a, t in rows]

    async def last_signal(self, mmsi: int) -> datetime | None:
        """Hora de la última posición guardada del buque."""
        return await self._session.scalar(
            select(func.max(Position.received_at)).where(Position.vessel_mmsi == mmsi)
        )
