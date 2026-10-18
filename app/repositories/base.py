"""Base del patrón repository (AGENTS.md §3).

Los repositorios son la única capa que habla con el ORM. Los routers y los servicios reciben
objetos de dominio, nunca una sesión ni sentencias SQL.

Regla de oro: consultas solo con el constructor de SQLAlchemy y parámetros enlazados. Prohibido
construir SQL con f-strings o concatenación, también dentro de `text()` (AGENTS.md §8.6).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ping(self) -> bool:
        """Comprueba que la base responde. Útil para `/ready` y para los tests de conexión."""
        result = await self._session.execute(select(1))
        return bool(result.scalar_one() == 1)
