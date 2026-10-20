"""Denegar por defecto (AGENTS.md §8.9): toda ruta fuera de la lista blanca exige un token.

Las rutas se recorren desde el esquema OpenAPI y no desde `app.routes`: desde FastAPI 0.143,
`app.routes` guarda cada router incluido como un solo objeto, sin sus rutas. Una ruta con
`include_in_schema=False` no saldría en el esquema; por eso `app/` tiene prohibido usarlo
(`test_no_route_hides_from_the_schema`).
"""

import ast
import re
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.routing import Route

from app.core.auth import UNAUTHORIZED_DETAIL
from app.core.config import Settings
from app.main import create_app
from app.routers import auth

APP_DIR = Path(__file__).resolve().parent.parent / "app"

# Lista blanca vigente (§8.9): infraestructura, documentación y la entrada a la autenticación.
# Añadir aquí una ruta es abrirla a Internet: tiene que justificarse en el PR.
PUBLIC_ROUTES = {
    ("GET", "/health"),
    ("GET", "/openapi.json"),
    ("GET", "/docs"),
    ("GET", "/docs/oauth2-redirect"),
    ("GET", "/redoc"),
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/refresh"),
}

# Con forma de JWT (tres partes) pero sin firma válida.
FORGED_BEARER = "cabecera.cuerpo.firma"


def all_routes(app: FastAPI) -> set[tuple[str, str]]:
    routes = {
        (method, path)
        for path, operations in app.openapi()["paths"].items()
        for method in (op.upper() for op in operations)
    }
    for route in app.routes:
        if isinstance(route, Route) and route.methods:
            routes |= {(method, route.path) for method in route.methods if method != "HEAD"}
    return routes


def concrete(path: str) -> str:
    """Sustituye los parámetros de ruta (`{id}`) por un valor válido para la mayoría de tipos."""
    return re.sub(r"\{[^}]+\}", "00000000-0000-0000-0000-000000000000", path)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        yield c


def protected_routes() -> list[tuple[str, str]]:
    app = create_app(Settings(_env_file=None, app_env="test"))
    return sorted(all_routes(app) - PUBLIC_ROUTES)


def test_the_whitelist_only_lists_existing_routes(app: FastAPI) -> None:
    # Si se borra o renombra una ruta pública, la lista blanca no puede quedarse abriendo otra.
    assert all_routes(app) >= PUBLIC_ROUTES


def test_there_are_protected_routes_to_check() -> None:
    # Sin esto, un fallo al recorrer las rutas dejaría el test siguiente en verde sin probar nada.
    assert ("GET", "/api/v1/auth/me") in protected_routes()


@pytest.mark.parametrize(
    "auth_header", [None, f"Bearer {FORGED_BEARER}"], ids=["sin_token", "falso"]
)
@pytest.mark.parametrize(("method", "path"), protected_routes())
async def test_every_route_outside_the_whitelist_requires_a_token(
    client: AsyncClient, method: str, path: str, auth_header: str | None
) -> None:
    headers = {"Authorization": auth_header} if auth_header else {}

    response = await client.request(method, concrete(path), headers=headers, json={})

    assert response.status_code == 401, f"{method} {path} responde sin token"
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    # Sin detalles internos: el mismo cuerpo para cualquier ruta y motivo.
    assert set(body) == {"type", "title", "status", "detail", "instance", "request_id"}
    assert body["detail"] == UNAUTHORIZED_DETAIL


@pytest.mark.parametrize(("method", "path"), sorted(PUBLIC_ROUTES))
async def test_whitelisted_routes_never_ask_for_a_token(
    client: AsyncClient, method: str, path: str
) -> None:
    response = await client.request(method, path, json={})

    # Pueden responder 4xx (datos inválidos, sin cookie de refresh), pero nunca "No autenticado".
    assert response.status_code < 500
    if response.headers["content-type"] == "application/problem+json":
        assert response.json()["detail"] != UNAUTHORIZED_DETAIL


@pytest.fixture
def unguarded_probe(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Una ruta nueva que se "olvida" de pedir autenticación, en un router protegido real.

    La única protección posible es la del router `/api/v1` de `app/main.py`.
    """
    monkeypatch.setattr(auth.router, "routes", list(auth.router.routes))

    @auth.router.get("/_probe")
    async def forgot_to_ask_for_a_user() -> dict[str, str]:
        return {"leak": "datos"}

    yield


async def test_a_new_route_without_its_own_auth_is_still_protected(
    app_settings: Settings, unguarded_probe: None
) -> None:
    app = create_app(app_settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        response = await c.get("/api/v1/auth/_probe")

    assert response.status_code == 401
    assert "datos" not in response.text


def test_no_route_hides_from_the_schema() -> None:
    offenders = [
        f"{path.relative_to(APP_DIR.parent)}:{node.lineno}"
        for path in APP_DIR.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.keyword) and node.arg == "include_in_schema"
    ]

    assert offenders == [], "Una ruta fuera del esquema escaparía del test de denegar por defecto"
