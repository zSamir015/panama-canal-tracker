"""Hash de contraseñas (Argon2id) y tokens de acceso JWT (ADR-0003, AGENTS.md §8.4 y §8.17).

Funciones puras, sin I/O: no leen la base ni el entorno. La configuración llega por parámetro.
"""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import NamedTuple
from uuid import UUID, uuid4

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import Settings

# NIST SP 800-63B: longitud mínima, sin reglas de composición. El máximo acota el trabajo de
# Argon2 con entradas enormes.
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128

# Claims que todo access token debe traer; PyJWT rechaza el token si falta alguno.
REQUIRED_CLAIMS = ("sub", "iat", "exp", "iss", "aud", "jti")

# Parámetros por defecto de pwdlib (Argon2id, t=3, m=64 MiB, p=4). Si cambian, los hashes viejos
# siguen verificando y `verify_password` devuelve el hash nuevo para guardarlo.
password_hash = PasswordHash((Argon2Hasher(),))


class PasswordPolicyError(ValueError):
    """La contraseña no cumple la política de longitud."""


class InvalidAccessTokenError(Exception):
    """Token ausente, mal formado, caducado o con una firma o claim inválidos.

    Un solo tipo para todos los casos: el cliente recibe siempre la misma respuesta 401.
    """


class PasswordCheck(NamedTuple):
    valid: bool
    # Hash con los parámetros actuales cuando el guardado usa otros; `None` si no hay que rehashear.
    new_hash: str | None


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: UUID
    jti: str
    expires_at: datetime


def check_password_policy(password: str) -> None:
    # `len` cuenta caracteres (code points), no bytes: "contraseña" mide 10.
    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise PasswordPolicyError(
            f"La contraseña debe tener entre {PASSWORD_MIN_LENGTH} y {PASSWORD_MAX_LENGTH} "
            "caracteres"
        )


def hash_password(password: str) -> str:
    check_password_policy(password)
    return password_hash.hash(password)


@cache
def _dummy_hash() -> str:
    # Hash de una contraseña aleatoria que nadie conoce, calculado una vez por proceso.
    return password_hash.hash(secrets.token_urlsafe(32))


def verify_password(password: str, hashed: str | None) -> PasswordCheck:
    """Comprueba la contraseña contra el hash guardado.

    Con `hashed=None` (el email no existe) verifica igualmente contra un hash ficticio y devuelve
    inválido: la respuesta tarda lo mismo exista o no el usuario, así que el tiempo no revela qué
    emails están registrados (AGENTS.md §8.4).
    """
    if len(password) > PASSWORD_MAX_LENGTH:
        # Ninguna contraseña guardada puede medir más; se evita hashear entradas enormes.
        return PasswordCheck(valid=False, new_hash=None)
    if hashed is None:
        password_hash.verify(password, _dummy_hash())
        return PasswordCheck(valid=False, new_hash=None)
    valid, new_hash = password_hash.verify_and_update(password, hashed)
    return PasswordCheck(valid=valid, new_hash=new_hash)


def create_access_token(
    user_id: UUID, settings: Settings, *, now: datetime | None = None
) -> tuple[str, AccessTokenClaims]:
    issued_at = now or datetime.now(UTC)
    claims = AccessTokenClaims(
        user_id=user_id,
        jti=uuid4().hex,
        expires_at=issued_at + timedelta(minutes=settings.access_token_expire_minutes),
    )
    payload = {
        "sub": str(user_id),
        "iat": issued_at,
        "exp": claims.expires_at,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "jti": claims.jti,
    }
    token = jwt.encode(
        payload, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm
    )
    return token, claims


def decode_access_token(token: str, settings: Settings) -> AccessTokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            # Lista fija: un token con `alg: none` u otro algoritmo se rechaza antes de mirar nada.
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": list(REQUIRED_CLAIMS)},
        )
        return AccessTokenClaims(
            user_id=UUID(payload["sub"]),
            jti=payload["jti"],
            expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        )
    except (jwt.PyJWTError, ValueError) as error:
        # ValueError: `sub` no es un UUID. El mensaje original no se propaga al cliente.
        raise InvalidAccessTokenError(type(error).__name__) from None
