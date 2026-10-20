"""Acceso a la tabla `users`."""

from uuid import UUID

from sqlalchemy import select

from app.models.user import User, UserRole
from app.repositories.base import BaseRepository


def normalize_email(email: str) -> str:
    """La base exige el email en minúsculas (`ck_users_email_lowercase`).

    Se normaliza al guardar y al buscar, para que `Ana@x.com` y `ana@x.com` sean la misma cuenta.
    """
    return email.lower()


class UserRepository(BaseRepository):
    async def get_by_id(self, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.email == normalize_email(email))
        )
        return result.scalar_one_or_none()

    async def add(self, *, email: str, hashed_password: str, role: UserRole) -> User:
        """Inserta el usuario y lo devuelve con su id. No hace commit: lo decide quien llama."""
        user = User(email=normalize_email(email), hashed_password=hashed_password, role=role)
        self._session.add(user)
        await self._session.flush()
        return user

    async def update_password_hash(self, user: User, hashed_password: str) -> None:
        """Guarda un hash recalculado (rehash tras cambiar los parámetros de Argon2)."""
        user.hashed_password = hashed_password
        await self._session.flush()
