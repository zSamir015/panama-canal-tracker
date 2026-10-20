"""Endpoints `/api/v1/auth/*` contra la base de test: register → login → me → refresh → logout."""

import io
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from uuid import UUID

import jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import SessionFactory
from app.core.logging import configure_logging
from app.core.security import PasswordCheck, decode_refresh_token
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories.user import UserRepository
from app.services import auth as auth_service

AUTH = "/api/v1/auth"
EMAIL = "ana@example.com"
PASSWORD = "una frase larga de prueba"
OTHER_EMAIL = "beto@example.com"


@pytest.fixture
async def app(migrated: AsyncEngine, db_app: FastAPI) -> AsyncIterator[FastAPI]:
    yield db_app


@pytest.fixture
def sessions(app: FastAPI) -> SessionFactory:
    factory: SessionFactory = app.state.session_factory
    return factory


def new_client(app: FastAPI) -> AsyncClient:
    # https: la cookie es `Secure` y httpx no la devolvería por http.
    return AsyncClient(transport=ASGITransport(app=app), base_url="https://test")


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with new_client(app) as c:
        yield c


async def register(client: AsyncClient, email: str = EMAIL) -> Response:
    return await client.post(f"{AUTH}/register", json={"email": email, "password": PASSWORD})


async def login(client: AsyncClient, email: str = EMAIL, password: str = PASSWORD) -> Response:
    return await client.post(f"{AUTH}/login", json={"email": email, "password": password})


def bearer(response: Response) -> dict[str, str]:
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def refresh_cookie(response: Response) -> SimpleCookie:
    cookie: SimpleCookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    return cookie


def use_refresh_cookie(client: AsyncClient, token: str) -> None:
    """Deja `token` como única cookie del cliente, como si el navegador la tuviera guardada."""
    client.cookies.clear()
    client.cookies.set("refresh_token", token, path="/api/v1/auth")


async def refresh_with(client: AsyncClient, token: str) -> Response:
    use_refresh_cookie(client, token)
    return await client.post(f"{AUTH}/refresh")


# --- register ------------------------------------------------------------------------------


async def test_register_creates_a_user_with_role_user(client: AsyncClient) -> None:
    response = await register(client, "Ana@Example.com")

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "email", "role", "created_at"}
    assert body["email"] == "ana@example.com"
    assert body["role"] == "user"
    UUID(body["id"])
    assert response.headers["cache-control"] == "no-store"


async def test_register_never_returns_the_password_or_hash(client: AsyncClient) -> None:
    response = await register(client)

    assert PASSWORD not in response.text
    assert "$argon2" not in response.text
    assert "password" not in response.text


