"""Respuestas de error `application/problem+json` (RFC 9457, AGENTS.md §3 y §8.9).

Todas las respuestas de error de la API tienen la misma forma:

    {"type": "about:blank", "title": "Not Found", "status": 404,
     "detail": "Recurso no encontrado", "instance": "/ruta", "request_id": "..."}

Los errores no controlados (500) nunca devuelven el mensaje ni la traza de la excepción: eso va al
log, junto con el `request_id` que también recibe el cliente, para poder buscarlo.
"""

from collections.abc import Mapping
from http import HTTPStatus
from typing import Any, cast

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

PROBLEM_JSON = "application/problem+json"
REQUEST_ID_HEADER = "X-Request-ID"

# Mensajes `detail` en español para los errores que genera el framework (rutas, métodos...).
DEFAULT_DETAILS = {
    HTTPStatus.BAD_REQUEST: "Petición inválida",
    HTTPStatus.NOT_FOUND: "Recurso no encontrado",
    HTTPStatus.METHOD_NOT_ALLOWED: "Método no permitido",
    HTTPStatus.UNPROCESSABLE_ENTITY: "La petición contiene datos inválidos",
    HTTPStatus.INTERNAL_SERVER_ERROR: "Error interno del servidor",
}


class ProblemResponse(JSONResponse):
    media_type = PROBLEM_JSON


def request_id_from_scope(scope: Scope) -> str:
    """Devuelve el id que `RequestIdMiddleware` asignó a la petición."""
    return str(scope.get("state", {}).get("request_id", ""))


def problem_response(
    status_code: int,
    *,
    scope: Scope,
    detail: str | None = None,
    headers: Mapping[str, str] | None = None,
    **extensions: Any,
) -> ProblemResponse:
    status = HTTPStatus(status_code)
    request_id = request_id_from_scope(scope)
    content = {
        "type": "about:blank",
        "title": status.phrase,
        "status": status.value,
        "detail": detail or DEFAULT_DETAILS.get(status, status.phrase),
        "instance": scope["path"],
        "request_id": request_id,
        **extensions,
    }
    # El 500 lo envía Starlette por fuera de los middlewares: la cabecera se pone aquí también.
    return ProblemResponse(
        content,
        status_code=status.value,
        headers={**(headers or {}), REQUEST_ID_HEADER: request_id},
    )


async def http_exception_handler(request: Request, exc: Exception) -> ProblemResponse:
    # Starlette tipa todos los handlers con `Exception`; solo llama a este con HTTPException.
    exc = cast(StarletteHTTPException, exc)
    # Sin `detail` propio, Starlette usa la frase en inglés del código ("Not Found").
    detail = None if exc.detail == HTTPStatus(exc.status_code).phrase else str(exc.detail)
    return problem_response(
        exc.status_code, scope=request.scope, detail=detail, headers=exc.headers
    )


async def validation_exception_handler(request: Request, exc: Exception) -> ProblemResponse:
    exc = cast(RequestValidationError, exc)
    # Solo ubicación, mensaje y tipo: el valor recibido (`input`) puede ser una contraseña.
    errors = [
        {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]
    return problem_response(HTTPStatus.UNPROCESSABLE_ENTITY, scope=request.scope, errors=errors)


async def unhandled_exception_handler(request: Request, exc: Exception) -> ProblemResponse:
    # `request_id` llega al log por contextvars (lo enlaza RequestIdMiddleware).
    structlog.get_logger(__name__).error("unhandled_error", exc_info=exc)
    return problem_response(HTTPStatus.INTERNAL_SERVER_ERROR, scope=request.scope)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    # Con `Exception`, Starlette lo usa en ServerErrorMiddleware para cualquier error no controlado.
    app.add_exception_handler(Exception, unhandled_exception_handler)
