"""Escritura de datos AIS: upsert de `vessels` e inserción por lotes de `positions` (tarea 3.4).

Todo es SQL construido con SQLAlchemy y parámetros enlazados: la geometría se forma con funciones
de PostGIS a partir de los números, nunca componiendo texto (AGENTS.md §8.6).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from geoalchemy2 import Geography
from sqlalchemy import cast, func
from sqlalchemy.dialects.postgresql import insert

from app.models.position import Position
from app.models.vessel import Vessel
from app.repositories.base import BaseRepository

_GEOGRAPHY_POINT = Geography(geometry_type="POINT", srid=4326, spatial_index=False)


@dataclass(frozen=True, slots=True)
class VesselRow:
    mmsi: int
    # Hora de la última posición del lote; None si el lote solo trae datos estáticos.
    last_seen_at: datetime | None = None
    name: str | None = None
    imo: int | None = None
    ship_type: int | None = None
    length_m: float | None = None
    beam_m: float | None = None


@dataclass(frozen=True, slots=True)
class PositionRow:
    received_at: datetime
    mmsi: int
    lat: float
    lon: float
    sog: float | None
    cog: float | None
    heading: int | None
    nav_status: int | None


class AisRepository(BaseRepository):
    async def upsert_vessels(self, rows: Sequence[VesselRow]) -> None:
        """Crea o actualiza buques. Un MMSI por fila: PostgreSQL no admite dos en el mismo upsert.

        - Los datos estáticos nuevos sustituyen a los viejos, pero un valor ausente (None) no borra
          uno ya conocido: un `ShipStaticData` sin nombre no deja al buque sin nombre.
        - `last_seen_at` solo avanza (GREATEST ignora los NULL).
        """
        if not rows:
            return
        statement = insert(Vessel).values(
            [
                {
                    "mmsi": row.mmsi,
                    "last_seen_at": row.last_seen_at,
                    "name": row.name,
                    "imo": row.imo,
                    "ship_type": row.ship_type,
                    "length_m": row.length_m,
                    "beam_m": row.beam_m,
                }
                # Orden fijo: dos transacciones que bloquean las mismas filas lo hacen en el mismo
                # orden y no se interbloquean.
                for row in sorted(rows, key=lambda row: row.mmsi)
            ]
        )
        excluded = statement.excluded
        statement = statement.on_conflict_do_update(
            index_elements=[Vessel.mmsi],
            set_={
                "name": func.coalesce(excluded.name, Vessel.name),
                "imo": func.coalesce(excluded.imo, Vessel.imo),
                "ship_type": func.coalesce(excluded.ship_type, Vessel.ship_type),
                "length_m": func.coalesce(excluded.length_m, Vessel.length_m),
                "beam_m": func.coalesce(excluded.beam_m, Vessel.beam_m),
                "last_seen_at": func.greatest(Vessel.last_seen_at, excluded.last_seen_at),
                "updated_at": func.now(),
            },
        )
        await self._session.execute(statement)

    async def insert_positions(self, rows: Sequence[PositionRow]) -> int:
        """Inserta posiciones y devuelve cuántas eran nuevas.

        Un mensaje recibido dos veces (misma hora y MMSI, la clave primaria) se ignora en vez de
        hacer fallar el lote entero.
        """
        if not rows:
            return 0
        statement = (
            insert(Position)
            .values(
                [
                    {
                        "received_at": row.received_at,
                        "vessel_mmsi": row.mmsi,
                        # PostGIS usa (lon, lat): x es la longitud.
                        "geom": cast(
                            func.ST_SetSRID(func.ST_MakePoint(row.lon, row.lat), 4326),
                            _GEOGRAPHY_POINT,
                        ),
                        "sog": row.sog,
                        "cog": row.cog,
                        "heading": row.heading,
                        "nav_status": row.nav_status,
                    }
                    for row in rows
                ]
            )
            .on_conflict_do_nothing(index_elements=[Position.received_at, Position.vessel_mmsi])
        )
        result = await self._session.execute(statement)
        return int(result.rowcount)  # type: ignore[attr-defined]
