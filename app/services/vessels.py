"""Consulta de buques para la API (tarea 3.9). Solo lectura."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

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


class VesselService:
    def __init__(self, session: AsyncSession) -> None:
        self._vessels = VesselRepository(session)

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
