"""Acceso a la tabla `transits` (tareas 5.3 y 5.4).

Escrituras del worker (abrir y cerrar tránsitos) y lecturas para reconstruir el estado del
detector al arrancar. Solo SQL construido con SQLAlchemy y parámetros enlazados (AGENTS.md §8.6).
"""

from dataclasses import dataclass
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import cast, func, select, update
from sqlalchemy.dialects.postgresql import distinct_on, insert

from app.models.position import Position
from app.models.transit import Transit
from app.repositories.base import BaseRepository

_GEOMETRY = Geometry(geometry_type="POINT", srid=4326)


@dataclass(frozen=True, slots=True)
class OpenTransitRow:
    mmsi: int
    direction: str
    entered_at: datetime


@dataclass(frozen=True, slots=True)
class ClosedTransitRow:
    mmsi: int
    direction: str
    status: str  # `completed` o `aborted`
    abort_reason: str | None
    entered_at: datetime
    exited_at: datetime


@dataclass(frozen=True, slots=True)
class TrackPoint:
    received_at: datetime
    lon: float
    lat: float


class TransitRepository(BaseRepository):
    async def open_transit(self, row: OpenTransitRow) -> bool:
        """Crea un tránsito `in_progress`. Devuelve False si el buque ya tenía uno abierto.

        El índice único parcial garantiza uno abierto por buque; un evento repetido no falla.
        """
        statement = (
            insert(Transit)
            .values(
                vessel_mmsi=row.mmsi,
                direction=row.direction,
                status="in_progress",
                entered_at=row.entered_at,
            )
            .on_conflict_do_nothing(
                index_elements=[Transit.vessel_mmsi],
                index_where=Transit.status == "in_progress",
            )
        )
        result = await self._session.execute(statement)
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def close_transit(self, row: ClosedTransitRow) -> None:
        """Cierra el tránsito abierto del buque; si no lo hay, lo guarda ya cerrado.

        Lo segundo pasa si la apertura no llegó a guardarse (la base no respondía): el cierre
        trae todo lo necesario y así no se pierde el tránsito.
        """
        result = await self._session.execute(
            update(Transit)
            .where(Transit.vessel_mmsi == row.mmsi, Transit.status == "in_progress")
            .values(
                status=row.status,
                abort_reason=row.abort_reason,
                exited_at=row.exited_at,
                updated_at=func.now(),
            )
        )
        if result.rowcount:  # type: ignore[attr-defined]
            return
        await self._session.execute(
            insert(Transit).values(
                vessel_mmsi=row.mmsi,
                direction=row.direction,
                status=row.status,
                abort_reason=row.abort_reason,
                entered_at=row.entered_at,
                exited_at=row.exited_at,
            )
        )

    async def open_transits(self) -> list[OpenTransitRow]:
        """Todos los tránsitos `in_progress` (pocas decenas como mucho)."""
        rows = await self._session.execute(
            select(Transit.vessel_mmsi, Transit.direction, Transit.entered_at).where(
                Transit.status == "in_progress"
            )
        )
        return [
            OpenTransitRow(mmsi=mmsi, direction=direction, entered_at=entered_at)
            for mmsi, direction, entered_at in rows
        ]

    async def last_closed_transits(self, since: datetime) -> list[ClosedTransitRow]:
        """El último tránsito cerrado de cada buque, si se cerró después de `since`."""
        rows = await self._session.execute(
            select(
                Transit.vessel_mmsi,
                Transit.direction,
                Transit.status,
                Transit.abort_reason,
                Transit.entered_at,
                Transit.exited_at,
            )
            .where(Transit.status != "in_progress", Transit.exited_at > since)
            .ext(distinct_on(Transit.vessel_mmsi))
            .order_by(Transit.vessel_mmsi, Transit.exited_at.desc())
        )
        return [
            ClosedTransitRow(
                mmsi=mmsi,
                direction=direction,
                status=status,
                abort_reason=abort_reason,
                entered_at=entered_at,
                exited_at=exited_at,
            )
            for mmsi, direction, status, abort_reason, entered_at, exited_at in rows
            if exited_at is not None  # siempre, en uno cerrado (ck_transits_exited_at)
        ]

    async def track(self, mmsi: int, since: datetime, *, limit: int = 20_000) -> list[TrackPoint]:
        """Posiciones del buque desde `since`, en orden cronológico (como mucho `limit`)."""
        point = cast(Position.geom, _GEOMETRY)
        rows = await self._session.execute(
            select(Position.received_at, func.ST_X(point), func.ST_Y(point))
            .where(Position.vessel_mmsi == mmsi, Position.received_at >= since)
            .order_by(Position.received_at)
            .limit(limit)
        )
        return [TrackPoint(received_at=at, lon=lon, lat=lat) for at, lon, lat in rows]

    async def last_point(self, mmsi: int) -> TrackPoint | None:
        point = cast(Position.geom, _GEOMETRY)
        row = (
            await self._session.execute(
                select(Position.received_at, func.ST_X(point), func.ST_Y(point))
                .where(Position.vessel_mmsi == mmsi)
                .order_by(Position.received_at.desc())
                .limit(1)
            )
        ).first()
        if row is None:
            return None
        at, lon, lat = row
        return TrackPoint(received_at=at, lon=lon, lat=lat)
