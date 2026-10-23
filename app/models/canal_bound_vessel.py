"""Modelo ORM de los buques que declaran como destino el Canal de Panamá (#59, ADR-0009)."""

from datetime import datetime

from sqlalchemy import (
    REAL,
    CheckConstraint,
    DateTime,
    Double,
    Index,
    Integer,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CanalBoundVessel(Base):
    """Último informe estático de cada buque cuyo destino declarado es el Canal.

    Va aparte de `vessels`, que son los buques vistos en el área del Canal: uno de estos puede
    estar al otro lado del mundo. Una fila por buque; si declara otro destino, se borra.
    """

    __tablename__ = "canal_bound_vessels"
    __table_args__ = (
        CheckConstraint("mmsi BETWEEN 100000000 AND 999999999", name="ck_canal_bound_mmsi"),
        CheckConstraint("imo IS NULL OR imo BETWEEN 1 AND 9999999", name="ck_canal_bound_imo"),
        CheckConstraint(
            "ship_type IS NULL OR ship_type BETWEEN 0 AND 99", name="ck_canal_bound_ship_type"
        ),
        CheckConstraint("length_m IS NULL OR length_m > 0", name="ck_canal_bound_length_positive"),
        CheckConstraint(
            "port_locode = 'PA' OR port_locode ~ '^PA[A-Z]{3}$'", name="ck_canal_bound_port"
        ),
        CheckConstraint(
            "(lat IS NULL) = (lon IS NULL)"
            " AND (lat IS NULL OR lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180)",
            name="ck_canal_bound_position",
        ),
        Index("ix_canal_bound_vessels_reported_at", "reported_at"),
    )

    mmsi: Mapped[int] = mapped_column(Integer, primary_key=True)
    imo: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(String(128))
    ship_type: Mapped[int | None] = mapped_column(SmallInteger)
    length_m: Mapped[float | None] = mapped_column(REAL)
    # Texto declarado tal cual (se muestra como texto, nunca como HTML) y puerto detectado.
    destination: Mapped[str] = mapped_column(String(64), nullable=False)
    port_locode: Mapped[str] = mapped_column(String(5), nullable=False)
    eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Posición que AISStream adjunta al mensaje (`MetaData`): la última conocida del buque.
    lat: Mapped[float | None] = mapped_column(Double)
    lon: Mapped[float | None] = mapped_column(Double)
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
