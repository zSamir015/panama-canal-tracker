"""Endpoints `/api/v1/auth/*` (docs/API_DESIGN.md "Auth").

Dos routers:
- `public_router`: register, login y refresh. Es la lista blanca de AGENTS.md §8.9; `app/main.py`
  lo monta fuera del router que exige token.
- `router`: logout y me, que exigen access token como el resto de `/api/v1`.

El refresh token viaja solo en una cookie `HttpOnly` (JavaScript no puede leerla), `Secure`,
`SameSite=Strict` y limitada a `/api/v1/auth`: nunca en el cuerpo de la respuesta.
"""

from datetime import UTC, datetime
from http import HTTPStatus
from typing import Annotated, Any

from fastapi import APIRouter, Cookie, Depends, Response

from app.core.auth import CurrentUser, get_app_settings
from app.core.config import Settings
from app.core.db import DbSession
from app.core.rate_limit import enforce_login, enforce_refresh, enforce_register
from app.schemas.auth import LoginRequest, TokenResponse, UserCreate, UserResponse
from app.services.auth import AuthService, IssuedTokens

REFRESH_COOKIE = "refresh_token"
REFRESH_COOKIE_PATH = "/api/v1/auth"
# Un refresh token firmado mide unos 400 bytes; nada legítimo se acerca a este límite.
REFRESH_COOKIE_MAX_LENGTH = 2048

PROBLEM: dict[str, Any] = {"content": {"application/problem+json": {}}}
UNAUTHORIZED: dict[int | str, dict[str, Any]] = {
    HTTPStatus.UNAUTHORIZED: {"description": "No autenticado", **PROBLEM}
}
INVALID_BODY: dict[int | str, dict[str, Any]] = {
    HTTPStatus.UNPROCESSABLE_ENTITY: {"description": "Datos inválidos", **PROBLEM}
}

public_router = APIRouter(prefix="/auth", tags=["auth"])
router = APIRouter(prefix="/auth", tags=["auth"])

RefreshCookie = Annotated[
    str | None, Cookie(alias=REFRESH_COOKIE, max_length=REFRESH_COOKIE_MAX_LENGTH)
]


def get_auth_service(
    session: DbSession, settings: Annotated[Settings, Depends(get_app_settings)]
) -> AuthService:
    return AuthService(session, settings)


Service = Annotated[AuthService, Depends(get_auth_service)]


def _set_refresh_cookie(response: Response, tokens: IssuedTokens) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token,
        max_age=int((tokens.refresh_expires_at - datetime.now(UTC)).total_seconds()),
        path=REFRESH_COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="strict",
    )


def _token_response(response: Response, tokens: IssuedTokens) -> TokenResponse:
    _set_refresh_cookie(response, tokens)
    return TokenResponse(access_token=tokens.access_token, expires_in=tokens.access_expires_in)


@public_router.post(
    "/register",
    dependencies=[Depends(enforce_register)],
    status_code=HTTPStatus.CREATED,
    summary="Crear una cuenta",
    description=(
        "Crea un usuario con rol `user`. El rol no se acepta en el cuerpo: cualquier campo "
        "desconocido responde 422. La contraseña debe tener entre 12 y 128 caracteres."
    ),
    responses={
        HTTPStatus.CONFLICT: {"description": "El email ya está registrado", **PROBLEM},
        **INVALID_BODY,
    },
)
async def register(body: UserCreate, service: Service) -> UserResponse:
    user = await service.register(body.email, body.password)
    return UserResponse.model_validate(user)


@public_router.post(
    "/login",
    dependencies=[Depends(enforce_login)],
    summary="Iniciar sesión",
    description=(
        "Devuelve un access token y deja el refresh token en la cookie `refresh_token`. "
        "Las credenciales incorrectas responden siempre el mismo 401, exista o no el email."
    ),
    responses={**UNAUTHORIZED, **INVALID_BODY},
)
async def login(body: LoginRequest, response: Response, service: Service) -> TokenResponse:
    return _token_response(response, await service.login(body.email, body.password))


@public_router.post(
    "/refresh",
    dependencies=[Depends(enforce_refresh)],
    summary="Renovar el access token",
    description=(
        "Usa la cookie `refresh_token`, la rota (la anterior deja de valer) y devuelve un access "
        "token nuevo. Reutilizar un refresh ya rotado revoca toda la sesión."
    ),
    responses=UNAUTHORIZED,
)
async def refresh(
    response: Response, service: Service, refresh_token: RefreshCookie = None
) -> TokenResponse:
    return _token_response(response, await service.refresh(refresh_token))


@router.post(
    "/logout",
    status_code=HTTPStatus.NO_CONTENT,
    summary="Cerrar sesión",
    description="Revoca la sesión del refresh token de la cookie y borra la cookie.",
    responses=UNAUTHORIZED,
)
async def logout(
    user: CurrentUser, service: Service, refresh_token: RefreshCookie = None
) -> Response:
    await service.logout(user, refresh_token)
    response = Response(status_code=HTTPStatus.NO_CONTENT)
    response.delete_cookie(
        REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, secure=True, httponly=True, samesite="strict"
    )
    return response


@router.get(
    "/me",
    summary="Usuario actual",
    description="Perfil del usuario del access token.",
    responses=UNAUTHORIZED,
)
async def me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)
