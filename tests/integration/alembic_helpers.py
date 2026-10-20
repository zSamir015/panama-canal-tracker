"""Ejecuta comandos de Alembic sobre una conexión ya abierta (la del rol `canal_owner`)."""

from collections.abc import Callable
from pathlib import Path

from alembic.config import Config
from sqlalchemy.engine import Connection

ROOT = Path(__file__).resolve().parent.parent.parent


def alembic(action: Callable[[Config, str], None], revision: str) -> Callable[[Connection], None]:
    def run(connection: Connection) -> None:
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["connection"] = connection
        config.attributes["configure_logger"] = False
        action(config, revision)

    return run
