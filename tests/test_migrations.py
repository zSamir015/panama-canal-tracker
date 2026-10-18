from pathlib import Path

from alembic.config import Config

from app.models import Base

ROOT = Path(__file__).resolve().parent.parent


def test_alembic_points_to_the_versioned_migration_directory() -> None:
    config = Config(str(ROOT / "alembic.ini"))

    assert config.get_main_option("script_location").endswith("/alembic")
    assert (ROOT / "alembic" / "versions" / "20261018_0001_users_refresh_tokens.py").is_file()


def test_models_match_the_initial_schema() -> None:
    assert set(Base.metadata.tables) == {"users", "refresh_tokens"}

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


def test_migration_uses_owner_url_not_application_url() -> None:
    env_source = (ROOT / "alembic" / "env.py").read_text()

    assert "migrations_database_url" in env_source
    assert ".database_url" not in env_source
