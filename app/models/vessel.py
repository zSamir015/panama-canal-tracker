"""Modelo ORM de los buques observados por AIS."""

from datetime import datetime

from sqlalchemy import REAL, CheckConstraint, DateTime, Index, Integer, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Vessel(Base):
    __tablename__ = "vessels"
    __table_args__ = (
        CheckConstraint("mmsi BETWEEN 100000000 AND 999999999", name="ck_vessels_mmsi"),
        CheckConstraint("imo IS NULL OR imo BETWEEN 1 AND 9999999", name="ck_vessels_imo"),
        CheckConstraint("length_m IS NULL OR length_m > 0", name="ck_vessels_length_positive"),
        CheckConstraint("beam_m IS NULL OR beam_m > 0", name="ck_vessels_beam_positive"),
        CheckConstraint(
            "ship_type IS NULL OR ship_type BETWEEN 0 AND 99", name="ck_vessels_ship_type"
        ),
        Index("ix_vessels_last_seen_at", "last_seen_at"),
    )

    mmsi: Mapped[int] = mapped_column(Integer, primary_key=True)
    imo: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(String(128))
    ship_type: Mapped[int | None] = mapped_column(SmallInteger)
    length_m: Mapped[float | None] = mapped_column(REAL)
    beam_m: Mapped[float | None] = mapped_column(REAL)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
