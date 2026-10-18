from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings

STRONG_SECRET = "s3cr3t-de-prueba-con-mas-de-32-bytes-de-largo"
DB_PASSWORD = "pw-db-falsa-de-prueba"
DB_URL = f"postgresql+asyncpg://canal_app:{DB_PASSWORD}@db:5432/canal_tracker"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aísla los tests de las variables del entorno de quien los ejecuta."""
    for name in (
        "APP_ENV",
        "LOG_LEVEL",
        "CORS_ORIGINS",
        "JWT_SECRET_KEY",
        "DATABASE_URL",
        "MIGRATIONS_DATABASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def make_settings(**env: str) -> Settings:
    return Settings(_env_file=None, **env)  # type: ignore[arg-type]


def production_env(**overrides: str) -> dict[str, str]:
    env = {
        "app_env": "production",
        "cors_origins": "https://tracker.example.com",
        "jwt_secret_key": STRONG_SECRET,
        "database_url": DB_URL,
    }
    env.update(overrides)
    return env


def test_development_defaults() -> None:
    settings = make_settings()

    assert settings.app_env == "development"
    assert settings.log_level == "INFO"
    assert settings.cors_origins == ["http://localhost:5173"]


def test_reads_values_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")

    settings = make_settings()

    assert settings.app_env == "test"
    assert settings.log_level == "WARNING"


def test_cors_origins_parsed_from_comma_separated_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", " http://localhost:5173 , https://tracker.example.com ,")

    settings = make_settings()

    assert settings.cors_origins == ["http://localhost:5173", "https://tracker.example.com"]


def test_rejects_unknown_app_env() -> None:
    with pytest.raises(ValidationError):
        make_settings(app_env="staging")


def test_rejects_wildcard_cors_origin_in_any_environment() -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        make_settings(cors_origins="http://localhost:5173,*")


def test_rejects_empty_cors_origins() -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        make_settings(cors_origins=" , ")


@pytest.mark.parametrize(
    "origin",
    [
        "https://tracker.example.com/",  # el navegador envía el origen sin barra final
        "https://tracker.example.com/app",
        "https://tracker.example.com?x=1",
        "https://user@tracker.example.com",
        "null",  # lo envían iframes con sandbox y archivos locales
        "tracker.example.com",
        "ftp://tracker.example.com",
        "https://",
    ],
)
def test_rejects_malformed_cors_origin(origin: str) -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        make_settings(cors_origins=origin)


def test_accepts_cors_origin_with_port() -> None:
    settings = make_settings(cors_origins="http://localhost:5173,https://tracker.example.com:8443")

    assert settings.cors_origins == ["http://localhost:5173", "https://tracker.example.com:8443"]


def test_production_requires_https_cors_origins() -> None:
    with pytest.raises(ValidationError, match="https"):
        make_settings(**production_env(cors_origins="http://tracker.example.com"))


def test_jwt_secret_is_masked_in_repr() -> None:
    settings = make_settings(jwt_secret_key=STRONG_SECRET)

    assert STRONG_SECRET not in repr(settings)
    assert settings.jwt_secret_key.get_secret_value() == STRONG_SECRET


def test_valid_production_config_is_accepted() -> None:
    settings = make_settings(**production_env())

    assert settings.app_env == "production"
    assert settings.cors_origins == ["https://tracker.example.com"]


def test_production_rejects_placeholder_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        make_settings(**production_env(jwt_secret_key="changeme"))


def test_production_rejects_short_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        make_settings(**production_env(jwt_secret_key="x" * 31))


def test_production_requires_explicit_jwt_secret() -> None:
    env = production_env()
    del env["jwt_secret_key"]

    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        make_settings(**env)


def test_production_requires_explicit_cors_origins() -> None:
    env = production_env()
    del env["cors_origins"]

    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        make_settings(**env)


def test_production_rejects_debug_log_level() -> None:
    with pytest.raises(ValidationError, match="LOG_LEVEL"):
        make_settings(**production_env(log_level="DEBUG"))


def test_validation_error_does_not_leak_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    # Secreto corto a propósito: pydantic recorta los valores largos al mostrar el input,
    # así que solo uno corto prueba de verdad que no aparece en el error.
    weak_secret = "filtrable"
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CORS_ORIGINS", "https://tracker.example.com")
    monkeypatch.setenv("JWT_SECRET_KEY", weak_secret)

    with pytest.raises(ValidationError) as exc_info:
        make_settings()

    assert weak_secret not in str(exc_info.value)


def test_production_values_from_environment_count_as_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CORS_ORIGINS", "https://tracker.example.com")
    monkeypatch.setenv("JWT_SECRET_KEY", STRONG_SECRET)
    monkeypatch.setenv("DATABASE_URL", DB_URL)

    settings = make_settings()

    assert settings.app_env == "production"


def test_get_settings_reads_once_per_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)  # sin .env del desarrollador
    get_settings.cache_clear()
    try:
        assert get_settings() is get_settings()
    finally:
        get_settings.cache_clear()


def test_database_url_has_a_development_default() -> None:
    settings = make_settings()

    assert settings.database_url.get_secret_value().startswith("postgresql+asyncpg://")


def test_database_url_never_appears_in_repr_or_str() -> None:
    settings = make_settings(database_url=DB_URL)

    assert DB_PASSWORD not in repr(settings)
    assert DB_PASSWORD not in str(settings)
    assert DB_PASSWORD not in settings.model_dump_json()
    assert settings.database_url.get_secret_value() == DB_URL


def test_database_url_rejects_other_drivers_without_leaking_the_value() -> None:
    url = f"postgresql://canal_app:{DB_PASSWORD}@db:5432/canal_tracker"

    with pytest.raises(ValidationError) as error:
        make_settings(database_url=url)

    assert "postgresql+asyncpg://" in str(error.value)
    assert DB_PASSWORD not in str(error.value)
    assert DB_PASSWORD not in repr(error.value.errors(include_input=False))


def test_production_requires_database_url() -> None:
    env = production_env()
    del env["database_url"]

    with pytest.raises(ValidationError, match="DATABASE_URL es obligatoria"):
        make_settings(**env)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://canal_app:changeme@db:5432/canal_tracker",
        "postgresql+asyncpg://canal_app@db:5432/canal_tracker",
        "postgresql+asyncpg://canal_app:@db:5432/canal_tracker",
    ],
)
def test_production_rejects_a_database_url_without_a_real_password(url: str) -> None:
    with pytest.raises(ValidationError, match="contraseña real"):
        make_settings(**production_env(database_url=url))


def test_production_accepts_a_database_url_with_a_password() -> None:
    settings = make_settings(**production_env(database_url=DB_URL))

    assert settings.database_url.get_secret_value() == DB_URL


def test_production_errors_never_include_the_database_url() -> None:
    with pytest.raises(ValidationError) as error:
        make_settings(
            **production_env(
                database_url=f"postgresql+asyncpg://canal_app:changeme@db:5432/x?{DB_PASSWORD}",
                log_level="DEBUG",
            )
        )

    assert DB_PASSWORD not in str(error.value)


OWNER_URL = f"postgresql+asyncpg://canal_owner:{DB_PASSWORD}@db:5432/canal_tracker"


def test_migrations_database_url_is_optional_for_the_api() -> None:
    # La API nunca necesita la URL del rol con DDL, ni siquiera en producción.
    assert make_settings().migrations_database_url is None
    assert make_settings(**production_env()).migrations_database_url is None


def test_migrations_database_url_never_appears_in_repr_or_str() -> None:
    settings = make_settings(migrations_database_url=OWNER_URL)

    assert DB_PASSWORD not in repr(settings)
    assert DB_PASSWORD not in str(settings)
    assert DB_PASSWORD not in settings.model_dump_json()
    assert settings.migrations_database_url is not None
    assert settings.migrations_database_url.get_secret_value() == OWNER_URL


@pytest.mark.parametrize("field", ["database_url", "migrations_database_url"])
def test_url_scheme_error_names_the_variable_without_leaking_it(field: str) -> None:
    url = f"postgresql://canal_owner:{DB_PASSWORD}@db:5432/canal_tracker"

    with pytest.raises(ValidationError) as error:
        make_settings(**{field: url})

    assert f"{field.upper()} debe usar el esquema postgresql+asyncpg://" in str(error.value)
    assert DB_PASSWORD not in str(error.value)
