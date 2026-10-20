"""Excepciones de dominio (AGENTS.md §3).

Los servicios lanzan estas excepciones sin saber nada de HTTP más allá del código que les
corresponde; el handler global de `app/core/errors.py` las convierte en `problem+json`.
"""

from collections.abc import Mapping
from http import HTTPStatus
from types import MappingProxyType


class DomainError(Exception):
    status_code: HTTPStatus = HTTPStatus.BAD_REQUEST
    detail: str = "Petición inválida"
    headers: Mapping[str, str] = MappingProxyType({})


class EmailAlreadyRegisteredError(DomainError):
    status_code = HTTPStatus.CONFLICT
    detail = "Ya existe una cuenta con ese email"


class InvalidCredentialsError(DomainError):
    # Mismo mensaje exista o no el email (AGENTS.md §8.4).
    status_code = HTTPStatus.UNAUTHORIZED
    detail = "Email o contraseña incorrectos"
    headers = MappingProxyType({"WWW-Authenticate": "Bearer"})


class InvalidRefreshTokenError(DomainError):
    # Ausente, caducado, revocado o reutilizado: el cliente no distingue el motivo.
    status_code = HTTPStatus.UNAUTHORIZED
    detail = "Sesión inválida o caducada"
