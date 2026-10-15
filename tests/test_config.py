from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings

STRONG_SECRET = "s3cr3t-de-prueba-con-mas-de-32-bytes-de-largo"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aísla los tests de las variables del entorno de quien los ejecuta."""
    for name in ("APP_ENV", "LOG_LEVEL", "CORS_ORIGINS", "JWT_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)


def make_settings(**env: str) -> Settings:
    return Settings(_env_file=None, **env)  # type: ignore[arg-type]


def production_env(**overrides: str) -> dict[str, str]:
    env = {
        "app_env": "production",
        "cors_origins": "https://tracker.example.com",
        "jwt_secret_key": STRONG_SECRET,
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
