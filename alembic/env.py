"""Configuración async de Alembic usando exclusivamente el rol de migraciones."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.models import Base
from app.models.base import include_object

MISSING_URL_HELP = (
    "MIGRATIONS_DATABASE_URL no está definida. Alembic necesita la URL del rol canal_owner "
    "(ver .env.example); nunca usa DATABASE_URL, que es la del rol canal_app sin DDL."
)

config = context.config
# Los tests ejecutan Alembic dentro de su proceso: ahí no debe reconfigurar los logs de la app.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def migrations_url() -> str:
    url = get_settings().migrations_database_url
    if url is None:
        raise RuntimeError(MISSING_URL_HELP)
    return url.get_secret_value()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = migrations_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        hide_parameters=True,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    # Los tests pasan su propia conexión (a la base de test) en `config.attributes`.
    connection = config.attributes.get("connection")
    if connection is not None:
        run_migrations(connection)
        return

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    raise RuntimeError("Las migraciones offline no están soportadas")
run_migrations_online()
