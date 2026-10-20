"""Contrato de los endpoints de auth (docs/API_DESIGN.md, AGENTS.md §8.6).

`extra="forbid"`: un campo desconocido (por ejemplo `role`) se rechaza con 422 en lugar de
ignorarse; así nadie puede colarse un rol en el registro.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.core.security import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH
from app.models.user import UserRole

NewPassword = Annotated[
    str, StringConstraints(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
]
# Al hacer login no se aplica el mínimo: la política podría endurecerse después de registrarse.
# El máximo sí, para no hashear entradas enormes.
LoginPassword = Annotated[str, StringConstraints(min_length=1, max_length=PASSWORD_MAX_LENGTH)]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class UserCreate(_Request):
    email: EmailStr = Field(max_length=320, examples=["demo@example.com"])
    password: NewPassword = Field(examples=["una frase larga y fácil de recordar"])


class LoginRequest(_Request):
    email: EmailStr = Field(max_length=320, examples=["demo@example.com"])
    password: LoginPassword


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 (tipo de token OAuth2, no un secreto)
    expires_in: int = Field(description="Segundos hasta que caduca el access token")


class UserResponse(BaseModel):
    """Perfil público del usuario. Nunca incluye el hash de la contraseña."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    role: UserRole
    created_at: datetime
