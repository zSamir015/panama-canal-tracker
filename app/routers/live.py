"""WebSocket `/ws/live` (tarea 4.2, docs/API_DESIGN.md).

Orden de una conexión:

1. **Origin** de `CORS_ORIGINS` o se rechaza el handshake (CORS no protege los WebSockets).
2. **Auth** en el primer mensaje, en menos de 5 s: `{"type": "auth", "token": ...}`. El token
   nunca va en la URL (acabaría en los logs del proxy). Si falla, cierre `4401`.
3. **Límite** de conexiones por usuario (`4429` si se supera).
4. Bucle: `subscribe` con el viewport → snapshot; cada segundo, `update`/`remove` con lo nuevo.

Códigos de cierre: `1008` origen no permitido · `1009` mensaje de más de 4 KB · `1011` error
interno · `1013` el cliente no lee (backpressure) · `4400` mensaje inválido · `4401` sin auth
válida · `4429` demasiadas conexiones o mensajes.

Nunca se registran el token ni el contenido de los mensajes del cliente: solo el motivo.
"""

import asyncio
import contextlib
import time
import uuid
from collections import deque
from collections.abc import Sequence
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, WebSocket
from pydantic import BaseModel, ValidationError
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.core.config import Settings
from app.core.db import SessionFactory
from app.schemas.live import (
    MAX_VESSELS_PER_MESSAGE,
    AuthMessage,
    LiveRemove,
    LiveSnapshot,
    LiveUpdate,
    client_message_adapter,
)
from app.services.live import (
    ClientView,
    ConnectionLimiter,
    LiveAuthError,
    LiveHub,
    LiveUnavailableError,
    authenticate,
    snapshot,
)

AUTH_TIMEOUT_SECONDS = 5.0
FLUSH_INTERVAL_SECONDS = 1.0
# Si un envío tarda más que esto, el cliente no está leyendo: se cierra en vez de esperarle.
SEND_TIMEOUT_SECONDS = 10.0
HEARTBEAT_SECONDS = 30.0
MAX_CLIENT_MESSAGE_BYTES = 4 * 1024
# Mensajes del cliente por ventana: mover el mapa manda un `subscribe` por gesto, no cientos.
MAX_CLIENT_MESSAGES = 20
CLIENT_MESSAGES_WINDOW_SECONDS = 10.0

CLOSE_POLICY = 1008
CLOSE_TOO_BIG = 1009
CLOSE_INTERNAL = 1011
CLOSE_TRY_AGAIN = 1013
CLOSE_INVALID = 4400
CLOSE_UNAUTHORIZED = 4401
CLOSE_TOO_MANY = 4429

router = APIRouter()
logger = structlog.get_logger(__name__)


