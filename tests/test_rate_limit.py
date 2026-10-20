"""Rate limiting sin base de datos ni Redis (ADR-0007).

Cada app de test cuenta en memoria (`tests/conftest.py`). El servicio de auth y el usuario actual
se sustituyen con `dependency_overrides`, así los tests no dependen de PostgreSQL: lo que se
prueba aquí es el límite, no el login.
"""

import io
import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from limits.aio.storage import MemoryStorage

from app.core.auth import get_current_user
from app.core.config import Settings
from app.core.logging import configure_logging
from app.core.rate_limit import AppRateLimiter, create_storage, email_key
from app.models.user import User, UserRole
from app.routers.auth import get_auth_service
from app.services.exceptions import InvalidCredentialsError, InvalidRefreshTokenError

AUTH = "/api/v1/auth"
EMAIL = "ana@example.com"
PASSWORD = "una frase larga de prueba"
LOGIN_BODY = {"email": EMAIL, "password": PASSWORD}


class RejectingAuthService:
    """Login siempre fallido y refresh siempre inválido, sin tocar la base."""

    async def login(self, email: str, password: str) -> None:
        raise InvalidCredentialsError

    async def register(self, email: str, password: str) -> None:
        raise InvalidCredentialsError

    async def refresh(self, refresh_token: str | None) -> None:
        raise InvalidRefreshTokenError


