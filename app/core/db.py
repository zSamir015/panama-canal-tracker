"""Conexión a PostgreSQL: engine, fábrica de sesiones y la dependencia `get_db`.

Nada se crea al importar el módulo: `create_app()` construye el engine con la configuración que
recibe y el `lifespan` lo cierra al apagar. Así los tests pueden crear varias apps con
configuraciones distintas sin compartir estado.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings

DB_CONNECT_TIMEOUT_SECONDS = 10

SessionFactory = async_sessionmaker[AsyncSession]


def create_engine(settings: Settings) -> AsyncEngine:
    """Crea el engine de la app. No abre ninguna conexión hasta la primera consulta."""
    return create_async_engine(
        settings.database_url.get_secret_value(),
        # Descarta conexiones muertas (reinicio de la base, corte de red) antes de entregarlas.
        pool_pre_ping=True,
        # Los parámetros de una consulta pueden ser datos de usuarios: no van en los errores.
        hide_parameters=True,
        # `echo` registraría cada SQL con sus valores.
        echo=False,
        connect_args={"timeout": DB_CONNECT_TIMEOUT_SECONDS},
    )


def create_session_factory(engine: AsyncEngine) -> SessionFactory:
    return async_sessionmaker(
        engine,
        # Tras un commit los objetos siguen usables sin una consulta implícita (imposible en async).
        expire_on_commit=False,
        autoflush=False,
    )


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Una sesión por request, cerrada siempre.

    No hace commit: la capa de servicios decide cuándo termina la transacción. Si algo falla
    antes de que se confirme, el rollback descarta todo lo escrito.
    """
    session_factory: SessionFactory = request.app.state.session_factory
    async with session_factory() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise


DbSession = Annotated[AsyncSession, Depends(get_db)]