class _Close(Exception):  # noqa: N818
    """Termina la conexión con este código y motivo (el motivo va al log, no al cliente)."""

    def __init__(self, code: int, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(reason)


class _Disconnected(Exception):  # noqa: N818
    """El cliente cerró la conexión."""


@router.websocket("/ws/live")
async def live(websocket: WebSocket) -> None:
    settings: Settings = websocket.app.state.settings
    origin = websocket.headers.get("origin")
    if origin is None or origin not in settings.cors_origins:
        # Antes de aceptar: el navegador recibe un 403 en el handshake.
        logger.warning("ws_origin_rejected", has_origin=origin is not None)
        await websocket.close(code=CLOSE_POLICY)
        return
    await websocket.accept()

    connection_id = uuid.uuid4().hex
    log = logger.bind(connection_id=connection_id)
    limiter: ConnectionLimiter = websocket.app.state.ws_limiter
    user_id: str | None = None
    acquired = False
    try:
        user_id = await _authenticate(websocket, settings, websocket.app.state.session_factory)
        log = log.bind(user_id=user_id)
        acquired = await limiter.acquire(user_id, connection_id)
        if not acquired:
            raise _Close(CLOSE_TOO_MANY, "too_many_connections")
        log.info("ws_connected")
        await _serve(websocket, user_id, connection_id, limiter)
    except _Close as close:
        log.info("ws_closed", code=close.code, reason=close.reason)
        await _close(websocket, close.code)
    except _Disconnected:
        log.info("ws_closed", code=None, reason="client_disconnected")
    finally:
        if acquired and user_id is not None:
            await limiter.release(user_id, connection_id)


async def _authenticate(websocket: WebSocket, settings: Settings, sessions: SessionFactory) -> str:
    try:
        text = await asyncio.wait_for(_receive_text(websocket), timeout=AUTH_TIMEOUT_SECONDS)
    except TimeoutError:
        raise _Close(CLOSE_UNAUTHORIZED, "auth_timeout") from None
    try:
        message = client_message_adapter.validate_json(text)
    except ValidationError:
        raise _Close(CLOSE_UNAUTHORIZED, "auth_invalid_message") from None
    if not isinstance(message, AuthMessage):
        raise _Close(CLOSE_UNAUTHORIZED, "auth_expected")
    try:
        return await authenticate(message.token, settings, sessions)
    except LiveAuthError as error:
        raise _Close(CLOSE_UNAUTHORIZED, error.reason) from None
    except LiveUnavailableError:
        raise _Close(CLOSE_INTERNAL, "auth_unavailable") from None


async def _serve(
    websocket: WebSocket, user_id: str, connection_id: str, limiter: ConnectionLimiter
) -> None:
    hub: LiveHub = websocket.app.state.live_hub
    view = ClientView()
    send_lock = asyncio.Lock()
    hub.register(view)
    tasks = [
        asyncio.create_task(_read(websocket, view, send_lock)),
        asyncio.create_task(_flush(websocket, view, send_lock)),
        asyncio.create_task(_heartbeat(limiter, user_id, connection_id)),
    ]
    try:
        # La primera que termine (desconexión, cierre o error) acaba con la conexión.
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        hub.unregister(view)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _read(websocket: WebSocket, view: ClientView, send_lock: asyncio.Lock) -> None:
    sessions: SessionFactory = websocket.app.state.session_factory
    recent: deque[float] = deque()
    while True:
        text = await _receive_text(websocket)
        now = time.monotonic()
        recent.append(now)
        while recent and recent[0] < now - CLIENT_MESSAGES_WINDOW_SECONDS:
            recent.popleft()
        if len(recent) > MAX_CLIENT_MESSAGES:
            raise _Close(CLOSE_TOO_MANY, "too_many_messages")
        try:
            message = client_message_adapter.validate_json(text)
        except ValidationError:
            raise _Close(CLOSE_INVALID, "invalid_message") from None
        if isinstance(message, AuthMessage):
            raise _Close(CLOSE_INVALID, "already_authenticated")
        viewport = message.viewport()
        async with send_lock:
            # Primero el viewport: lo que publique el worker mientras se consulta la base queda
            # pendiente y sale detrás del snapshot (es más nuevo).
            view.reset(viewport, [])
            try:
                vessels = await snapshot(sessions, viewport, now=datetime.now(UTC))
            except LiveUnavailableError:
                raise _Close(CLOSE_INTERNAL, "snapshot_failed") from None
            view.add_known(vessels)
            await _send(websocket, LiveSnapshot(vessels=vessels))


async def _flush(websocket: WebSocket, view: ClientView, send_lock: asyncio.Lock) -> None:
    while True:
        await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
        async with send_lock:
            updates, removes = view.drain()
            for chunk in _chunks(updates, MAX_VESSELS_PER_MESSAGE):
                await _send(websocket, LiveUpdate(vessels=list(chunk)))
            if removes:
                await _send(websocket, LiveRemove(mmsi=removes))


async def _heartbeat(limiter: ConnectionLimiter, user_id: str, connection_id: str) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        await limiter.refresh(user_id, connection_id)


async def _receive_text(websocket: WebSocket) -> str:
    message = await websocket.receive()
    if message["type"] == "websocket.disconnect":
        raise _Disconnected
    text = message.get("text")
    if text is None:
        raise _Close(CLOSE_INVALID, "binary_message")
    if len(text.encode()) > MAX_CLIENT_MESSAGE_BYTES:
        raise _Close(CLOSE_TOO_BIG, "message_too_big")
    return str(text)


async def _send(websocket: WebSocket, message: BaseModel) -> None:
    try:
        await asyncio.wait_for(
            websocket.send_text(message.model_dump_json()), timeout=SEND_TIMEOUT_SECONDS
        )
    except TimeoutError:
        raise _Close(CLOSE_TRY_AGAIN, "slow_client") from None
    except (WebSocketDisconnect, RuntimeError):
        raise _Disconnected from None


async def _close(websocket: WebSocket, code: int) -> None:
    if websocket.application_state == WebSocketState.DISCONNECTED:
        return
    with contextlib.suppress(RuntimeError, WebSocketDisconnect):
        await websocket.close(code=code)


def _chunks[T](items: Sequence[T], size: int) -> list[Sequence[T]]:
    return [items[start : start + size] for start in range(0, len(items), size)]
