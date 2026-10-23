"""Lecturas de buques y de su última posición (tarea 3.9)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import distinct_on

from app.models.position import Position
from app.models.vessel import Vessel
from app.repositories.base import BaseRepository


@dataclass(frozen=True, slots=True)
class VesselRecord:
    mmsi: int
    name: str | None
    imo: int | None
    ship_type: int | None
    length_m: float | None
    beam_m: float | None
    last_seen_at: datetime | None


@dataclass(frozen=True, slots=True)
class PositionRecord:
    received_at: datetime
    lat: float
    lon: float
    sog: float | None
    cog: float | None
    heading: float | None
    nav_status: int | None


@dataclass(frozen=True, slots=True)
class LivePositionRecord:
    mmsi: int
    lon: float
    lat: float
    cog: float | None
    sog: float | None
    received_at: datetime
    name: str | None
    ship_type: int | None


_VESSEL_COLUMNS = (
    Vessel.mmsi,
    Vessel.name,
    Vessel.imo,
    Vessel.ship_type,
    Vessel.length_m,
    Vessel.beam_m,
    Vessel.last_seen_at,
)


class VesselRepository(BaseRepository):
    async def list(
        self,
        *,
        offset: int,
        limit: int,
        ship_type: int | None = None,
        seen_since: datetime | None = None,
    ) -> tuple[list[VesselRecord], int]:
        """Una página de buques (los vistos más recientemente primero) y el total filtrado."""
        conditions = []
        if ship_type is not None:
            conditions.append(Vessel.ship_type == ship_type)
        if seen_since is not None:
            conditions.append(Vessel.last_seen_at >= seen_since)

        total = await self._session.scalar(
            select(func.count()).select_from(Vessel).where(*conditions)
        )
        rows = await self._session.execute(
            select(*_VESSEL_COLUMNS)
            .where(*conditions)
            # Orden total y estable: sin el MMSI, dos buques con la misma hora podrían cambiar de
            # página entre una petición y la siguiente.
            .order_by(Vessel.last_seen_at.desc().nulls_last(), Vessel.mmsi)
            .offset(offset)
            .limit(limit)
        )
        return [VesselRecord(*row) for row in rows], int(total or 0)

    async def get(self, mmsi: int) -> VesselRecord | None:
        row = (
            await self._session.execute(select(*_VESSEL_COLUMNS).where(Vessel.mmsi == mmsi))
        ).one_or_none()
        return VesselRecord(*row) if row else None

    async def last_position(self, mmsi: int) -> PositionRecord | None:
        """La posición más reciente; usa el índice (vessel_mmsi, received_at)."""
        point = cast(Position.geom, Geometry)
        row = (
            await self._session.execute(
                select(
                    Position.received_at,
                    func.ST_Y(point),  # latitud
                    func.ST_X(point),  # longitud
                    Position.sog,
                    Position.cog,
                    Position.heading,
                    Position.nav_status,
                )
                .where(Position.vessel_mmsi == mmsi)
                .order_by(Position.received_at.desc())
                .limit(1)
            )
        ).one_or_none()
        return PositionRecord(*row) if row else None

    async def latest_positions_in(
        self,
        *,
        min_lon: float,
        min_lat: float,
        max_lon: float,
        max_lat: float,
        since: datetime,
        limit: int,
    ) -> Sequence[LivePositionRecord]:
        """Última posición de cada buque con señal desde `since`, si cae dentro de la caja.

        Primero la última de cada buque y después el filtro: un buque que ya salió de la caja no
        aparece por una posición antigua de dentro. Los más recientes primero, hasta `limit`.
        """
        point = cast(Position.geom, Geometry)
        latest = (
            select(
                Position.vessel_mmsi.label("mmsi"),
                func.ST_X(point).label("lon"),
                func.ST_Y(point).label("lat"),
                Position.cog,
                Position.sog,
                Position.received_at,
            )
            .where(Position.received_at >= since)  # acota los chunks de la hypertable
            .ext(distinct_on(Position.vessel_mmsi))
            .order_by(Position.vessel_mmsi, Position.received_at.desc())
            .subquery()
        )
        rows = await self._session.execute(
            select(
                latest.c.mmsi,
                latest.c.lon,
                latest.c.lat,
                latest.c.cog,
                latest.c.sog,
                latest.c.received_at,
                Vessel.name,
                Vessel.ship_type,
            )
            .join(Vessel, Vessel.mmsi == latest.c.mmsi)
            .where(
                latest.c.lon.between(min_lon, max_lon),
                latest.c.lat.between(min_lat, max_lat),
            )
            .order_by(latest.c.received_at.desc(), latest.c.mmsi)
            .limit(limit)
        )
        return [LivePositionRecord(*row) for row in rows]
