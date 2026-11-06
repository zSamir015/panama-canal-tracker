"""Create the positions_hourly continuous aggregate.

Revision ID: 20261106_0006
Revises: 20261106_0005
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261106_0006"
down_revision: str | None = "20261106_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Una fila por buque y hora: cuántas posiciones llegaron y a qué velocidad. De ahí salen el
    # tráfico (buques distintos por día) y la cobertura de AISStream (mensajes por hora).
    #
    # `materialized_only = false`: las consultas suman a lo ya calculado las posiciones de la hora
    # en curso, que todavía no se han materializado. `WITH NO DATA` porque una migración corre en
    # una transacción y `CREATE ... WITH DATA` no puede; el primer refresco lo hace la política.
    op.execute(
        """
        CREATE MATERIALIZED VIEW positions_hourly
        WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
        SELECT
            time_bucket(INTERVAL '1 hour', received_at) AS bucket,
            vessel_mmsi,
            count(*) AS positions,
            avg(sog) AS avg_sog,
            max(sog) AS max_sog
        FROM positions
        GROUP BY bucket, vessel_mmsi
        WITH NO DATA
        """
    )
    # `start_offset => NULL`: el primer refresco materializa todo el histórico; los siguientes solo
    # recalculan las horas con datos nuevos (TimescaleDB lleva un registro de lo invalidado).
    op.execute(
        """
        SELECT add_continuous_aggregate_policy(
            'positions_hourly',
            start_offset => NULL,
            end_offset => INTERVAL '1 hour',
            schedule_interval => INTERVAL '30 minutes'
        )
        """
    )


def downgrade() -> None:
    # Borrar la vista borra también su política y su hypertable de materialización.
    op.execute("DROP MATERIALIZED VIEW IF EXISTS positions_hourly")
