"""Buques con destino declarado al Canal (#59): escritura del worker y lectura de la API."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import case, delete, func, select
from sqlalchemy.dialects.postgresql import insert

from app.models.canal_bound_vessel import CanalBoundVessel
from app.repositories.base import BaseRepository


@dataclass(frozen=True, slots=True)
class CanalBoundRow:
    mmsi: int
    destination: str
    port_locode: str
    reported_at: datetime
    name: str | None = None
    imo: int | None = None
    ship_type: int | None = None
    length_m: float | None = None
    eta: datetime | None = None
    lat: float | None = None
    lon: float | None = None


# Una ETA de hace más de esto se considera vencida (la tripulación no la actualizó): esos buques
# van después de los que tienen una ETA próxima.
ETA_GRACE = timedelta(days=1)

_COLUMNS = (
    CanalBoundVessel.mmsi,
    CanalBoundVessel.destination,
    CanalBoundVessel.port_locode,
    CanalBoundVessel.reported_at,
    CanalBoundVessel.name,
    CanalBoundVessel.imo,
    CanalBoundVessel.ship_type,
    CanalBoundVessel.length_m,
    CanalBoundVessel.eta,
    CanalBoundVessel.lat,
    CanalBoundVessel.lon,
)


class CanalBoundRepository(BaseRepository):
    async def upsert(self, rows: Sequence[CanalBoundRow]) -> None:
        """Guarda el último informe de cada buque. Un MMSI por fila.

        - Destino, puerto y ETA se sustituyen siempre: una ETA vieja engaña más que ninguna.
        - Un nombre, IMO, tipo, eslora o posición ausentes no borran los conocidos.
        - Un informe más antiguo que el guardado no lo pisa.
        """
        if not rows:
            return
        statement = insert(CanalBoundVessel).values(
            [
                {
                    "mmsi": row.mmsi,
                    "destination": row.destination,
                    "port_locode": row.port_locode,
                    "reported_at": row.reported_at,
                    "name": row.name,
                    "imo": row.imo,
                    "ship_type": row.ship_type,
                    "length_m": row.length_m,
                    "eta": row.eta,
                    "lat": row.lat,
                    "lon": row.lon,
                }
                # Orden fijo: dos transacciones sobre las mismas filas no se interbloquean.
                for row in sorted(rows, key=lambda row: row.mmsi)
            ]
        )
        excluded = statement.excluded
        # La posición va en pareja: o las dos nuevas o las dos guardadas.
        has_position = excluded.lat.is_not(None)
        statement = statement.on_conflict_do_update(
            index_elements=[CanalBoundVessel.mmsi],
            set_={
                "destination": excluded.destination,
                "port_locode": excluded.port_locode,
                "eta": excluded.eta,
                "reported_at": excluded.reported_at,
                "name": func.coalesce(excluded.name, CanalBoundVessel.name),
                "imo": func.coalesce(excluded.imo, CanalBoundVessel.imo),
                "ship_type": func.coalesce(excluded.ship_type, CanalBoundVessel.ship_type),
                "length_m": func.coalesce(excluded.length_m, CanalBoundVessel.length_m),
                "lat": case((has_position, excluded.lat), else_=CanalBoundVessel.lat),
                "lon": case((has_position, excluded.lon), else_=CanalBoundVessel.lon),
                "updated_at": func.now(),
            },
            where=excluded.reported_at >= CanalBoundVessel.reported_at,
        )
        await self._session.execute(statement)

    async def remove(self, mmsis: Sequence[int]) -> int:
        """Borra los buques que ya declaran otro destino; devuelve cuántos había."""
        if not mmsis:
            return 0
        result = await self._session.execute(
            delete(CanalBoundVessel).where(CanalBoundVessel.mmsi.in_(sorted(mmsis)))
        )
        return int(result.rowcount)  # type: ignore[attr-defined]

    async def tracked_mmsis(self) -> set[int]:
        """MMSI guardados: el worker los vigila para borrarlos si cambian de destino."""
        return set((await self._session.scalars(select(CanalBoundVessel.mmsi))).all())

    async def list(
        self,
        *,
        offset: int,
        limit: int,
        reported_since: datetime,
        now: datetime,
        port: str | None = None,
    ) -> tuple[list[CanalBoundRow], int]:
        """Una página y el total: ETA próximas primero, después las vencidas y al final sin ETA."""
        conditions = [CanalBoundVessel.reported_at >= reported_since]
        if port is not None:
            conditions.append(CanalBoundVessel.port_locode == port)
        total = await self._session.scalar(
            select(func.count()).select_from(CanalBoundVessel).where(*conditions)
        )
        rows = await self._session.execute(
            select(*_COLUMNS)
            .where(*conditions)
            .order_by(
                case((CanalBoundVessel.eta >= now - ETA_GRACE, 0), else_=1),
                CanalBoundVessel.eta.asc().nulls_last(),
                CanalBoundVessel.mmsi,
            )
            .offset(offset)
            .limit(limit)
        )
        return [CanalBoundRow(*row) for row in rows], int(total or 0)
