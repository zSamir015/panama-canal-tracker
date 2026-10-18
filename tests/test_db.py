import ast
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.db import DbSession, create_engine, get_db
from app.main import create_app

APP_DIR = Path(__file__).resolve().parent.parent / "app"
FAKE_URL = "postgresql+asyncpg://canal_app:pw-falsa-de-prueba@localhost:1/canal_tracker"


class SpySession(AsyncSession):
    """Sesión que cuenta cuántas veces se hizo rollback y si se cerró."""

    rollbacks = 0
    closed = False

    async def rollback(self) -> None:
        type(self).rollbacks += 1
        await super().rollback()

    async def close(self) -> None:
        type(self).closed = True
        await super().close()


@pytest.fixture
def spy_app(app_settings: Settings) -> FastAPI:
    SpySession.rollbacks = 0
    SpySession.closed = False
    app = create_app(app_settings)
    app.state.session_factory = async_sessionmaker(
        app.state.engine, class_=SpySession, expire_on_commit=False
    )
    return app


def test_importing_the_module_creates_no_engine() -> None:
    # `create_app()` es quien crea el engine; la configuración llega por parámetro.
    settings = Settings(_env_file=None, database_url=FAKE_URL)  # type: ignore[arg-type]

    engine = create_engine(settings)

    assert isinstance(engine, AsyncEngine)
    assert engine.dialect.driver == "asyncpg"
    assert engine.pool.checkedout() == 0  # no abrió conexiones


def test_engine_hides_parameters_and_does_not_echo() -> None:
    settings = Settings(_env_file=None, database_url=FAKE_URL)  # type: ignore[arg-type]

    engine = create_engine(settings)

    assert engine.sync_engine.hide_parameters is True
    assert engine.echo is False


def test_engine_repr_does_not_expose_the_password() -> None:
    settings = Settings(_env_file=None, database_url=FAKE_URL)  # type: ignore[arg-type]

    assert "pw-falsa-de-prueba" not in repr(create_engine(settings))


def test_create_app_builds_engine_and_session_factory(app: FastAPI) -> None:
    assert isinstance(app.state.engine, AsyncEngine)
    assert isinstance(app.state.session_factory, async_sessionmaker)


async def test_lifespan_disposes_the_engine_on_shutdown(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    disposed: list[bool] = []
    original = AsyncEngine.dispose

    async def spy_dispose(self: AsyncEngine, *args: Any, **kwargs: Any) -> None:
        disposed.append(True)
        await original(self, *args, **kwargs)

    monkeypatch.setattr(AsyncEngine, "dispose", spy_dispose)

    async with app.router.lifespan_context(app):
        assert disposed == []

    assert disposed == [True]


async def test_get_db_opens_a_session_and_closes_it(spy_app: FastAPI) -> None:
    @spy_app.get("/probe")
    async def probe(session: DbSession) -> dict[str, bool]:
        assert isinstance(session, SpySession)
        return {"in_transaction": session.in_transaction()}

    async with AsyncClient(transport=ASGITransport(app=spy_app), base_url="http://t") as client:
        response = await client.get("/probe")

    assert response.status_code == 200
    assert SpySession.closed is True
    assert SpySession.rollbacks == 0


async def test_get_db_rolls_back_and_closes_when_the_request_fails(spy_app: FastAPI) -> None:
    seen: list[AsyncSession] = []

    async def failing(session: AsyncSession = Depends(get_db)) -> None:  # noqa: B008
        seen.append(session)
        raise RuntimeError("fallo a propósito")

    spy_app.add_api_route("/boom", failing)

    async with AsyncClient(
        transport=ASGITransport(app=spy_app, raise_app_exceptions=False), base_url="http://t"
    ) as client:
        response = await client.get("/boom")

    assert response.status_code == 500
    assert SpySession.rollbacks == 1
    assert SpySession.closed is True


async def test_get_db_gives_each_request_its_own_session(spy_app: FastAPI) -> None:
    ids: list[int] = []

    @spy_app.get("/id")
    async def session_id(session: DbSession) -> None:
        ids.append(id(session))

    async with AsyncClient(transport=ASGITransport(app=spy_app), base_url="http://t") as client:
        await client.get("/id")
        await client.get("/id")

    assert len(ids) == 2


async def test_get_db_closes_the_session_when_the_generator_is_closed(app: FastAPI) -> None:
    class Request:
        pass

    request = Request()
    request.app = app  # type: ignore[attr-defined]
    generator: AsyncIterator[AsyncSession] = get_db(request)  # type: ignore[arg-type]

    session = await anext(generator)
    await generator.aclose()  # type: ignore[attr-defined]

    assert not session.in_transaction()


def _python_files(folder: Path) -> list[Path]:
    return sorted(folder.rglob("*.py"))


def test_routers_never_touch_the_orm() -> None:
    forbidden = ("sqlalchemy", "asyncpg", "app.models", "app.repositories")
    offenders: list[str] = []
    for path in _python_files(APP_DIR / "routers"):
        for node in ast.walk(ast.parse(path.read_text())):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            offenders += [f"{path.name}: {n}" for n in names if n.startswith(forbidden)]

    assert offenders == []


def _is_dynamic_string(node: ast.expr) -> bool:
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        return True
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
    )


def test_no_sql_is_built_with_string_interpolation() -> None:
    offenders: list[str] = []
    for path in _python_files(APP_DIR):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name in ("text", "execute", "exec_driver_sql") and node.args:
                if _is_dynamic_string(node.args[0]):
                    offenders.append(f"{path.name}:{node.lineno}")

    assert offenders == []


def test_the_sql_scanner_detects_an_interpolated_query() -> None:
    tree = ast.parse('text(f"SELECT * FROM users WHERE id = {user_id}")')
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))

    assert _is_dynamic_string(call.args[0])
