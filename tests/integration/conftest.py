"""Fixtures de los tests de integración: usan la base REAL con el rol `canal_app`.

Si la base no está levantada fallan con un mensaje claro; nunca se saltan en silencio
(un test saltado parece verde y oculta que no se probó nada).
"""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.main import create_app

NO_DATABASE_HELP = (
    "No se pudo conectar a la base de datos de desarrollo ({error}).\n"
    "Levántala con: colima start && docker compose up -d --wait\n"
    "y comprueba DATABASE_URL en .env (rol canal_app). "
    "Para ejecutar solo los tests unitarios: pytest -m 'not integration'"
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)


@pytest.fixture
def db_settings() -> Settings:
    return Settings(app_env="test", cors_origins=["https://tracker.example.com"])


@pytest.fixture
async def db_app(db_settings: Settings) -> AsyncIterator[FastAPI]:
    app = create_app(db_settings)
    engine: AsyncEngine = app.state.engine
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as error:
        await engine.dispose()
        pytest.fail(NO_DATABASE_HELP.format(error=type(error).__name__), pytrace=False)
    yield app
    await engine.dispose()
