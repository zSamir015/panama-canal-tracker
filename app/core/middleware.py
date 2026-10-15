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
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import REQUEST_ID_HEADER, problem_response

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
