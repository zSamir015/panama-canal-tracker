"""Create canal_bound_vessels.

Revision ID: 20261022_0003
Revises: 20261020_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261022_0003"
down_revision: str | None = "20261020_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "canal_bound_vessels",
        sa.Column("mmsi", sa.Integer(), nullable=False),
        sa.Column("imo", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("ship_type", sa.SmallInteger(), nullable=True),
        sa.Column("length_m", sa.REAL(), nullable=True),
        sa.Column("destination", sa.String(length=64), nullable=False),
        sa.Column("port_locode", sa.String(length=5), nullable=False),
        sa.Column("eta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lat", sa.Double(), nullable=True),
        sa.Column("lon", sa.Double(), nullable=True),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("mmsi BETWEEN 100000000 AND 999999999", name="ck_canal_bound_mmsi"),
        sa.CheckConstraint("imo IS NULL OR imo BETWEEN 1 AND 9999999", name="ck_canal_bound_imo"),
        sa.CheckConstraint(
            "ship_type IS NULL OR ship_type BETWEEN 0 AND 99", name="ck_canal_bound_ship_type"
        ),
        sa.CheckConstraint(
            "length_m IS NULL OR length_m > 0", name="ck_canal_bound_length_positive"
        ),
        sa.CheckConstraint(
            "port_locode = 'PA' OR port_locode ~ '^PA[A-Z]{3}$'", name="ck_canal_bound_port"
        ),
        sa.CheckConstraint(
            "(lat IS NULL) = (lon IS NULL)"
            " AND (lat IS NULL OR lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180)",
            name="ck_canal_bound_position",
        ),
        sa.PrimaryKeyConstraint("mmsi"),
    )
    op.create_index("ix_canal_bound_vessels_reported_at", "canal_bound_vessels", ["reported_at"])


def downgrade() -> None:
    op.drop_index("ix_canal_bound_vessels_reported_at", table_name="canal_bound_vessels")
    op.drop_table("canal_bound_vessels")
