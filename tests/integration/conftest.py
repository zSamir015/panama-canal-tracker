"""Fixtures de los tests de integración: usan PostgreSQL REAL, en la base `<base>_test`.

Nunca tocan la base en la que trabajas: los tests de migraciones crean y borran el esquema
completo. La base de test la crea `docker/db/initdb/110_canal_test_database.sh` (o
`scripts/create_test_database.sh` en un volumen que ya existía).

Si la base no está levantada fallan con un mensaje claro; nunca se saltan en silencio
(un test saltado parece verde y oculta que no se probó nada).
"""

from collections.abc import AsyncIterator
from urllib.parse import urlsplit, urlunsplit

import pytest
from alembic import command
from fastapi import FastAPI
from limits.aio.storage import RedisStorage
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

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


@pytest.fixture
async def migrated(owner_engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    """Esquema migrado a `head` en la base de test; al terminar vuelve a `base`.

    Empieza bajando a `base` por si una ejecución anterior se cortó a la mitad.
    """
    async with owner_engine.begin() as connection:
        await connection.run_sync(alembic(command.downgrade, "base"))
        await connection.run_sync(alembic(command.upgrade, "head"))
    yield owner_engine
    async with owner_engine.begin() as connection:
        await connection.run_sync(alembic(command.downgrade, "base"))


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
