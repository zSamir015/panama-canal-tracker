from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi import FastAPI
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.models import Base
from app.models.base import include_object

ROOT = Path(__file__).resolve().parent.parent.parent
INSUFFICIENT_PRIVILEGE = "42501"
CHECK_VIOLATION = "23514"
UNIQUE_VIOLATION = "23505"


def alembic(action: Callable[[Config, str], None], revision: str) -> Callable[[Connection], None]:
    def run(connection: Connection) -> None:
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["connection"] = connection
        config.attributes["configure_logger"] = False
        action(config, revision)

    return run


def sqlstate(error: Exception) -> str | None:
    return getattr(getattr(error, "orig", None), "sqlstate", None)


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


async def test_tests_never_touch_the_development_database(owner_engine: AsyncEngine) -> None:
    assert owner_engine.url.database is not None
    assert owner_engine.url.database.endswith("_test")


async def test_upgrade_creates_the_tables_owned_by_the_migration_role(
    migrated: AsyncEngine,
) -> None:
    async with migrated.connect() as connection:
        owners = dict(
            (
                await connection.execute(
                    text(
                        "SELECT tablename, tableowner FROM pg_tables WHERE schemaname = 'public' "
                        "AND tablename IN ('users', 'refresh_tokens', 'alembic_version')"
                    )
                )
            ).all()
        )

    assert owners == {
        "users": "canal_owner",
        "refresh_tokens": "canal_owner",
        "alembic_version": "canal_owner",
    }


async def test_migration_creates_no_extensions(migrated: AsyncEngine) -> None:
    # Las extensiones las instala el superusuario (docker/db/initdb); canal_owner no es dueño
    # de ninguna, así que no puede borrarlas.
    async with migrated.connect() as connection:
        owned = (
            await connection.execute(
                text(
                    "SELECT extname FROM pg_extension "
                    "WHERE pg_get_userbyid(extowner) = current_user"
                )
            )
        ).all()

    assert owned == []


async def test_models_match_the_migrated_schema(migrated: AsyncEngine) -> None:
    def diff(connection: Connection) -> list[Any]:
        context = MigrationContext.configure(
            connection,
            opts={
                "compare_type": True,
                "compare_server_default": True,
                "include_object": include_object,
            },
        )
        return compare_metadata(context, Base.metadata)

    async with migrated.connect() as connection:
        differences = await connection.run_sync(diff)

    assert differences == []


async def test_app_role_reads_and_writes_but_cannot_change_the_schema(
    migrated: AsyncEngine, db_app: FastAPI
) -> None:
    # Sin conceder nada en el test: los permisos vienen de los DEFAULT PRIVILEGES de la base.
    async with db_app.state.session_factory() as session:
        await session.execute(
            text("INSERT INTO users (email, hashed_password) VALUES (:email, :hash)"),
            {"email": "ana@example.com", "hash": "hash-falso"},
        )
        role = (
            await session.execute(
                text("SELECT role FROM users WHERE email = :email"), {"email": "ana@example.com"}
            )
        ).scalar_one()
        await session.commit()

        for ddl in (
            "ALTER TABLE users ADD COLUMN extra int",
            "DROP TABLE refresh_tokens",
            "CREATE TABLE intruder (id int)",
        ):
            with pytest.raises(ProgrammingError) as error:
                await session.execute(text(ddl))
            assert sqlstate(error.value) == INSUFFICIENT_PRIVILEGE, ddl
            await session.rollback()

    assert role == "user"


async def test_email_must_be_stored_in_lowercase(migrated: AsyncEngine) -> None:
    insert = text("INSERT INTO users (email, hashed_password) VALUES (:email, 'hash-falso')")

    async with migrated.connect() as connection:
        with pytest.raises(IntegrityError) as uppercase:
            await connection.execute(insert, {"email": "Ana@example.com"})
        await connection.rollback()

        await connection.execute(insert, {"email": "ana@example.com"})
        with pytest.raises(IntegrityError) as duplicate:
            await connection.execute(insert, {"email": "ana@example.com"})
        await connection.rollback()

    assert sqlstate(uppercase.value) == CHECK_VIOLATION
    assert sqlstate(duplicate.value) == UNIQUE_VIOLATION


async def test_refresh_token_defaults_use_the_insert_time(migrated: AsyncEngine) -> None:
    # Un default `'now()'` entre comillas se congela al crear la tabla; `now()` no.
    async with migrated.connect() as connection:
        default = (
            await connection.execute(
                text(
                    "SELECT column_default FROM information_schema.columns "
                    "WHERE table_name = 'refresh_tokens' AND column_name = 'created_at'"
                )
            )
        ).scalar_one()

    assert default == "now()"


async def test_downgrade_removes_everything_the_migration_created(
    owner_engine: AsyncEngine,
) -> None:
    async def tables() -> set[str]:
        async with owner_engine.connect() as connection:
            names = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
        return set(names) - {"alembic_version"}

    async with owner_engine.begin() as connection:
        await connection.run_sync(alembic(command.downgrade, "base"))
    before = await tables()

    async with owner_engine.begin() as connection:
        await connection.run_sync(alembic(command.upgrade, "head"))
        await connection.run_sync(alembic(command.downgrade, "base"))

    async with owner_engine.connect() as connection:
        user_role = (await connection.execute(text("SELECT to_regtype('user_role')"))).scalar_one()

    assert await tables() == before
    assert user_role is None
