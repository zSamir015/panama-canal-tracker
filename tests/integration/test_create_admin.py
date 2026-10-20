"""`scripts/create_admin.py` contra la base de test."""

import importlib.util
import io
from pathlib import Path
from types import ModuleType

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.db import SessionFactory
from app.core.logging import configure_logging
from app.core.security import verify_password
from app.models.user import UserRole
from app.repositories.user import UserRepository

ROOT = Path(__file__).resolve().parent.parent.parent
PASSWORD = "contraseña-del-admin-larga"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("create_admin", ROOT / "scripts/create_admin.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


create_admin_script = load_script()
AdminCreationError = create_admin_script.AdminCreationError


@pytest.fixture
def sessions(migrated: AsyncEngine, db_app: FastAPI) -> SessionFactory:
    factory: SessionFactory = db_app.state.session_factory
    return factory


async def test_creates_an_admin_with_a_hashed_password_and_lowercase_email(
    sessions: SessionFactory,
) -> None:
    user_id = await create_admin_script.create_admin(sessions, "Admin@Example.com", PASSWORD)

    async with sessions() as session:
        user = await UserRepository(session).get_by_id(user_id)
    assert user is not None
    assert user.email == "admin@example.com"
    assert user.role == UserRole.ADMIN
    assert user.hashed_password.startswith("$argon2id$")
    assert verify_password(PASSWORD, user.hashed_password).valid


async def test_refuses_an_existing_email_in_any_case(sessions: SessionFactory) -> None:
    await create_admin_script.create_admin(sessions, "admin@example.com", PASSWORD)

    with pytest.raises(AdminCreationError, match="Ya existe"):
        await create_admin_script.create_admin(sessions, "ADMIN@example.com", PASSWORD)


@pytest.mark.parametrize(
    ("email", "password", "message"),
    [
        ("no-es-un-email", PASSWORD, "email no es válido"),
        ("admin@example.com", "corta", "entre 12 y 128"),
        ("admin@example.com", "a" * 129, "entre 12 y 128"),
    ],
)
async def test_rejects_invalid_input_without_writing(
    sessions: SessionFactory, email: str, password: str, message: str
) -> None:
    with pytest.raises(AdminCreationError, match=message):
        await create_admin_script.create_admin(sessions, email, password)

    async with sessions() as session:
        assert await UserRepository(session).get_by_email("admin@example.com") is None


def test_main_logs_the_new_id_but_never_the_email_or_password(
    monkeypatch: pytest.MonkeyPatch, migrated: AsyncEngine, db_settings: Settings
) -> None:
    # `main()` completo, con su propio engine y su propio event loop, contra la base de test.
    stream = io.StringIO()
    monkeypatch.setattr(create_admin_script, "get_settings", lambda: db_settings)
    monkeypatch.setattr(create_admin_script, "read_password", lambda: PASSWORD)
    monkeypatch.setattr(
        create_admin_script,
        "configure_logging",
        lambda level: configure_logging(level, stream=stream),
    )

    assert create_admin_script.main(["admin@example.com"]) == 0
    assert create_admin_script.main(["admin@example.com"]) == 1

    output = stream.getvalue()
    assert '"event": "admin_created"' in output
    assert '"event": "admin_not_created"' in output
    assert "admin@example.com" not in output
    assert PASSWORD not in output
    assert "$argon2id$" not in output


def test_password_mismatch_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter([PASSWORD, PASSWORD + "x"])
    monkeypatch.setattr(create_admin_script.getpass, "getpass", lambda _prompt: next(answers))

    with pytest.raises(AdminCreationError, match="no coinciden"):
        create_admin_script.read_password()
