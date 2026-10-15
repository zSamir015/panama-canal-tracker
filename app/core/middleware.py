"""Middlewares ASGI de la API.

Son middlewares ASGI "puros" (no `BaseHTTPMiddleware`): se ejecutan en la misma tarea que el
endpoint, así que las contextvars que enlazan (el `request_id` de los logs) siguen visibles en el
handler de errores 500.
"""

import uuid
from http import HTTPStatus

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import problem_response
from app.core.headers import REQUEST_ID_HEADER, security_headers

MAX_BODY_BYTES = 64 * 1024  # AGENTS.md §8.6


class RequestIdMiddleware:
    """Asigna un id único a cada petición: va en la cabecera `X-Request-ID` y en cada log.

    El id siempre se genera aquí; uno enviado por el cliente se ignora para que nadie pueda
    escribir valores arbitrarios en los logs.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        # Cada petición corre en su propia tarea; se limpia por si alguna contextvar quedó enlazada.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        await self.app(scope, receive, send_with_request_id)


class SecurityHeadersMiddleware:
    """Añade las cabeceras de seguridad de AGENTS.md §8.11 a todas las respuestas."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers_to_add = security_headers(scope["path"])

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in headers_to_add.items():
                    headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)


class HardenedCORSMiddleware(CORSMiddleware):
    """CORS de Starlette, pero un preflight rechazado responde `problem+json` sin la política.

    Starlette responde texto plano e incluye igualmente `Access-Control-Allow-Methods`,
    `-Headers` y `-Credentials`: no hace falta anunciar la política a un origen no autorizado.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] == "OPTIONS":
            request_headers = Headers(scope=scope)
            # Misma condición que usa Starlette para reconocer un preflight.
            if "origin" in request_headers and "access-control-request-method" in request_headers:
                response = self.preflight_response(request_headers=request_headers)
                if response.status_code != HTTPStatus.OK:
                    response = problem_response(
                        HTTPStatus.BAD_REQUEST,
                        scope=scope,
                        detail="Petición CORS no permitida",
                        headers={"Vary": response.headers["vary"]},
                    )
                await response(scope, receive, send)
                return

        await super().__call__(scope, receive, send)


class BodySizeLimitMiddleware:
    """Rechaza con 413 los bodies de más de `max_bytes`.

    Se comprueba `Content-Length` antes de leer nada y, como el cliente puede omitirlo
    (transfer-encoding chunked) o mentir, también se cuentan los bytes mientras llegan.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    def _too_large_detail(self) -> str:
        return f"El cuerpo de la petición supera el límite de {self.max_bytes} bytes"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = Headers(scope=scope).get("content-length")
        if content_length is not None:
            if not content_length.isdigit():
                response = problem_response(
                    HTTPStatus.BAD_REQUEST, scope=scope, detail="Cabecera Content-Length inválida"
                )
                await response(scope, receive, send)
                return
            if int(content_length) > self.max_bytes:
                response = problem_response(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    scope=scope,
                    detail=self._too_large_detail(),
                )
                await response(scope, receive, send)
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Debe ser un HTTPException: FastAPI lo deja pasar hasta el handler, pero
                    # cualquier otra excepción al leer el body la convierte en un 400 genérico.
                    raise HTTPException(
                        HTTPStatus.REQUEST_ENTITY_TOO_LARGE, detail=self._too_large_detail()
                    )
            return message

        await self.app(scope, limited_receive, send)
