"""Registro, login, refresh y logout (AGENTS.md §8.4, docs/API_DESIGN.md "Auth").

Este servicio decide cuándo termina cada transacción: hace commit al final de cada operación que
escribe. Si algo falla antes, `get_db` hace rollback y no queda nada a medias.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import (
    InvalidTokenError,
    RefreshTokenClaims,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from app.models.user import User, UserRole
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository
from app.services.exceptions import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    access_token: str
    access_expires_in: int  # segundos
    refresh_token: str
    refresh_expires_at: datetime


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._users = UserRepository(session)
        self._refresh_tokens = RefreshTokenRepository(session)

    async def register(self, email: str, password: str) -> User:
        # El rol no llega del cliente: el registro siempre crea `user` (AGENTS.md §8.3).
        if await self._users.get_by_email(email) is not None:
            raise EmailAlreadyRegisteredError
        try:
            user = await self._users.add(
                email=email, hashed_password=hash_password(password), role=UserRole.USER
            )
            await self._session.commit()
        except IntegrityError:
            # Otra petición registró el mismo email entre la consulta y el INSERT.
            await self._session.rollback()
            raise EmailAlreadyRegisteredError from None
        logger.info("user_registered", user_id=str(user.id))
        return user

    async def login(self, email: str, password: str) -> IssuedTokens:
        user = await self._users.get_by_email(email)
        # Sin usuario se verifica contra el hash ficticio: mismo tiempo y mismo error.
        check = verify_password(password, user.hashed_password if user else None)
        if user is None or not check.valid:
            logger.info("login_failed")
            raise InvalidCredentialsError
        if check.new_hash is not None:
            await self._users.update_password_hash(user, check.new_hash)

        tokens, _ = await self._issue(user.id, family_id=uuid4(), now=datetime.now(UTC))
        await self._session.commit()
        logger.info("login_succeeded", user_id=str(user.id))
        return tokens

    async def refresh(self, refresh_token: str | None) -> IssuedTokens:
        """Rota el refresh: el usado queda revocado y apunta al nuevo (`replaced_by_jti`).

        Si llega uno ya revocado, alguien tiene una copia (robada o reenviada): se revoca toda la
        familia, así que ni el atacante ni el usuario legítimo pueden seguir con esa sesión.
        """
        claims = self._decode(refresh_token)
        now = datetime.now(UTC)
        stored = await self._refresh_tokens.get_for_update(claims.jti)
        if stored is None or stored.user_id != claims.user_id:
            raise InvalidRefreshTokenError
        if stored.revoked_at is not None:
            await self._refresh_tokens.revoke_family(stored.family_id, now)
            await self._session.commit()
            logger.warning(
                "refresh_token_reuse_detected",
                user_id=str(stored.user_id),
                family_id=str(stored.family_id),
            )
            raise InvalidRefreshTokenError
        if stored.expires_at <= now:
            raise InvalidRefreshTokenError

        tokens, new_jti = await self._issue(stored.user_id, family_id=stored.family_id, now=now)
        await self._refresh_tokens.mark_rotated(stored, new_jti, now)
        await self._session.commit()
        return tokens

    async def logout(self, user: User, refresh_token: str | None) -> None:
        """Revoca la sesión del refresh recibido. Sin refresh válido no hay nada que revocar."""
        try:
            claims = self._decode(refresh_token)
        except InvalidRefreshTokenError:
            return
        stored = await self._refresh_tokens.get_for_update(claims.jti)
        # Solo sesiones propias: un refresh de otro usuario se ignora sin revelar que existe.
        if stored is None or stored.user_id != user.id:
            return
        await self._refresh_tokens.revoke_family(stored.family_id, datetime.now(UTC))
        await self._session.commit()
        logger.info("logout", user_id=str(user.id))

    def _decode(self, refresh_token: str | None) -> RefreshTokenClaims:
        if not refresh_token:
            raise InvalidRefreshTokenError
        try:
            return decode_refresh_token(refresh_token, self._settings)
        except InvalidTokenError:
            raise InvalidRefreshTokenError from None

    async def _issue(
        self, user_id: UUID, *, family_id: UUID, now: datetime
    ) -> tuple[IssuedTokens, UUID]:
        """Emite access + refresh y guarda el `jti` del refresh. Devuelve también ese `jti`."""
        access_token, access = create_access_token(user_id, self._settings, now=now)
        refresh_token, refresh = create_refresh_token(user_id, family_id, self._settings, now=now)
        await self._refresh_tokens.add(
            jti=refresh.jti, family_id=family_id, user_id=user_id, expires_at=refresh.expires_at
        )
        tokens = IssuedTokens(
            access_token=access_token,
            access_expires_in=int((access.expires_at - now).total_seconds()),
            refresh_token=refresh_token,
            refresh_expires_at=refresh.expires_at,
        )
        return tokens, refresh.jti
