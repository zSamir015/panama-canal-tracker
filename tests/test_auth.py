"""Rechazo de tokens en el stack HTTP completo, sin base de datos.

Todos estos casos se rechazan antes de consultar la base: el token se valida primero. Los casos
con un usuario real (403, admin, usuario borrado) están en `tests/integration/test_auth.py`.
"""

import io
import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.core.auth import UNAUTHORIZED_DETAIL
from app.core.config import Settings
from app.core.logging import configure_logging
from app.core.security import create_access_token
from app.main import create_app
from app.routers import admin

ADMIN_PATH = "/api/v1/admin/_test"


@pytest.fixture
def admin_test_route(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Añade una ruta al router de admin real, sin dejarla puesta para otros tests.

    La ruta no declara ninguna dependencia: la protección tiene que venir del router.
    """
    monkeypatch.setattr(admin.router, "routes", list(admin.router.routes))

    @admin.router.get("/_test")
    async def admin_only() -> dict[str, str]:
        return {"ok": "admin"}

    yield


@pytest.fixture
def auth_app(app_settings: Settings, admin_test_route: None) -> FastAPI:
    return create_app(app_settings)


@pytest.fixture
async def client(auth_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=auth_app), base_url="http://test") as c:
        yield c


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def payload(settings: Settings, **overrides: object) -> dict[str, object]:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "sub": str(uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "jti": uuid4().hex,
    }
    return claims | overrides


def bad_tokens(settings: Settings) -> dict[str, dict[str, str]]:
    key = settings.jwt_secret_key.get_secret_value()
    expired, _ = create_access_token(uuid4(), settings, now=datetime.now(UTC) - timedelta(hours=1))
    return {
        "sin_cabecera": {},
        "cabecera_vacia": {"Authorization": ""},
        "esquema_basic": {"Authorization": "Basic dXNlcjpwYXNz"},
        "bearer_sin_token": {"Authorization": "Bearer "},
        "basura": bearer("no-es-un-jwt"),
        "caducado": bearer(expired),
        "firma_invalida": bearer(
            jwt.encode(payload(settings), "otra-clave-de-32-bytes-como-minimo!!", "HS256")
        ),
        "alg_none": bearer(jwt.encode(payload(settings), None, algorithm="none")),
        "audiencia_incorrecta": bearer(jwt.encode(payload(settings, aud="otra"), key, "HS256")),
        "emisor_incorrecto": bearer(jwt.encode(payload(settings, iss="otro"), key, "HS256")),
        "sin_sub": bearer(
            jwt.encode({k: v for k, v in payload(settings).items() if k != "sub"}, key, "HS256")
        ),
    }


# Solo para obtener los nombres de los casos al recolectar los tests.
CASES = list(bad_tokens(Settings(_env_file=None, jwt_secret_key=SecretStr("k" * 32))))


@pytest.mark.parametrize("case", CASES)
async def test_invalid_credentials_get_the_same_401(
    client: AsyncClient, app_settings: Settings, case: str
) -> None:
    response = await client.get(ADMIN_PATH, headers=bad_tokens(app_settings)[case])

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["www-authenticate"] == "Bearer"
    body = response.json()
    assert body["detail"] == UNAUTHORIZED_DETAIL
    # Mismo cuerpo en todos los casos: solo cambia el id de la petición.
    assert set(body) == {"type", "title", "status", "detail", "instance", "request_id"}


async def test_unknown_api_paths_still_return_404(client: AsyncClient) -> None:
    # El 404 de una ruta inexistente no depende del token: no hay ruta a la que proteger.
    response = await client.get("/api/v1/no-existe")

    assert response.status_code == 404


async def test_public_routes_need_no_token(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200


async def test_rejected_token_never_reaches_the_logs(
    client: AsyncClient, app_settings: Settings
) -> None:
    stream = io.StringIO()
    configure_logging("DEBUG", stream=stream)
    tokens = bad_tokens(app_settings)

    for headers in tokens.values():
        await client.get(ADMIN_PATH, headers=headers)

    output = stream.getvalue()
    for headers in tokens.values():
        value = headers.get("Authorization", "").removeprefix("Bearer ").removeprefix("Basic ")
        if value:
            assert value not in output
    events = [json.loads(line) for line in output.splitlines()]
    rejected = [e for e in events if e["event"] == "access_token_rejected"]
    assert {e["reason"] for e in rejected} >= {"ExpiredSignatureError", "InvalidAlgorithmError"}
