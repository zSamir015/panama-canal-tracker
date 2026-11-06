"""Modelo ORM de las visitas a los fondeaderos del Canal (tarea 6.1)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    Integer,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Valores del enum de la base (migración 20261106_0005). Los mismos que `AnchorageId`.
ANCHORAGE_NAMES = ("atlantic", "pacific")


class AnchorageVisit(Base):
    """Una espera de un buque en un fondeadero.

    - `departed_at` es `NULL` mientras la visita sigue abierta.
    - `transit_id` enlaza con el tránsito siguiente (tarea 6.2); hasta entonces es `NULL`.
    - Como mucho una visita abierta por buque (índice único parcial).
    """

    __tablename__ = "anchorage_visits"
    __table_args__ = (
        CheckConstraint("vessel_mmsi BETWEEN 100000000 AND 999999999", name="ck_visits_mmsi"),
        CheckConstraint("departed_at IS NULL OR departed_at > arrived_at", name="ck_visits_order"),
        ForeignKeyConstraint(["vessel_mmsi"], ["vessels.mmsi"], name="fk_visits_vessel_mmsi"),
        ForeignKeyConstraint(
            ["transit_id"], ["transits.id"], name="fk_visits_transit_id", ondelete="SET NULL"
        ),
        Index(
            "uq_visits_one_open_per_vessel",
            "vessel_mmsi",
            unique=True,
            postgresql_where=text("departed_at IS NULL"),
        ),
        Index("ix_visits_arrived_at", "arrived_at"),
        Index("ix_visits_vessel_mmsi_arrived_at", "vessel_mmsi", "arrived_at"),
        Index("ix_visits_transit_id", "transit_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    vessel_mmsi: Mapped[int] = mapped_column(Integer, nullable=False)
    anchorage: Mapped[str] = mapped_column(
        Enum(*ANCHORAGE_NAMES, name="anchorage_name"), nullable=False
    )
    arrived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    departed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transit_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
