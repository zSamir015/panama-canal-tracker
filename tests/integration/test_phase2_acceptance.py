"""Aceptación de la Fase 2 (docs/ROADMAP.md): el flujo completo contra PostgreSQL y Redis reales.

register → login → endpoint protegido → refresh → logout, y el límite de intentos del login
contado en Redis, todo por HTTP como lo haría el navegador.
"""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from limits.aio.storage import RedisStorage
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.rate_limit import AppRateLimiter

AUTH = "/api/v1/auth"
EMAIL = "demo@example.com"
PASSWORD = "una frase larga para la demo"


@pytest.fixture
async def app(
    migrated: AsyncEngine, db_app: FastAPI, redis_storage: RedisStorage
) -> AsyncIterator[FastAPI]:
    # Contador en el Redis real (base 15) en lugar del de memoria de los tests unitarios.
    db_app.state.rate_limiter = AppRateLimiter(redis_storage)
    yield db_app


@pytest.fixture
async def browser(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Un cliente que guarda las cookies entre peticiones, como un navegador (https: `Secure`)."""
    transport = ASGITransport(app=app, client=("203.0.113.20", 50000))
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        yield client


async def test_register_login_protected_refresh_logout(browser: AsyncClient) -> None:
    # 1. Registro: siempre rol `user`.
    registered = await browser.post(f"{AUTH}/register", json={"email": EMAIL, "password": PASSWORD})
    assert registered.status_code == 201
    assert registered.json()["role"] == "user"

    # 2. Login: access token en el cuerpo, refresh solo en la cookie.
    login = await browser.post(f"{AUTH}/login", json={"email": EMAIL, "password": PASSWORD})
    assert login.status_code == 200
    access = login.json()["access_token"]
    first_refresh = browser.cookies["refresh_token"]
    assert first_refresh not in login.text

    # 3. Endpoint protegido: sin token 401, con token el perfil propio.
    assert (await browser.get(f"{AUTH}/me")).status_code == 401
    me = await browser.get(f"{AUTH}/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200
    assert me.json()["id"] == registered.json()["id"]

    # 4. Refresh: la cookie rota y el access token nuevo funciona.
    refreshed = await browser.post(f"{AUTH}/refresh")
    assert refreshed.status_code == 200
    new_access = refreshed.json()["access_token"]
    assert browser.cookies["refresh_token"] != first_refresh
    headers = {"Authorization": f"Bearer {new_access}"}
    assert (await browser.get(f"{AUTH}/me", headers=headers)).status_code == 200

    # 5. Logout: 204, la cookie desaparece y la sesión ya no se puede renovar.
    assert (await browser.post(f"{AUTH}/logout", headers=headers)).status_code == 204
    assert "refresh_token" not in browser.cookies
    assert (await browser.post(f"{AUTH}/refresh")).status_code == 401


async def test_login_brute_force_is_stopped_by_redis(browser: AsyncClient) -> None:
    await browser.post(f"{AUTH}/register", json={"email": EMAIL, "password": PASSWORD})
    wrong = {"email": EMAIL, "password": "contraseña equivocada larga"}

    statuses = [(await browser.post(f"{AUTH}/login", json=wrong)).status_code for _ in range(5)]
    blocked = await browser.post(f"{AUTH}/login", json={"email": EMAIL, "password": PASSWORD})

    assert statuses == [401] * 5
    # Ni siquiera la contraseña correcta pasa mientras dura el bloqueo.
    assert blocked.status_code == 429
    assert blocked.headers["content-type"] == "application/problem+json"
    assert 1 <= int(blocked.headers["retry-after"]) <= 60