async def test_register_rejects_a_role_in_the_body(
    client: AsyncClient, sessions: SessionFactory
) -> None:
    response = await client.post(
        f"{AUTH}/register", json={"email": EMAIL, "password": PASSWORD, "role": "admin"}
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["type"] == "extra_forbidden"
    async with sessions() as session:
        assert await UserRepository(session).get_by_email(EMAIL) is None


@pytest.mark.parametrize(
    "body",
    [
        {"email": "no-es-un-email", "password": PASSWORD},
        {"email": EMAIL, "password": "corta"},
        {"email": EMAIL, "password": "a" * 129},
        {"email": EMAIL, "password": 123456789012},
        {"email": EMAIL},
        {},
    ],
    ids=["email", "corta", "larga", "no_string", "sin_password", "vacio"],
)
async def test_register_validates_the_body(client: AsyncClient, body: dict[str, object]) -> None:
    response = await client.post(f"{AUTH}/register", json=body)

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    # El 422 nunca devuelve el valor recibido (podría ser la contraseña).
    assert "input" not in response.json()["errors"][0]


async def test_register_duplicate_email_in_any_case_is_409(client: AsyncClient) -> None:
    await register(client)

    response = await register(client, "ANA@example.com")

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["detail"] == "Ya existe una cuenta con ese email"


# --- login ---------------------------------------------------------------------------------


async def test_login_returns_an_access_token_and_sets_the_refresh_cookie(
    app: FastAPI, client: AsyncClient
) -> None:
    await register(client)

    response = await login(client, "ANA@example.com")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in"}
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == app.state.settings.access_token_expire_minutes * 60
    assert response.headers["cache-control"] == "no-store"

    morsel = refresh_cookie(response)["refresh_token"]
    assert morsel.value not in response.text  # el refresh nunca va en el cuerpo
    assert morsel["httponly"] is True
    assert morsel["secure"] is True
    assert morsel["samesite"] == "strict"
    assert morsel["path"] == "/api/v1/auth"
    assert int(morsel["max-age"]) == pytest.approx(
        app.state.settings.refresh_token_expire_days * 86400, abs=5
    )


async def test_access_token_from_login_opens_me(client: AsyncClient) -> None:
    registered = (await register(client)).json()

    response = await client.get(f"{AUTH}/me", headers=bearer(await login(client)))

    assert response.status_code == 200
    assert response.json() == registered


async def test_wrong_password_and_unknown_email_get_the_same_401(client: AsyncClient) -> None:
    await register(client)

    wrong_password = await login(client, EMAIL, "otra frase larga cualquiera")
    unknown_email = await login(client, "nadie@example.com", PASSWORD)

    for response in (wrong_password, unknown_email):
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert "set-cookie" not in response.headers

    def comparable(response: Response) -> dict[str, object]:
        body = response.json()
        del body["request_id"]
        return body

    assert comparable(wrong_password) == comparable(unknown_email)


async def test_login_upgrades_a_hash_with_old_parameters(
    client: AsyncClient, sessions: SessionFactory
) -> None:
    old = PasswordHash((Argon2Hasher(time_cost=1, memory_cost=8192, parallelism=1),))
    async with sessions() as session:
        await session.execute(
            User.__table__.insert().values(email=EMAIL, hashed_password=old.hash(PASSWORD))
        )
        await session.commit()

    assert (await login(client)).status_code == 200

    async with sessions() as session:
        user = await UserRepository(session).get_by_email(EMAIL)
    assert user is not None
    assert "m=65536,t=3,p=4" in user.hashed_password


# --- refresh -------------------------------------------------------------------------------


async def test_refresh_rotates_the_cookie_and_issues_a_new_access_token(
    client: AsyncClient, sessions: SessionFactory
) -> None:
    await register(client)
    first = refresh_cookie(await login(client))["refresh_token"].value

    response = await client.post(f"{AUTH}/refresh")

    assert response.status_code == 200
    second = refresh_cookie(response)["refresh_token"].value
    assert second != first
    assert (await client.get(f"{AUTH}/me", headers=bearer(response))).status_code == 200
    async with sessions() as session:
        rows = (await session.execute(select(RefreshToken))).scalars().all()
    rotated = [row for row in rows if row.revoked_at is not None]
    alive = [row for row in rows if row.revoked_at is None]
    assert len(rotated) == 1 and len(alive) == 1
    assert rotated[0].replaced_by_jti == alive[0].jti
    assert rotated[0].family_id == alive[0].family_id


async def test_refresh_without_cookie_is_401(client: AsyncClient) -> None:
    response = await client.post(f"{AUTH}/refresh")

    assert response.status_code == 401
    assert response.json()["detail"] == "Sesión inválida o caducada"


async def test_reusing_a_rotated_refresh_revokes_the_whole_session(
    client: AsyncClient, sessions: SessionFactory
) -> None:
    await register(client)
    stolen = refresh_cookie(await login(client))["refresh_token"].value
    legit = refresh_cookie(await client.post(f"{AUTH}/refresh"))["refresh_token"].value

    reuse = await refresh_with(client, stolen)
    after = await refresh_with(client, legit)

    assert reuse.status_code == 401
    assert after.status_code == 401  # también cae la rama legítima: la sesión entera
    async with sessions() as session:
        alive = await session.execute(select(RefreshToken).where(RefreshToken.revoked_at.is_(None)))
    assert alive.scalars().all() == []


async def test_reuse_only_revokes_that_session(client: AsyncClient) -> None:
    await register(client)
    laptop = refresh_cookie(await login(client))["refresh_token"].value
    phone = refresh_cookie(await login(client))["refresh_token"].value
    await refresh_with(client, laptop)

    assert (await refresh_with(client, laptop)).status_code == 401  # reutilización
    assert (await refresh_with(client, phone)).status_code == 200  # otra sesión, intacta


async def test_access_token_is_not_accepted_as_refresh(client: AsyncClient) -> None:
    await register(client)
    access = (await login(client)).json()["access_token"]

    assert (await refresh_with(client, access)).status_code == 401


async def test_refresh_token_is_not_accepted_as_access(client: AsyncClient) -> None:
    await register(client)
    refresh = refresh_cookie(await login(client))["refresh_token"].value

    response = await client.get(f"{AUTH}/me", headers={"Authorization": f"Bearer {refresh}"})

    assert response.status_code == 401


async def test_refresh_expired_in_the_database_is_401(
    client: AsyncClient, sessions: SessionFactory
) -> None:
    await register(client)
    await login(client)
    async with sessions() as session:
        await session.execute(
            update(RefreshToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()

    assert (await client.post(f"{AUTH}/refresh")).status_code == 401


async def test_refresh_of_a_deleted_user_is_401(
    client: AsyncClient, sessions: SessionFactory
) -> None:
    await register(client)
    await login(client)
    async with sessions() as session:
        await session.execute(delete(User))
        await session.commit()

    assert (await client.post(f"{AUTH}/refresh")).status_code == 401


async def test_oversized_refresh_cookie_is_rejected(client: AsyncClient) -> None:
    response = await refresh_with(client, "a" * 5000)

    assert response.status_code == 422


# --- logout --------------------------------------------------------------------------------


async def test_logout_revokes_the_session_and_clears_the_cookie(client: AsyncClient) -> None:
    await register(client)
    logged_in = await login(client)
    token = refresh_cookie(logged_in)["refresh_token"].value

    response = await client.post(f"{AUTH}/logout", headers=bearer(logged_in))

    assert response.status_code == 204
    cleared = refresh_cookie(response)["refresh_token"]
    assert cleared.value == ""
    assert cleared["max-age"] == "0"
    assert cleared["path"] == "/api/v1/auth"
    assert (await refresh_with(client, token)).status_code == 401


async def test_logout_requires_an_access_token(client: AsyncClient) -> None:
    assert (await client.post(f"{AUTH}/logout")).status_code == 401


async def test_logout_with_someone_elses_refresh_does_not_revoke_it(app: FastAPI) -> None:
    # Acceso cruzado: B manda la cookie de A con su propio access token.
    async with new_client(app) as ana, new_client(app) as beto:
        await register(ana)
        await register(beto, OTHER_EMAIL)
        ana_refresh = refresh_cookie(await login(ana))["refresh_token"].value
        beto_login = await login(beto, OTHER_EMAIL)

        use_refresh_cookie(beto, ana_refresh)
        response = await beto.post(f"{AUTH}/logout", headers=bearer(beto_login))

        assert response.status_code == 204
        assert (await refresh_with(ana, ana_refresh)).status_code == 200


# --- me ------------------------------------------------------------------------------------


async def test_me_without_token_is_401(client: AsyncClient) -> None:
    assert (await client.get(f"{AUTH}/me")).status_code == 401


async def test_me_only_ever_returns_the_token_owner(app: FastAPI) -> None:
    async with new_client(app) as ana, new_client(app) as beto:
        ana_id = (await register(ana)).json()["id"]
        beto_id = (await register(beto, OTHER_EMAIL)).json()["id"]

        as_ana = await ana.get(f"{AUTH}/me", headers=bearer(await login(ana)))
        as_beto = await beto.get(f"{AUTH}/me", headers=bearer(await login(beto, OTHER_EMAIL)))

    assert as_ana.json()["id"] == ana_id
    assert as_beto.json()["id"] == beto_id


# --- logs ----------------------------------------------------------------------------------


async def test_full_flow_never_logs_secrets_or_emails(client: AsyncClient) -> None:
    stream = io.StringIO()
    configure_logging("DEBUG", stream=stream)

    await register(client)
    await login(client, EMAIL, "contraseña equivocada larga")
    logged_in = await login(client)
    refreshed = await client.post(f"{AUTH}/refresh")
    await client.post(f"{AUTH}/logout", headers=bearer(refreshed))

    output = stream.getvalue()
    secrets = [
        PASSWORD,
        "contraseña equivocada larga",
        logged_in.json()["access_token"],
        refresh_cookie(logged_in)["refresh_token"].value,
        refreshed.json()["access_token"],
        refresh_cookie(refreshed)["refresh_token"].value,
        EMAIL,
        "$argon2id$",
    ]
    for secret in secrets:
        assert secret not in output
    for event in ("user_registered", "login_failed", "login_succeeded", "logout"):
        assert f'"event": "{event}"' in output


async def test_register_race_on_the_same_email_is_409(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Dos registros simultáneos: ambos ven que el email está libre y el INSERT de uno falla.
    await register(client)

    async def not_found(self: UserRepository, email: str) -> None:
        return None

    monkeypatch.setattr(UserRepository, "get_by_email", not_found)

    response = await register(client)

    assert response.status_code == 409


async def test_logout_without_refresh_cookie_still_succeeds(client: AsyncClient) -> None:
    await register(client)
    logged_in = await login(client)
    client.cookies.clear()

    response = await client.post(f"{AUTH}/logout", headers=bearer(logged_in))

    assert response.status_code == 204


async def test_login_of_an_unknown_email_still_verifies_a_hash(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Anti-enumeración: el servicio tiene que pasar por `verify_password` (hash ficticio)
    # también cuando el email no existe, no responder antes.
    calls: list[str | None] = []
    real = auth_service.verify_password

    def spy(password: str, hashed: str | None) -> PasswordCheck:
        calls.append(hashed)
        return real(password, hashed)

    monkeypatch.setattr(auth_service, "verify_password", spy)

    response = await login(client, "nadie@example.com", PASSWORD)

    assert response.status_code == 401
    assert calls == [None]


async def test_refresh_signed_for_another_user_is_401(app: FastAPI, client: AsyncClient) -> None:
    # Defensa en profundidad: aunque alguien tuviera la clave, el `jti` guardado pertenece a Ana
    # y no sirve para emitir tokens a nombre de Beto.
    await register(client)
    beto_id = (await register(client, OTHER_EMAIL)).json()["id"]
    settings = app.state.settings
    ana = decode_refresh_token(refresh_cookie(await login(client))["refresh_token"].value, settings)
    now = datetime.now(UTC)
    forged = jwt.encode(
        {
            "sub": beto_id,
            "iat": now,
            "exp": now + timedelta(days=1),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "jti": str(ana.jti),
            "fam": str(ana.family_id),
            "token_type": "refresh",
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm="HS256",
    )

    assert (await refresh_with(client, forged)).status_code == 401
