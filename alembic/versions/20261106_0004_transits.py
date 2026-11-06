"""Create transits.

Revision ID: 20261106_0004
Revises: 20261022_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261106_0004"
down_revision: str | None = "20261022_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUMS = {
    "transit_direction": ("northbound", "southbound"),
    "transit_status": ("in_progress", "completed", "aborted"),
    "transit_abort_reason": ("timeout", "reversal"),
}


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)
    direction, status, abort_reason = (
        postgresql.ENUM(*values, name=name, create_type=False) for name, values in ENUMS.items()
    )

    op.create_table(
        "transits",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("vessel_mmsi", sa.Integer(), nullable=False),
        sa.Column("direction", direction, nullable=False),
        sa.Column("status", status, nullable=False),
        sa.Column("abort_reason", abort_reason, nullable=True),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "duration_minutes",
            sa.Integer(),
            sa.Computed(
                "CASE WHEN status = 'completed' "
                "THEN (EXTRACT(EPOCH FROM exited_at - entered_at) / 60)::integer END",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("vessel_mmsi BETWEEN 100000000 AND 999999999", name="ck_transits_mmsi"),
        sa.CheckConstraint(
            "(status = 'in_progress') = (exited_at IS NULL)", name="ck_transits_exited_at"
        ),
        sa.CheckConstraint("exited_at IS NULL OR exited_at > entered_at", name="ck_transits_order"),
        sa.CheckConstraint(
            "(status = 'aborted') = (abort_reason IS NOT NULL)", name="ck_transits_abort_reason"
        ),
        sa.ForeignKeyConstraint(["vessel_mmsi"], ["vessels.mmsi"], name="fk_transits_vessel_mmsi"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_transits_one_in_progress_per_vessel",
        "transits",
        ["vessel_mmsi"],
        unique=True,
        postgresql_where=sa.text("status = 'in_progress'"),
    )
    op.create_index("ix_transits_entered_at", "transits", ["entered_at"])
    op.create_index("ix_transits_vessel_mmsi_entered_at", "transits", ["vessel_mmsi", "entered_at"])


def downgrade() -> None:
    op.drop_index("ix_transits_vessel_mmsi_entered_at", table_name="transits")
    op.drop_index("ix_transits_entered_at", table_name="transits")
    op.drop_index("uq_transits_one_in_progress_per_vessel", table_name="transits")
    op.drop_table("transits")
    bind = op.get_bind()
    for name, values in reversed(ENUMS.items()):
        postgresql.ENUM(*values, name=name).drop(bind)