@pytest.fixture
def user() -> User:
    return User(
        id=uuid4(),
        email=EMAIL,
        hashed_password="no-se-usa",
        role=UserRole.USER,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def limited_app(app: FastAPI, user: User) -> Iterator[FastAPI]:
    app.dependency_overrides[get_auth_service] = RejectingAuthService
    app.dependency_overrides[get_current_user] = lambda: user
    yield app
    app.dependency_overrides.clear()


def client_from(app: FastAPI, ip: str = "203.0.113.10") -> AsyncClient:
    transport = ASGITransport(app=app, client=(ip, 50000))
    return AsyncClient(transport=transport, base_url="https://test")


@pytest.fixture
async def client(limited_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with client_from(limited_app) as c:
        yield c


def assert_rate_limited(response: Response, window_seconds: int = 60) -> None:
    assert response.status_code == 429
    assert response.headers["content-type"] == "application/problem+json"
    assert 1 <= int(response.headers["retry-after"]) <= window_seconds
    assert response.json()["detail"] == "Demasiadas peticiones; vuelve a intentarlo más tarde"


# --- Límites por endpoint ------------------------------------------------------------------


async def test_login_allows_5_attempts_per_minute_per_ip(client: AsyncClient) -> None:
    for attempt in range(5):
        body = {"email": f"user{attempt}@example.com", "password": PASSWORD}
        assert (await client.post(f"{AUTH}/login", json=body)).status_code == 401

    response = await client.post(
        f"{AUTH}/login", json={"email": "otro@example.com", "password": PASSWORD}
    )

    assert_rate_limited(response)


async def test_login_allows_5_attempts_per_minute_per_email(limited_app: FastAPI) -> None:
    # Cada intento desde una IP distinta: solo el límite por email puede frenarlos.
    for attempt in range(5):
        async with client_from(limited_app, f"203.0.113.{attempt + 1}") as c:
            assert (await c.post(f"{AUTH}/login", json=LOGIN_BODY)).status_code == 401

    async with client_from(limited_app, "198.51.100.7") as c:
        response = await c.post(f"{AUTH}/login", json=LOGIN_BODY)

    assert_rate_limited(response)


async def test_login_email_limit_ignores_case(limited_app: FastAPI) -> None:
    for attempt, email in enumerate(["ana@example.com", "ANA@example.com", "Ana@Example.com"] * 2):
        async with client_from(limited_app, f"203.0.113.{attempt + 1}") as c:
            last = await c.post(f"{AUTH}/login", json={"email": email, "password": PASSWORD})

    assert_rate_limited(last)


async def test_invalid_bodies_also_count(client: AsyncClient) -> None:
    for _ in range(5):
        assert (await client.post(f"{AUTH}/login", json={})).status_code == 422

    assert_rate_limited(await client.post(f"{AUTH}/login", json={}))


async def test_register_allows_3_per_minute_per_ip(client: AsyncClient) -> None:
    for _ in range(3):
        response = await client.post(f"{AUTH}/register", json={"email": "x"})
        assert response.status_code == 422

    assert_rate_limited(await client.post(f"{AUTH}/register", json={"email": "x"}))


async def test_refresh_allows_10_per_minute_per_ip(client: AsyncClient) -> None:
    for _ in range(10):
        assert (await client.post(f"{AUTH}/refresh")).status_code == 401

    assert_rate_limited(await client.post(f"{AUTH}/refresh"))


async def test_api_allows_120_requests_per_minute_per_user(client: AsyncClient) -> None:
    for _ in range(120):
        assert (await client.get(f"{AUTH}/me")).status_code == 200

    assert_rate_limited(await client.get(f"{AUTH}/me"))


async def test_api_limit_is_per_user_not_per_ip(limited_app: FastAPI, user: User) -> None:
    async with client_from(limited_app) as c:
        for _ in range(120):
            await c.get(f"{AUTH}/me")
        other = User(
            id=uuid4(),
            email="beto@example.com",
            hashed_password="no-se-usa",
            role=UserRole.USER,
            created_at=datetime.now(UTC),
        )
        limited_app.dependency_overrides[get_current_user] = lambda: other

        response = await c.get(f"{AUTH}/me")

    assert response.status_code == 200


async def test_limits_are_per_ip(limited_app: FastAPI) -> None:
    async with client_from(limited_app, "203.0.113.10") as first:
        for _ in range(3):
            await first.post(f"{AUTH}/register", json={})
        assert (await first.post(f"{AUTH}/register", json={})).status_code == 429

    async with client_from(limited_app, "203.0.113.11") as second:
        assert (await second.post(f"{AUTH}/register", json={})).status_code == 422


async def test_x_forwarded_for_is_not_trusted_by_the_app(client: AsyncClient) -> None:
    # Si la app leyera la cabecera, cada petición "vendría" de una IP nueva y nunca se frenaría.
    for attempt in range(3):
        headers = {"X-Forwarded-For": f"198.51.100.{attempt}"}
        await client.post(f"{AUTH}/register", json={}, headers=headers)

    response = await client.post(
        f"{AUTH}/register", json={}, headers={"X-Forwarded-For": "198.51.100.99"}
    )

    assert response.status_code == 429


async def test_limits_do_not_affect_public_infrastructure(client: AsyncClient) -> None:
    for _ in range(200):
        assert (await client.get("/health")).status_code == 200


# --- Claves ---------------------------------------------------------------------------------


async def test_keys_never_contain_emails_or_passwords(limited_app: FastAPI) -> None:
    storage = MemoryStorage()
    limited_app.state.rate_limiter = AppRateLimiter(storage)
    async with client_from(limited_app) as c:
        await c.post(f"{AUTH}/login", json=LOGIN_BODY)

    keys = " ".join(storage.events)
    assert EMAIL not in keys
    assert PASSWORD not in keys
    assert email_key(EMAIL) in keys
    assert "203.0.113.10" in keys


# --- Redis caído ----------------------------------------------------------------------------


@pytest.fixture
def redis_down(limited_app: FastAPI) -> FastAPI:
    # Puerto 1: nadie escucha, la conexión falla al momento.
    settings = Settings(_env_file=None, redis_url="redis://:pw-falsa@127.0.0.1:1/0")  # type: ignore[arg-type]
    limited_app.state.rate_limiter = AppRateLimiter(create_storage(settings))
    return limited_app


@pytest.mark.parametrize(
    ("path", "body"),
    [("/login", LOGIN_BODY), ("/register", LOGIN_BODY), ("/refresh", None)],
)
async def test_auth_fails_closed_when_redis_is_down(
    redis_down: FastAPI, path: str, body: dict[str, str] | None
) -> None:
    async with client_from(redis_down) as c:
        response = await c.post(f"{AUTH}{path}", json=body)

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["retry-after"] == "30"
    assert response.json()["detail"] == "Servicio no disponible temporalmente"


async def test_api_fails_open_when_redis_is_down(redis_down: FastAPI, user: User) -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)

    async with client_from(redis_down) as c:
        response = await c.get(f"{AUTH}/me")

    assert response.status_code == 200
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    [unavailable] = [e for e in events if e["event"] == "rate_limit_unavailable"]
    assert unavailable["scope"] == "api"
    assert unavailable["fail_open"] is True
    # Solo el ámbito: ni la contraseña de Redis ni el resto de la clave (id de usuario, IP).
    assert "pw-falsa" not in stream.getvalue()
    assert str(user.id) not in stream.getvalue()
    assert "203.0.113.10" not in stream.getvalue()


async def test_exceeded_limit_is_logged_without_the_key(client: AsyncClient) -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)

    for _ in range(6):
        await client.post(f"{AUTH}/login", json=LOGIN_BODY)

    output = stream.getvalue()
    assert '"event": "rate_limit_exceeded"' in output
    assert EMAIL not in output
    assert email_key(EMAIL) not in output
