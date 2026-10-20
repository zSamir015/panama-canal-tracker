"""Dependencias de autenticación y autorización (AGENTS.md §8.3, §8.4 y §8.9).

- `get_current_user`: exige `Authorization: Bearer <access_token>` válido y un usuario que exista.
- `require_admin`: además exige el rol `admin`.

Todos los fallos de autenticación responden igual (401, mismo `detail`): el cliente no puede
distinguir un token caducado de uno falsificado o de un usuario borrado.
"""

from http import HTTPStatus
from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings
from app.core.db import DbSession
from app.core.security import InvalidAccessTokenError, decode_access_token
from app.models.user import User, UserRole
from app.repositories.user import UserRepository

UNAUTHORIZED_DETAIL = "No autenticado"
FORBIDDEN_DETAIL = "No tienes permiso para acceder a este recurso"

# auto_error=False: el 401 lo generamos nosotros, con el mismo formato que el resto de fallos.
# Además documenta el esquema Bearer en OpenAPI.
bearer_scheme = HTTPBearer(auto_error=False)

logger = structlog.get_logger(__name__)


def get_app_settings(request: Request) -> Settings:
    """La configuración con la que se creó la app (ver `create_app`)."""
    settings: Settings = request.app.state.settings
    return settings


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=HTTPStatus.UNAUTHORIZED,
        detail=UNAUTHORIZED_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    session: DbSession,
) -> User:
    if credentials is None:
        raise _unauthorized()
    try:
        claims = decode_access_token(credentials.credentials, settings)
    except InvalidAccessTokenError as error:
        # Solo el tipo de error, nunca el token.
        logger.info("access_token_rejected", reason=str(error))
        raise _unauthorized() from None

    user = await UserRepository(session).get_by_id(claims.user_id)
    if user is None:
        logger.info("access_token_rejected", reason="UnknownUser", user_id=str(claims.user_id))
        raise _unauthorized()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if user.role != UserRole.ADMIN:
        logger.warning("admin_access_denied", user_id=str(user.id))
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=FORBIDDEN_DETAIL)
    return user


AdminUser = Annotated[User, Depends(require_admin)]
