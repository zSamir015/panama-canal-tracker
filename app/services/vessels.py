"""Consulta de buques para la API (tarea 3.9). Solo lectura."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.canal_bound import CanalBoundRepository, CanalBoundRow
from app.repositories.vessels import PositionRecord, VesselRecord, VesselRepository
from app.services.exceptions import VesselNotFoundError


@dataclass(frozen=True, slots=True)
class VesselPage:
    items: list[VesselRecord]
    total: int
    page: int
    size: int


@dataclass(frozen=True, slots=True)
class VesselDetail:
    vessel: VesselRecord
    last_position: PositionRecord | None


@dataclass(frozen=True, slots=True)
class CanalBoundPage:
    items: list[CanalBoundRow]
    total: int
    page: int
    size: int


class VesselService:
    def __init__(self, session: AsyncSession) -> None:
        self._vessels = VesselRepository(session)
        self._canal_bound = CanalBoundRepository(session)

    async def list(
        self,
        *,
        page: int,
        size: int,
        ship_type: int | None = None,
        seen_since: datetime | None = None,
    ) -> VesselPage:
        items, total = await self._vessels.list(
            offset=(page - 1) * size, limit=size, ship_type=ship_type, seen_since=seen_since
        )
        return VesselPage(items=items, total=total, page=page, size=size)

    async def get(self, mmsi: int) -> VesselDetail:
        vessel = await self._vessels.get(mmsi)
        if vessel is None:
            raise VesselNotFoundError
        return VesselDetail(vessel=vessel, last_position=await self._vessels.last_position(mmsi))

    async def canal_bound(
        self,
        *,
        page: int,
        size: int,
        default_days: int,
        port: str | None = None,
        reported_since: datetime | None = None,
    ) -> CanalBoundPage:
        """Buques con destino declarado al Canal (#59): ETA próximas primero, vencidas después."""
        now = datetime.now(UTC)
        since = reported_since or now - timedelta(days=default_days)
        items, total = await self._canal_bound.list(
            offset=(page - 1) * size, limit=size, reported_since=since, now=now, port=port
        )
        return CanalBoundPage(items=items, total=total, page=page, size=size)
