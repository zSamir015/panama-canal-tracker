"""Modelo ORM de los tránsitos del Canal detectados a partir de AIS (tarea 5.3)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Computed,
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

# Valores de los enums de la base (migración 20261106_0004). Los mismos que usa el detector
# (`app/services/transit_detector.py`).
TRANSIT_DIRECTIONS = ("northbound", "southbound")
TRANSIT_STATUSES = ("in_progress", "completed", "aborted")
TRANSIT_ABORT_REASONS = ("timeout", "reversal")


class Transit(Base):
    """Un tránsito de un buque entre las dos entradas del Canal.

    - La dirección se conoce desde que se abre: la da la entrada por la que llegó.
    - `exited_at` es la hora de salida (`completed`) o del aborto (`aborted`); `NULL` mientras
      está `in_progress`.
    - Como mucho un tránsito `in_progress` por buque (índice único parcial).
    """

    __tablename__ = "transits"
    __table_args__ = (
        CheckConstraint("vessel_mmsi BETWEEN 100000000 AND 999999999", name="ck_transits_mmsi"),
        CheckConstraint(
            "(status = 'in_progress') = (exited_at IS NULL)", name="ck_transits_exited_at"
        ),
        CheckConstraint("exited_at IS NULL OR exited_at > entered_at", name="ck_transits_order"),
        CheckConstraint(
            "(status = 'aborted') = (abort_reason IS NOT NULL)", name="ck_transits_abort_reason"
        ),
        ForeignKeyConstraint(["vessel_mmsi"], ["vessels.mmsi"], name="fk_transits_vessel_mmsi"),
        Index(
            "uq_transits_one_in_progress_per_vessel",
            "vessel_mmsi",
            unique=True,
            postgresql_where=text("status = 'in_progress'"),
        ),
        Index("ix_transits_entered_at", "entered_at"),
        Index("ix_transits_vessel_mmsi_entered_at", "vessel_mmsi", "entered_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    vessel_mmsi: Mapped[int] = mapped_column(Integer, nullable=False)
    direction: Mapped[str] = mapped_column(
        Enum(*TRANSIT_DIRECTIONS, name="transit_direction"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum(*TRANSIT_STATUSES, name="transit_status"), nullable=False
    )
    abort_reason: Mapped[str | None] = mapped_column(
        Enum(*TRANSIT_ABORT_REASONS, name="transit_abort_reason")
    )
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Solo de los completados: la duración de un aborto no es la de un tránsito.
    duration_minutes: Mapped[int | None] = mapped_column(
        Integer,
        Computed(
            "CASE WHEN status = 'completed' "
            "THEN (EXTRACT(EPOCH FROM exited_at - entered_at) / 60)::integer END",
            persisted=True,
        ),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
