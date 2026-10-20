"""Autenticación y autorización con usuarios reales en la base de test."""

import io
from collections.abc import AsyncIterator, Iterator
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.auth import FORBIDDEN_DETAIL, UNAUTHORIZED_DETAIL, CurrentUser
from app.core.db import SessionFactory
from app.core.logging import configure_logging
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User, UserRole
from app.repositories.user import UserRepository

PASSWORD = "contraseña-de-prueba-larga"
ADMIN_PATH = "/api/v1/admin/_test"


@pytest.fixture
def admin_test_route(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from app.routers import admin

    monkeypatch.setattr(admin.router, "routes", list(admin.router.routes))

    @admin.router.get("/_test")
    async def admin_only() -> dict[str, str]:
        return {"ok": "admin"}

    yield


@pytest.fixture
async def app(
    migrated: AsyncEngine, admin_test_route: None, db_app: FastAPI
) -> AsyncIterator[FastAPI]:
    # Ruta que solo exige un usuario autenticado, para probar `get_current_user` por sí sola.
    @db_app.get("/_test/me")
    async def me(user: CurrentUser) -> dict[str, str]:
        return {"id": str(user.id), "role": user.role}

    yield db_app


@pytest.fixture
def sessions(app: FastAPI) -> SessionFactory:
    factory: SessionFactory = app.state.session_factory
    return factory


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def add_user(sessions: SessionFactory, email: str, role: UserRole = UserRole.USER) -> User:
    async with sessions() as session:
        user = await UserRepository(session).add(
            email=email, hashed_password=hash_password(PASSWORD), role=role
        )
        await session.commit()
        return user


def bearer_for(app: FastAPI, user_id: UUID) -> dict[str, str]:
    token, _ = create_access_token(user_id, app.state.settings)
    return {"Authorization": f"Bearer {token}"}


# --- get_current_user / require_admin ------------------------------------------------------


async def test_valid_token_identifies_the_user(
    app: FastAPI, client: AsyncClient, sessions: SessionFactory
) -> None:
    user = await add_user(sessions, "ana@example.com")

    response = await client.get("/_test/me", headers=bearer_for(app, user.id))

    assert response.status_code == 200
    assert response.json() == {"id": str(user.id), "role": "user"}


async def test_user_role_gets_403_on_admin_routes(
    app: FastAPI, client: AsyncClient, sessions: SessionFactory
) -> None:
    user = await add_user(sessions, "ana@example.com")

    response = await client.get(ADMIN_PATH, headers=bearer_for(app, user.id))

    assert response.status_code == 403
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["detail"] == FORBIDDEN_DETAIL


async def test_admin_role_reaches_admin_routes(
    app: FastAPI, client: AsyncClient, sessions: SessionFactory
) -> None:
    admin_user = await add_user(sessions, "admin@example.com", UserRole.ADMIN)

    response = await client.get(ADMIN_PATH, headers=bearer_for(app, admin_user.id))

    assert response.status_code == 200
    assert response.json() == {"ok": "admin"}


async def test_admin_routes_without_token_get_401(client: AsyncClient) -> None:
    response = await client.get(ADMIN_PATH)

    assert response.status_code == 401
    assert response.json()["detail"] == UNAUTHORIZED_DETAIL


async def test_role_is_read_from_the_database_on_every_request(
    app: FastAPI, client: AsyncClient, sessions: SessionFactory
) -> None:
    # El rol no va en el token: quitarle el admin a alguien tiene efecto inmediato.
    admin_user = await add_user(sessions, "admin@example.com", UserRole.ADMIN)
    headers = bearer_for(app, admin_user.id)
    assert (await client.get(ADMIN_PATH, headers=headers)).status_code == 200

    async with sessions() as session:
        await session.execute(
            update(User).where(User.id == admin_user.id).values(role=UserRole.USER)
        )
        await session.commit()

    assert (await client.get(ADMIN_PATH, headers=headers)).status_code == 403


async def test_token_of_a_deleted_user_gets_the_same_401(
    app: FastAPI, client: AsyncClient, sessions: SessionFactory
) -> None:
    user = await add_user(sessions, "ana@example.com")
    headers = bearer_for(app, user.id)
    async with sessions() as session:
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()

    response = await client.get("/_test/me", headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["detail"] == UNAUTHORIZED_DETAIL


async def test_denied_requests_never_log_tokens_or_hashes(
    app: FastAPI, client: AsyncClient, sessions: SessionFactory
) -> None:
    stream = io.StringIO()
    configure_logging("DEBUG", stream=stream)
    user = await add_user(sessions, "ana@example.com")
    headers = bearer_for(app, user.id)

    await client.get(ADMIN_PATH, headers=headers)

    output = stream.getvalue()
    assert "admin_access_denied" in output
    assert headers["Authorization"].removeprefix("Bearer ") not in output
    assert user.hashed_password not in output
    assert PASSWORD not in output


# --- UserRepository ------------------------------------------------------------------------


async def test_email_is_stored_and_found_in_lowercase(sessions: SessionFactory) -> None:
    user = await add_user(sessions, "Ana.Perez@Example.COM")

    async with sessions() as session:
        found = await UserRepository(session).get_by_email("ANA.PEREZ@example.com")

    assert user.email == "ana.perez@example.com"
    assert found is not None and found.id == user.id


async def test_same_email_in_other_case_is_a_duplicate(sessions: SessionFactory) -> None:
    await add_user(sessions, "ana@example.com")

    with pytest.raises(IntegrityError):
        await add_user(sessions, "ANA@example.com")


async def test_password_hash_can_be_replaced(sessions: SessionFactory) -> None:
    user = await add_user(sessions, "ana@example.com")
    new_hash = hash_password("otra-contraseña-larga")

    async with sessions() as session:
        users = UserRepository(session)
        stored = await users.get_by_id(user.id)
        assert stored is not None
        await users.update_password_hash(stored, new_hash)
        await session.commit()

    async with sessions() as session:
        reloaded = await UserRepository(session).get_by_id(user.id)
    assert reloaded is not None
    assert verify_password("otra-contraseña-larga", reloaded.hashed_password).valid


async def test_user_role_enum_matches_the_database(migrated: AsyncEngine) -> None:
    async with migrated.connect() as connection:
        labels = (
            await connection.execute(text("SELECT unnest(enum_range(NULL::user_role))"))
        ).all()

    assert {label for (label,) in labels} == {role.value for role in UserRole}
