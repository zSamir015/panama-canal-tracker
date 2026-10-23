from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

import app.core.config
from app.core.config import Settings
from app.models import Base
from app.models.base import include_object

ROOT = Path(__file__).resolve().parent.parent


def test_alembic_points_to_the_versioned_migration_directory() -> None:
    config = Config(str(ROOT / "alembic.ini"))

    assert config.get_main_option("script_location").endswith("/alembic")
    assert (ROOT / "alembic" / "versions" / "20261018_0001_users_refresh_tokens.py").is_file()
    assert (ROOT / "alembic" / "versions" / "20261020_0002_vessels_positions.py").is_file()
    assert (ROOT / "alembic" / "versions" / "20261022_0003_canal_bound_vessels.py").is_file()


def test_models_declare_the_persistent_tables() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "refresh_tokens",
        "vessels",
        "positions",
        "canal_bound_vessels",
    }

    users = Base.metadata.tables["users"]
    assert {column.name for column in users.primary_key.columns} == {"id"}
    assert users.c.email.unique is True
    assert users.c.hashed_password.nullable is False
    assert users.c.role.nullable is False

    refresh_tokens = Base.metadata.tables["refresh_tokens"]
    assert {column.name for column in refresh_tokens.primary_key.columns} == {"jti"}
    assert refresh_tokens.c.family_id.nullable is False
    assert refresh_tokens.c.expires_at.nullable is False
    assert refresh_tokens.c.revoked_at.nullable is True
    assert refresh_tokens.c.replaced_by_jti.nullable is True

    vessels = Base.metadata.tables["vessels"]
    assert {column.name for column in vessels.primary_key.columns} == {"mmsi"}
    assert vessels.c.updated_at.nullable is False

    positions = Base.metadata.tables["positions"]
    assert {column.name for column in positions.primary_key.columns} == {
        "received_at",
        "vessel_mmsi",
    }
    assert positions.c.geom.nullable is False

    canal_bound = Base.metadata.tables["canal_bound_vessels"]
    assert {column.name for column in canal_bound.primary_key.columns} == {"mmsi"}
    assert canal_bound.c.destination.nullable is False
    assert canal_bound.c.port_locode.nullable is False
    assert canal_bound.c.reported_at.nullable is False


def alembic_config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["configure_logger"] = False
    return config


def test_extension_tables_are_ignored_but_ours_are_not() -> None:
    users = Base.metadata.tables["users"]

    assert include_object(users, "spatial_ref_sys", "table", True, None) is False
    assert include_object(users, "users", "table", True, None) is True
    assert include_object(users, "spatial_ref_sys", "table", False, users) is True


def test_alembic_refuses_to_run_without_the_migrations_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Sin MIGRATIONS_DATABASE_URL, Alembic no debe caer en otra URL (ni en la de canal_app).
    monkeypatch.delenv("MIGRATIONS_DATABASE_URL", raising=False)
    monkeypatch.setattr(app.core.config, "get_settings", lambda: Settings(_env_file=None))

    with pytest.raises(RuntimeError, match="MIGRATIONS_DATABASE_URL no está definida"):
        command.upgrade(alembic_config(), "head")


def test_alembic_refuses_offline_mode() -> None:
    with pytest.raises(RuntimeError, match="offline"):
        command.upgrade(alembic_config(), "head", sql=True)


def test_server_defaults_are_sql_expressions_not_string_literals() -> None:
    # `server_default="now()"` se compila como DEFAULT 'now()': un texto que PostgreSQL convierte
    # en una fecha fija al crear la tabla. Hay que usar `func.now()` o `text(...)`.
    literals = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if column.server_default is not None
        and isinstance(getattr(column.server_default, "arg", None), str)
    ]

    assert literals == []
