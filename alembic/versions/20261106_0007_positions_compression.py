"""Compress old positions and add the positions_5min history aggregate.

Revision ID: 20261106_0007
Revises: 20261106_0006
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261106_0007"
down_revision: str | None = "20261106_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Compresión (ADR-0005): los chunks de más de 7 días se guardan en columnas, agrupados por
    # buque y ordenados por hora (lo que más se lee es la trayectoria de un buque). No se borra
    # nada: los datos siguen ahí, solo ocupan mucho menos, y se pueden leer e incluso escribir
    # (el `ON CONFLICT DO NOTHING` del writer sigue funcionando sobre un chunk comprimido).
    op.execute(
        """
        ALTER TABLE positions SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'vessel_mmsi',
            timescaledb.compress_orderby = 'received_at DESC'
        )
        """
    )
    # `initial_start`: la primera pasada llega dentro de una hora y no al crear la política. Al
    # desplegar, la compresión de todo lo viejo no arranca en mitad de la migración, y los tests
    # no se encuentran el chunk comprimido por un trabajo en segundo plano que no controlan.
    op.execute(
        """
        SELECT add_compression_policy(
            'positions', INTERVAL '7 days', initial_start => now() + INTERVAL '1 hour'
        )
        """
    )

    # Histórico reducido: la última posición de cada buque en cada tramo de 5 minutos. Para
    # consultar trayectorias de hace meses sin recorrer todas las posiciones. Solo materializado
    # (no en tiempo real): es histórico, y lo reciente se lee de `positions`.
    op.execute(
        """
        CREATE MATERIALIZED VIEW positions_5min
        WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
        SELECT
            time_bucket(INTERVAL '5 minutes', received_at) AS bucket,
            vessel_mmsi,
            count(*) AS positions,
            last(geom, received_at) AS geom,
            last(sog, received_at) AS sog,
            last(cog, received_at) AS cog,
            last(nav_status, received_at) AS nav_status
        FROM positions
        GROUP BY bucket, vessel_mmsi
        WITH NO DATA
        """
    )
    op.execute(
        """
        SELECT add_continuous_aggregate_policy(
            'positions_5min',
            start_offset => NULL,
            end_offset => INTERVAL '1 hour',
            schedule_interval => INTERVAL '1 hour',
            initial_start => now() + INTERVAL '1 hour'
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS positions_5min")
    op.execute("SELECT remove_compression_policy('positions', if_exists => true)")
    # No se puede desactivar la compresión con chunks comprimidos: primero se descomprimen.
    op.execute(
        "SELECT decompress_chunk(chunk, if_compressed => true) "
        "FROM show_chunks('positions') AS chunk"
    )
    op.execute("ALTER TABLE positions SET (timescaledb.compress = false)")
