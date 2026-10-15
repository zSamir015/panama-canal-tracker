"""Configuración de la aplicación leída de variables de entorno (AGENTS.md §8.2).

Este es el único módulo que lee el entorno. El resto del código pide la configuración con
`get_settings()` y nunca usa `os.environ`.
"""

from functools import lru_cache
from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

AppEnv = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

JWT_SECRET_PLACEHOLDER = "changeme"  # noqa: S105 (placeholder de .env.example, no es un secreto)
JWT_SECRET_MIN_BYTES = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # `.env` trae variables de fases futuras que aún no se leen aquí.
        extra="ignore",
        frozen=True,
        # Sin esto, pydantic copia el input (con el secreto en claro) en el mensaje de error.
        hide_input_in_errors=True,
    )

    app_env: AppEnv = "development"
    log_level: LogLevel = "INFO"
    # NoDecode: el valor llega como "a,b,c" y no como JSON; se separa en el validador.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    jwt_secret_key: SecretStr = SecretStr(JWT_SECRET_PLACEHOLDER)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def reject_wildcard_origin(cls, value: list[str]) -> list[str]:
        if "*" in value:
            raise ValueError("CORS_ORIGINS no puede contener '*'; lista los orígenes explícitos")
        return value

    @model_validator(mode="after")
    def check_production(self) -> Self:
        """Fail fast: en producción la app no arranca con una configuración insegura.

        Los mensajes nunca incluyen el valor del secreto.
        """
        if self.app_env != "production":
            return self

        errors: list[str] = []
        secret = self.jwt_secret_key.get_secret_value()
        if "jwt_secret_key" not in self.model_fields_set:
            errors.append("JWT_SECRET_KEY es obligatoria en producción")
        elif secret == JWT_SECRET_PLACEHOLDER:
            errors.append("JWT_SECRET_KEY no puede ser el placeholder en producción")
        elif len(secret.encode()) < JWT_SECRET_MIN_BYTES:
            errors.append(f"JWT_SECRET_KEY debe medir al menos {JWT_SECRET_MIN_BYTES} bytes")

        if "cors_origins" not in self.model_fields_set:
            errors.append("CORS_ORIGINS es obligatoria en producción")

        if self.log_level == "DEBUG":
            errors.append("LOG_LEVEL no puede ser DEBUG en producción")

        if errors:
            raise ValueError("; ".join(errors))
        return self


@lru_cache
def get_settings() -> Settings:
    """Devuelve la configuración, leída una sola vez por proceso."""
    return Settings()
