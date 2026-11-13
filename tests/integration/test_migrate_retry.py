"""El reintento de `migrate()` ante la carrera con el planificador de TimescaleDB (issue #141).

No necesita base de datos: la conexión es un doble que falla las veces que se le pida.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, cast

import pytest
from alembic import command
from sqlalchemy.exc import InternalError
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.conftest import MIGRATION_RETRIES, migrate


class FlakyConnection:
    """Lanza los errores de `errors` en orden, uno por intento, y después funciona."""

    def __init__(self, errors: list[Exception]) -> None:
        self.errors = errors
        self.attempts = 0

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield

    async def run_sync(self, function: Callable[..., Any]) -> None:
        self.attempts += 1
        if self.errors:
            raise self.errors.pop(0)


def db_error(message: str) -> InternalError:
    return InternalError(
        "DROP MATERIALIZED VIEW IF EXISTS positions_hourly", {}, Exception(message)
    )


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    async def instant(_seconds: float) -> None:
        return None

    # Sin las esperas entre reintentos: el test no necesita el tiempo real.
    monkeypatch.setattr(asyncio, "sleep", instant)


async def run(connection: FlakyConnection) -> None:
    await migrate(cast(AsyncConnection, connection), command.downgrade, "base")


@pytest.mark.parametrize("message", ["tuple concurrently deleted", "tuple concurrently updated"])
async def test_retries_the_scheduler_race(message: str) -> None:
    connection = FlakyConnection([db_error(message), db_error(message)])

    await run(connection)

    assert connection.attempts == 3


async def test_any_other_error_is_raised_at_once() -> None:
    connection = FlakyConnection([db_error("deadlock detected")])

    with pytest.raises(InternalError, match="deadlock detected"):
        await run(connection)
    assert connection.attempts == 1


async def test_gives_up_after_the_last_retry() -> None:
    errors: list[Exception] = [
        db_error("tuple concurrently updated") for _ in range(MIGRATION_RETRIES)
    ]
    connection = FlakyConnection(errors)

    with pytest.raises(InternalError, match="tuple concurrently updated"):
        await run(connection)
    assert connection.attempts == MIGRATION_RETRIES
