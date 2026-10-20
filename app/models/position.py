"""Modelo ORM de las posiciones AIS históricas."""

from datetime import datetime

from geoalchemy2 import Geography
from geoalchemy2.elements import WKBElement
from sqlalchemy import (
    REAL,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        CheckConstraint("vessel_mmsi BETWEEN 100000000 AND 999999999", name="ck_positions_mmsi"),
        CheckConstraint("sog IS NULL OR sog >= 0 AND sog < 102.3", name="ck_positions_sog"),
        CheckConstraint("cog IS NULL OR cog >= 0 AND cog < 360", name="ck_positions_cog"),
        CheckConstraint(
            "heading IS NULL OR heading >= 0 AND heading < 360", name="ck_positions_heading"
        ),
        CheckConstraint(
            "nav_status IS NULL OR nav_status BETWEEN 0 AND 15",
            name="ck_positions_nav_status",
        ),
        ForeignKeyConstraint(["vessel_mmsi"], ["vessels.mmsi"], name="fk_positions_vessel_mmsi"),
        # Timescale crea este índice al convertir la tabla en hypertable; se declara para que
        # Alembic no intente eliminarlo durante una comprobación de deriva del esquema.
        Index("positions_received_at_idx", text("received_at DESC")),
        Index("ix_positions_geom", "geom", postgresql_using="gist"),
        Index("ix_positions_vessel_mmsi_received_at", "vessel_mmsi", "received_at"),
    )

    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    vessel_mmsi: Mapped[int] = mapped_column(Integer, primary_key=True)
    geom: Mapped[WKBElement] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )
    sog: Mapped[float | None] = mapped_column(REAL)
    cog: Mapped[float | None] = mapped_column(REAL)
    heading: Mapped[float | None] = mapped_column(REAL)
    nav_status: Mapped[int | None] = mapped_column(SmallInteger)
