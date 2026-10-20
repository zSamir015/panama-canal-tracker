"""Create vessels and positions hypertable.

Revision ID: 20261020_0002
Revises: 20261018_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geography

revision: str = "20261020_0002"
down_revision: str | None = "20261018_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vessels",
        sa.Column("mmsi", sa.Integer(), nullable=False),
        sa.Column("imo", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("ship_type", sa.SmallInteger(), nullable=True),
        sa.Column("length_m", sa.REAL(), nullable=True),
        sa.Column("beam_m", sa.REAL(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("mmsi BETWEEN 100000000 AND 999999999", name="ck_vessels_mmsi"),
        sa.CheckConstraint("imo IS NULL OR imo BETWEEN 1 AND 9999999", name="ck_vessels_imo"),
        sa.CheckConstraint("length_m IS NULL OR length_m > 0", name="ck_vessels_length_positive"),
        sa.CheckConstraint("beam_m IS NULL OR beam_m > 0", name="ck_vessels_beam_positive"),
        sa.CheckConstraint(
            "ship_type IS NULL OR ship_type BETWEEN 0 AND 99", name="ck_vessels_ship_type"
        ),
        sa.PrimaryKeyConstraint("mmsi"),
    )
    op.create_index("ix_vessels_last_seen_at", "vessels", ["last_seen_at"])

    op.create_table(
        "positions",
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vessel_mmsi", sa.Integer(), nullable=False),
        sa.Column(
            "geom",
            Geography(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("sog", sa.REAL(), nullable=True),
        sa.Column("cog", sa.REAL(), nullable=True),
        sa.Column("heading", sa.REAL(), nullable=True),
        sa.Column("nav_status", sa.SmallInteger(), nullable=True),
        sa.CheckConstraint("vessel_mmsi BETWEEN 100000000 AND 999999999", name="ck_positions_mmsi"),
        sa.CheckConstraint("sog IS NULL OR sog >= 0 AND sog < 102.3", name="ck_positions_sog"),
        sa.CheckConstraint("cog IS NULL OR cog >= 0 AND cog < 360", name="ck_positions_cog"),
        sa.CheckConstraint(
            "heading IS NULL OR heading >= 0 AND heading < 511", name="ck_positions_heading"
        ),
        sa.CheckConstraint(
            "nav_status IS NULL OR nav_status BETWEEN 0 AND 15",
            name="ck_positions_nav_status",
        ),
        sa.ForeignKeyConstraint(["vessel_mmsi"], ["vessels.mmsi"], name="fk_positions_vessel_mmsi"),
        sa.PrimaryKeyConstraint("received_at", "vessel_mmsi"),
    )
    op.execute(
        "SELECT create_hypertable('positions', by_range('received_at'), if_not_exists => TRUE)"
    )
    op.create_index("ix_positions_geom", "positions", ["geom"], postgresql_using="gist")
    op.create_index(
        "ix_positions_vessel_mmsi_received_at",
        "positions",
        ["vessel_mmsi", "received_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_positions_vessel_mmsi_received_at", table_name="positions")
    op.drop_index("ix_positions_geom", table_name="positions")
    op.drop_table("positions")
    op.drop_index("ix_vessels_last_seen_at", table_name="vessels")
    op.drop_table("vessels")
