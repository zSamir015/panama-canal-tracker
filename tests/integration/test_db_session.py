import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import DbSession
from app.repositories.base import BaseRepository

PROBE = "app.probe"


def client_for(app: FastAPI) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t"
    )


def pool_checked_out(app: FastAPI) -> int:
    engine: AsyncEngine = app.state.engine
    return engine.pool.checkedout()  # type: ignore[attr-defined,no-any-return]


async def test_connects_with_the_least_privileged_role(db_app: FastAPI) -> None:
    async with db_app.state.session_factory() as session:
        role = (await session.execute(text("SELECT current_user"))).scalar_one()
        assert await BaseRepository(session).ping() is True

    assert role == "canal_app"


async def test_app_role_cannot_run_ddl(db_app: FastAPI) -> None:
    # Mínimo privilegio (AGENTS.md §8.16): crear tablas es trabajo de `canal_owner`.
    async with db_app.state.session_factory() as session:
        with pytest.raises(ProgrammingError, match="permission denied"):
            await session.execute(text("CREATE TABLE should_not_exist (id int)"))


async def test_request_gets_a_working_session_and_returns_the_connection(db_app: FastAPI) -> None:
    @db_app.get("/probe")
    async def probe(session: DbSession) -> dict[str, bool]:
        return {"ok": await BaseRepository(session).ping()}

    async with client_for(db_app) as client:
        response = await client.get("/probe")

    assert response.json() == {"ok": True}
    assert pool_checked_out(db_app) == 0


async def test_failed_request_rolls_back_and_releases_the_connection(db_app: FastAPI) -> None:
    @db_app.get("/write-then-fail")
    async def write_then_fail(session: DbSession) -> None:
        # `set_config(..., false)` se comporta como un SET de sesión: Postgres lo deshace si la
        # transacción termina en rollback, así que sirve de "escritura" sin permisos de DDL.
        await session.execute(text("SELECT set_config(:name, 'sucio', false)"), {"name": PROBE})
        raise RuntimeError("fallo a propósito")

    @db_app.get("/read")
    async def read(session: DbSession) -> dict[str, str | None]:
        value = (
            await session.execute(text("SELECT current_setting(:name, true)"), {"name": PROBE})
        ).scalar_one()
        return {"value": value or None}

    async with client_for(db_app) as client:
        failed = await client.get("/write-then-fail")
        after = await client.get("/read")

    assert failed.status_code == 500
    assert after.json() == {"value": None}
    assert pool_checked_out(db_app) == 0


async def test_committed_write_survives_the_request_control(db_app: FastAPI) -> None:
    # Control del test anterior: si la "escritura" se confirma, la ve el siguiente request.
    # Así sabemos que la prueba de rollback detecta algo real.
    @db_app.get("/write-and-commit")
    async def write_and_commit(session: DbSession) -> None:
        await session.execute(text("SELECT set_config(:name, 'limpio', false)"), {"name": PROBE})
        await session.commit()

    @db_app.get("/read")
    async def read(session: DbSession) -> dict[str, str | None]:
        value = (
            await session.execute(text("SELECT current_setting(:name, true)"), {"name": PROBE})
        ).scalar_one()
        return {"value": value or None}

    async with client_for(db_app) as client:
        await client.get("/write-and-commit")
        after = await client.get("/read")

    assert after.json() == {"value": "limpio"}


async def test_database_error_leaves_the_pool_usable(db_app: FastAPI) -> None:
    @db_app.get("/bad-sql")
    async def bad_sql(session: DbSession) -> None:
        await session.execute(text("SELECT * FROM table_that_does_not_exist"))

    @db_app.get("/ok")
    async def ok(session: DbSession) -> dict[str, bool]:
        return {"ok": await BaseRepository(session).ping()}

    async with client_for(db_app) as client:
        failed = await client.get("/bad-sql")
        recovered = await client.get("/ok")

    assert failed.status_code == 500
    assert recovered.json() == {"ok": True}
    assert pool_checked_out(db_app) == 0


async def test_parameters_are_bound_not_interpolated(db_app: FastAPI) -> None:
    hostile = "x'; DROP TABLE users; --"

    async with db_app.state.session_factory() as session:
        echoed = (await session.execute(text("SELECT :value"), {"value": hostile})).scalar_one()

    assert echoed == hostile


async def test_db_error_does_not_leak_parameter_values(db_app: FastAPI) -> None:
    user_data = "dato-de-usuario"

    async with db_app.state.session_factory() as session:
        with pytest.raises(DBAPIError) as error:
            await session.execute(
                text("SELECT * FROM missing_table WHERE name = :name"), {"name": user_data}
            )

    assert user_data not in str(error.value)
