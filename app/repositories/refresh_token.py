"""Acceso a la tabla `refresh_tokens`."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update

from app.models.refresh_token import RefreshToken
from app.repositories.base import BaseRepository


class RefreshTokenRepository(BaseRepository):
    async def add(
        self, *, jti: UUID, family_id: UUID, user_id: UUID, expires_at: datetime
    ) -> RefreshToken:
        token = RefreshToken(jti=jti, family_id=family_id, user_id=user_id, expires_at=expires_at)
        self._session.add(token)
        await self._session.flush()
        return token

    async def get_for_update(self, jti: UUID) -> RefreshToken | None:
        """Bloquea la fila hasta el commit: dos refresh simultáneos con el mismo token no pueden
        rotarlo los dos; el segundo espera y lo ve ya rotado (reutilización)."""
        result = await self._session.execute(
            select(RefreshToken).where(RefreshToken.jti == jti).with_for_update()
        )
        return result.scalar_one_or_none()

    async def revoke_family(self, family_id: UUID, now: datetime) -> None:
        """Revoca todos los tokens aún vivos de la familia (la sesión completa)."""
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    async def mark_rotated(self, token: RefreshToken, replaced_by: UUID, now: datetime) -> None:
        token.revoked_at = now
        token.replaced_by_jti = replaced_by
        await self._session.flush()
