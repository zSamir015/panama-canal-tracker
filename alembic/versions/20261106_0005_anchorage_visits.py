"""Create anchorage_visits.

Revision ID: 20261106_0005
Revises: 20261106_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261106_0005"
down_revision: str | None = "20261106_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ANCHORAGES = ("atlantic", "pacific")


def upgrade() -> None:
    postgresql.ENUM(*ANCHORAGES, name="anchorage_name").create(op.get_bind(), checkfirst=True)
    anchorage = postgresql.ENUM(*ANCHORAGES, name="anchorage_name", create_type=False)

    op.create_table(
        "anchorage_visits",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("vessel_mmsi", sa.Integer(), nullable=False),
        sa.Column("anchorage", anchorage, nullable=False),
        sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("departed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("vessel_mmsi BETWEEN 100000000 AND 999999999", name="ck_visits_mmsi"),
        sa.CheckConstraint(
            "departed_at IS NULL OR departed_at > arrived_at", name="ck_visits_order"
        ),
        sa.ForeignKeyConstraint(["vessel_mmsi"], ["vessels.mmsi"], name="fk_visits_vessel_mmsi"),
        sa.ForeignKeyConstraint(
            ["transit_id"], ["transits.id"], name="fk_visits_transit_id", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_visits_one_open_per_vessel",
        "anchorage_visits",
        ["vessel_mmsi"],
        unique=True,
        postgresql_where=sa.text("departed_at IS NULL"),
    )
    op.create_index("ix_visits_arrived_at", "anchorage_visits", ["arrived_at"])
    op.create_index(
        "ix_visits_vessel_mmsi_arrived_at", "anchorage_visits", ["vessel_mmsi", "arrived_at"]
    )
    op.create_index("ix_visits_transit_id", "anchorage_visits", ["transit_id"])


def downgrade() -> None:
    op.drop_index("ix_visits_transit_id", table_name="anchorage_visits")
    op.drop_index("ix_visits_vessel_mmsi_arrived_at", table_name="anchorage_visits")
    op.drop_index("ix_visits_arrived_at", table_name="anchorage_visits")
    op.drop_index("uq_visits_one_open_per_vessel", table_name="anchorage_visits")
    op.drop_table("anchorage_visits")
    postgresql.ENUM(*ANCHORAGES, name="anchorage_name").drop(op.get_bind())
