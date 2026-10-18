from pathlib import Path

from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.core.config import Settings

ROOT = Path(__file__).resolve().parent.parent.parent


async def test_upgrade_and_downgrade_schema_with_migration_role(db_app: FastAPI) -> None:
    settings = Settings()
    engine = create_async_engine(
        settings.migrations_database_url.get_secret_value(),
        hide_parameters=True,
    )
    config = Config(str(ROOT / "alembic.ini"))

    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "ALTER DEFAULT PRIVILEGES FOR ROLE canal_owner IN SCHEMA public "
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO canal_app"
                )
            )
            await connection.run_sync(lambda sync_connection: _run_upgrade(config, sync_connection))

        async with db_app.state.session_factory() as session:
            tables = (
                (
                    await session.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = 'public'"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert {"users", "refresh_tokens", "alembic_version"} <= set(tables)
            assert (await session.execute(text("SELECT current_user"))).scalar_one() == "canal_app"

        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: _run_downgrade(config, sync_connection)
            )
    finally:
        await engine.dispose()


def _run_upgrade(config: Config, connection: Connection) -> None:
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


def _run_downgrade(config: Config, connection: Connection) -> None:
    config.attributes["connection"] = connection
    command.downgrade(config, "base")
