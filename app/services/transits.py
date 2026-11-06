"""Consulta de tránsitos para la API (tarea 5.4). Solo lectura."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.anchorages import AnchorageRepository, WaitRecord
from app.repositories.transits import TransitRecord, TransitRepository
from app.services.exceptions import TransitNotFoundError


@dataclass(frozen=True, slots=True)
class TransitPage:
    items: list[TransitRecord]
    total: int
    page: int
    size: int


@dataclass(frozen=True, slots=True)
class CurrentTransits:
    items: list[TransitRecord]
    total: int


@dataclass(frozen=True, slots=True)
class TransitDetail:
    transit: TransitRecord
    wait: WaitRecord | None


class TransitService:
    def __init__(self, session: AsyncSession) -> None:
        self._transits = TransitRepository(session)
        self._anchorages = AnchorageRepository(session)

    async def list(
        self,
        *,
        page: int,
        size: int,
        entered_from: datetime,
        entered_to: datetime,
        direction: str | None = None,
        status: str | None = None,
    ) -> TransitPage:
        items, total = await self._transits.list_transits(
            offset=(page - 1) * size,
            limit=size,
            entered_from=entered_from,
            entered_to=entered_to,
            direction=direction,
            status=status,
        )
        return TransitPage(items=items, total=total, page=page, size=size)

    async def current(self, *, limit: int) -> CurrentTransits:
        items, total = await self._transits.current_transits(limit=limit)
        return CurrentTransits(items=items, total=total)

    async def get(self, transit_id: UUID) -> TransitDetail:
        record = await self._transits.get_transit(transit_id)
        if record is None:
            raise TransitNotFoundError
        return TransitDetail(transit=record, wait=await self._anchorages.wait_before(transit_id))
