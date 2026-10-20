"""Configuración de la aplicación leída de variables de entorno (AGENTS.md §8.2).

Este es el único módulo que lee el entorno. El resto del código pide la configuración con
`get_settings()` y nunca usa `os.environ`.
"""

from functools import lru_cache
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

AppEnv = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

JWT_SECRET_PLACEHOLDER = "changeme"  # noqa: S105 (placeholder de .env.example, no es un secreto)
JWT_SECRET_MIN_BYTES = 32
DATABASE_URL_PLACEHOLDER = "postgresql+asyncpg://canal_app:changeme@localhost:5432/canal_tracker"
DATABASE_DRIVER_SCHEME = "postgresql+asyncpg"
DATABASE_PASSWORD_PLACEHOLDER = "changeme"  # noqa: S105 (placeholder de .env.example)
REDIS_URL_PLACEHOLDER = "redis://:changeme@localhost:6379/0"


def _is_origin(value: str) -> bool:
    """`esquema://host[:puerto]` exacto, como lo envía el navegador en la cabecera `Origin`."""
    parts = urlsplit(value)
    return (
        parts.scheme in ("http", "https")
        and bool(parts.hostname)
        and "@" not in parts.netloc
        and value == f"{parts.scheme}://{parts.netloc}"
    )


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
    # Un solo valor posible: nadie puede configurar `none` ni mezclar HS256 con claves públicas.
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_issuer: str = Field(default="panama-canal-tracker", min_length=1)
    jwt_audience: str = Field(default="panama-canal-tracker-api", min_length=1)
    access_token_expire_minutes: int = Field(default=15, ge=1, le=60)
    refresh_token_expire_days: int = Field(default=7, ge=1, le=30)
    # Lleva la contraseña del rol `canal_app` (sin DDL), así que es un secreto (AGENTS.md §8.16).
    database_url: SecretStr = SecretStr(DATABASE_URL_PLACEHOLDER)
    # Rol `canal_owner` (DDL). Solo la usa Alembic: el proceso de la API no necesita tenerla, así
    # que no tiene valor por defecto y `alembic/env.py` falla si no está definida.
    migrations_database_url: SecretStr | None = None
    redis_url: SecretStr = SecretStr(REDIS_URL_PLACEHOLDER)

    @field_validator("database_url", "migrations_database_url")
    @classmethod
    def require_asyncpg_url(cls, value: SecretStr | None, info: ValidationInfo) -> SecretStr | None:
        # El mensaje nombra la variable pero no incluye el valor: la URL lleva la contraseña.
        if (
            value is not None
            and urlsplit(value.get_secret_value()).scheme != DATABASE_DRIVER_SCHEME
        ):
            name = (info.field_name or "").upper()
            raise ValueError(f"{name} debe usar el esquema {DATABASE_DRIVER_SCHEME}://")
        return value

    @field_validator("redis_url")
    @classmethod
    def require_redis_url(cls, value: SecretStr) -> SecretStr:
        if urlsplit(value.get_secret_value()).scheme not in {"redis", "rediss"}:
            raise ValueError("REDIS_URL debe usar el esquema redis:// o rediss://")
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def require_explicit_origins(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("CORS_ORIGINS debe contener al menos un origen explícito")
        if "*" in value:
            raise ValueError("CORS_ORIGINS no puede contener '*'; lista los orígenes explícitos")
        for origin in value:
            if not _is_origin(origin):
                # El navegador compara el origen exacto: "https://x.com/" no coincidiría nunca.
                raise ValueError(
                    f"CORS_ORIGINS: {origin!r} no es un origen válido (esquema://host[:puerto])"
                )
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

        if "database_url" not in self.model_fields_set:
            errors.append("DATABASE_URL es obligatoria en producción")
        elif urlsplit(self.database_url.get_secret_value()).password in (
            None,
            "",
            DATABASE_PASSWORD_PLACEHOLDER,
        ):
            errors.append("DATABASE_URL debe llevar una contraseña real en producción")

        redis_parts = urlsplit(self.redis_url.get_secret_value())
        if "redis_url" not in self.model_fields_set:
            errors.append("REDIS_URL es obligatoria en producción")
        elif redis_parts.password in (None, "", DATABASE_PASSWORD_PLACEHOLDER):
            errors.append("REDIS_URL debe llevar una contraseña real en producción")

        if "cors_origins" not in self.model_fields_set:
            errors.append("CORS_ORIGINS es obligatoria en producción")
        elif any(not origin.startswith("https://") for origin in self.cors_origins):
            errors.append("CORS_ORIGINS solo admite orígenes https en producción")

        if self.log_level == "DEBUG":
            errors.append("LOG_LEVEL no puede ser DEBUG en producción")

        if errors:
            raise ValueError("; ".join(errors))
        return self


@lru_cache
def get_settings() -> Settings:
    """Devuelve la configuración, leída una sola vez por proceso."""
    return Settings()
