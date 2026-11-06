"""Acceso a la tabla `anchorage_visits` (tarea 6.1).

Escrituras del worker (abrir y cerrar visitas) y lecturas para reconstruir el estado del detector
al arrancar. Solo SQL construido con SQLAlchemy y parámetros enlazados (AGENTS.md §8.6).
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.models.anchorage_visit import AnchorageVisit
from app.models.position import Position
from app.models.transit import Transit
from app.repositories.base import BaseRepository
from app.services.waiting import TransitCandidate, VisitCandidate


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


@dataclass(frozen=True, slots=True)
class WaitRecord:
    """La espera en fondeo previa a un tránsito, tal como la lee la API."""

    anchorage: str
    arrived_at: datetime
    departed_at: datetime | None


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

    async def count_open(self) -> int:
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(AnchorageVisit)
                .where(AnchorageVisit.departed_at.is_(None))
            )
            or 0
        )

    async def last_signal(self, mmsi: int) -> datetime | None:
        """Hora de la última posición guardada del buque."""
        return await self._session.scalar(
            select(func.max(Position.received_at)).where(Position.vessel_mmsi == mmsi)
        )

    # --- Enlace con el tránsito siguiente (6.2) -----------------------------------------------

    async def unlinked_visits(self, since: datetime) -> list[VisitCandidate]:
        """Visitas sin tránsito que llegaron desde `since`."""
        rows = await self._session.execute(
            select(
                AnchorageVisit.id,
                AnchorageVisit.vessel_mmsi,
                AnchorageVisit.anchorage,
                AnchorageVisit.arrived_at,
                AnchorageVisit.departed_at,
            ).where(AnchorageVisit.transit_id.is_(None), AnchorageVisit.arrived_at >= since)
        )
        return [VisitCandidate(*row) for row in rows]

    async def unlinked_transits(self, since: datetime) -> list[TransitCandidate]:
        """Tránsitos que empezaron desde `since` y ninguna visita tiene como siguiente."""
        taken = exists().where(AnchorageVisit.transit_id == Transit.id)
        rows = await self._session.execute(
            select(Transit.id, Transit.vessel_mmsi, Transit.direction, Transit.entered_at).where(
                Transit.entered_at >= since, ~taken
            )
        )
        return [TransitCandidate(*row) for row in rows]

    async def link(self, visit_id: UUID, transit_id: UUID) -> bool:
        """Enlaza la visita con el tránsito. False si ya estaba enlazada (otra pasada)."""
        result = await self._session.execute(
            update(AnchorageVisit)
            .where(AnchorageVisit.id == visit_id, AnchorageVisit.transit_id.is_(None))
            .values(transit_id=transit_id, updated_at=func.now())
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def wait_before(self, transit_id: UUID) -> WaitRecord | None:
        """La visita enlazada como espera previa de este tránsito, si la hay."""
        row = (
            await self._session.execute(
                select(
                    AnchorageVisit.anchorage, AnchorageVisit.arrived_at, AnchorageVisit.departed_at
                ).where(AnchorageVisit.transit_id == transit_id)
            )
        ).first()
        return WaitRecord(*row) if row else None
