"""Fixtures de los tests de integración: usan PostgreSQL REAL, en la base `<base>_test`.

Nunca tocan la base en la que trabajas: los tests de migraciones crean y borran el esquema
completo. La base de test la crea `docker/db/initdb/110_canal_test_database.sh` (o
`scripts/create_test_database.sh` en un volumen que ya existía).

Si la base no está levantada fallan con un mensaje claro; nunca se saltan en silencio
(un test saltado parece verde y oculta que no se probó nada).
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from urllib.parse import urlsplit, urlunsplit

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from limits.aio.storage import RedisStorage
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import InternalError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.core.config import Settings
from app.core.rate_limit import create_storage
from app.main import create_app
from tests.conftest import TEST_JWT_KEY
from tests.integration.alembic_helpers import alembic

TEST_DATABASE_SUFFIX = "_test"

NO_DATABASE_HELP = (
    "No se pudo conectar a la base de test {database!r} como {role} ({error}).\n"
    "Levántala con: colima start && docker compose up -d --wait && "
    "scripts/create_test_database.sh\n"
    "y comprueba DATABASE_URL y MIGRATIONS_DATABASE_URL en .env. "
    "Para ejecutar solo los tests unitarios: pytest -m 'not integration'"
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)


def to_test_database(url: SecretStr) -> SecretStr:
    """La misma URL (rol y contraseña) apuntando a `<base>_test`."""
    parsed = make_url(url.get_secret_value())
    database = parsed.database or ""
    if not database.endswith(TEST_DATABASE_SUFFIX):
        database += TEST_DATABASE_SUFFIX
    return SecretStr(parsed.set(database=database).render_as_string(hide_password=False))


async def require_connection(engine: AsyncEngine, role: str) -> None:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as error:
        await engine.dispose()
        pytest.fail(
            NO_DATABASE_HELP.format(
                database=engine.url.database, role=role, error=type(error).__name__
            ),
            pytrace=False,
        )


@pytest.fixture
def db_settings() -> Settings:
    settings = Settings(app_env="test", cors_origins=["https://tracker.example.com"])
    if settings.migrations_database_url is None:
        pytest.fail("Define MIGRATIONS_DATABASE_URL en .env (rol canal_owner)", pytrace=False)
    return settings.model_copy(
        update={
            "database_url": to_test_database(settings.database_url),
            "migrations_database_url": to_test_database(settings.migrations_database_url),
            # La clave de `.env` puede ser el placeholder; los tests firman con la suya.
            "jwt_secret_key": SecretStr(TEST_JWT_KEY),
        }
    )


@pytest.fixture
async def db_app(db_settings: Settings) -> AsyncIterator[FastAPI]:
    app = create_app(db_settings)
    engine: AsyncEngine = app.state.engine
    await require_connection(engine, "canal_app")
    yield app
    await engine.dispose()


@pytest.fixture
async def owner_engine(db_settings: Settings) -> AsyncIterator[AsyncEngine]:
    """Engine con el rol de migraciones (`canal_owner`) sobre la base de test."""
    assert db_settings.migrations_database_url is not None
    engine = create_async_engine(
        db_settings.migrations_database_url.get_secret_value(), hide_parameters=True
    )
    await require_connection(engine, "canal_owner")
    yield engine
    await engine.dispose()


TEST_MIGRATION_LOCK = "panama_canal_tracker_test_migrations"
MIGRATION_RETRIES = 5


@pytest.fixture
async def migration_lock(owner_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """Serializa cualquier prueba que pueda cambiar el esquema de la base compartida."""
    connection = await owner_engine.connect()
    try:
        await connection.execute(
            text("SELECT pg_advisory_lock(hashtextextended(:lock_name, 0))"),
            {"lock_name": TEST_MIGRATION_LOCK},
        )
        await connection.commit()
        yield connection
    finally:
        await connection.execute(
            text("SELECT pg_advisory_unlock(hashtextextended(:lock_name, 0))"),
            {"lock_name": TEST_MIGRATION_LOCK},
        )
        await connection.commit()
        await connection.close()


async def migrate(
    connection: AsyncConnection, action: Callable[[Config, str], None], revision: str
) -> None:
    """Ejecuta un comando de Alembic en una transacción, reintentándola si TimescaleDB choca.

    Al crear una política (refresco de un agregado, compresión), el planificador de TimescaleDB
    escribe de inmediato en su catálogo de trabajos. Si el siguiente DDL borra esa política a los
    pocos milisegundos (los tests suben y bajan el esquema sin pausa), PostgreSQL responde
    "tuple concurrently deleted". Es una carrera del test con el planificador, no un fallo de la
    migración: la transacción se deshace entera y reintentarla la resuelve. Cualquier otro error
    se propaga sin reintentar.
    """
    for attempt in range(MIGRATION_RETRIES):
        try:
            async with connection.begin():
                await connection.run_sync(alembic(action, revision))
        except InternalError as error:
            if "tuple concurrently deleted" not in str(error) or attempt + 1 == MIGRATION_RETRIES:
                raise
            await asyncio.sleep(0.2 * (attempt + 1))
        else:
            return


@pytest.fixture
async def migrated(
    owner_engine: AsyncEngine, migration_lock: AsyncConnection
) -> AsyncIterator[AsyncEngine]:
    """Esquema migrado a `head` aislado frente a otras ejecuciones.

    La base de test es compartida por todos los procesos de pytest. El advisory lock mantiene
    el esquema en `head` durante toda la prueba y evita que otra ejecución lo baje mientras la
    primera todavía usa sus tablas.
    """
    await migrate(migration_lock, command.downgrade, "base")
    await migrate(migration_lock, command.upgrade, "head")
    yield owner_engine
    await migrate(migration_lock, command.downgrade, "base")


# Redis real: la base 15, nunca la 0 de desarrollo. Se vacía antes y después de cada test.
TEST_REDIS_DB = 15
NO_REDIS_HELP = (
    "No se pudo conectar a Redis con REDIS_URL. Levántalo con: docker compose up -d --wait. "
    "Para ejecutar solo los tests unitarios: pytest -m 'not integration'"
)


def with_test_db(url: SecretStr) -> SecretStr:
    parts = urlsplit(url.get_secret_value())
    return SecretStr(urlunsplit(parts._replace(path=f"/{TEST_REDIS_DB}")))


@pytest.fixture
def redis_url() -> SecretStr:
    return with_test_db(Settings(app_env="test").redis_url)


@pytest.fixture
async def redis_storage(redis_url: SecretStr) -> AsyncIterator[RedisStorage]:
    settings = Settings(app_env="test", redis_url=redis_url)
    redis = create_storage(settings)
    if not await redis.check():
        pytest.fail(NO_REDIS_HELP, pytrace=False)
    await redis.reset()
    yield redis
    await redis.reset()
