"""Worker de ingesta AIS: una única conexión WebSocket con AISStream (tarea 3.3).

ADR-0002 y ADR-0004: AISStream admite **una conexión por API key**, así que solo este proceso se
conecta, nunca la API ni el navegador. El worker:

1. abre el WebSocket y envía la suscripción (bbox del Canal y tipos de mensaje) al instante:
   AISStream cierra la conexión si no llega en 3 segundos;
2. espera la `SubscriptionConfirmation` (AISStream no confirma una suscripción inválida);
3. pasa cada frame por el parser (3.2) y deja los resultados en una cola acotada que vacía el
   writer (3.4, `app/workers/ais_writer.py`) guardándolos en la base por lotes;
4. si la conexión cae, reintenta con backoff exponencial y jitter, de 1 s hasta
   `AIS_RECONNECT_MAX_SECONDS`.

La lectura nunca se bloquea: si el writer no da abasto y la cola se llena, se descartan los
mensajes más antiguos y se cuentan. Para un mapa en vivo vale más la posición nueva que la vieja,
y AISStream desconecta a los clientes que leen despacio.

La API key nunca se registra: ni en los logs propios ni en los de la librería `websockets`, que en
DEBUG escribe cada frame enviado (la suscripción incluida).

Uso: `python -m app.workers.ais_consumer` (con `AISSTREAM_API_KEY` en `.env`; para desarrollar
sin key, `AISSTREAM_URL=ws://127.0.0.1:8765` y `python scripts/ais_simulator.py serve`).
"""

import asyncio
import contextlib
import json
import logging
import random
import signal
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import structlog
from pydantic import SecretStr
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_session_factory
from app.core.logging import configure_logging
from app.services.ais_parser import AisMessageRejected, parse_message
from app.workers.ais_publisher import (
    STATUS_INTERVAL_SECONDS,
    AisPublisher,
    WorkerStatus,
    create_redis,
    worker_status,
)
from app.workers.ais_writer import AisWriter, WriterStats
from app.workers.common import BACKOFF_BASE_SECONDS, AisRecord, backoff_delay

# Área del Canal en el orden de AISStream, [lat, lon] (docs/DATA_SOURCES.md §1).
CANAL_BOUNDING_BOXES: tuple[tuple[tuple[float, float], tuple[float, float]], ...] = (
    ((8.4, -80.2), (9.7, -79.2)),
)
MESSAGE_TYPES = ("PositionReport", "ShipStaticData")

CONFIRMATION_TIMEOUT_SECONDS = 10.0
OPEN_TIMEOUT_SECONDS = 10.0
# Un frame AIS ocupa cientos de bytes; el parser rechaza los de más de 8 KB. Por encima de esto,
# `websockets` corta la conexión antes de reservar memoria para el frame.
MAX_FRAME_BYTES = 64 * 1024
# Cada cuántos descartes por cola llena se avisa en el log (avisar de todos sería otro problema).
DROP_LOG_EVERY = 1000
STATS_LOG_INTERVAL_SECONDS = 60.0

logger = structlog.get_logger(__name__)

# Logger para la librería `websockets`: en DEBUG escribe cada frame enviado, y el de suscripción
# lleva la API key. Este logger nunca baja de INFO, aunque el resto de la app esté en DEBUG.
_websocket_logger = logging.getLogger(f"{__name__}.websocket")
_websocket_logger.setLevel(logging.INFO)


class AisServerError(Exception):
    """AISStream envió `{"error": ...}` (key inválida, suscripción incorrecta...)."""


@dataclass
class ConsumerStats:
    """Estado del worker. La 3.5 lo publicará y la 3.9 lo expondrá en `/admin/ingestion/status`."""

    connections: int = 0
    connected: bool = False
    subscribed: bool = False
    received: int = 0
    queued: int = 0
    ignored: int = 0
    dropped: int = 0
    rejected: Counter[str] = field(default_factory=Counter)
    last_message_at: datetime | None = None
    last_error: str | None = None


class AisConsumer:
    def __init__(
        self,
        *,
        url: str,
        api_key: SecretStr,
        queue: asyncio.Queue[AisRecord],
        reconnect_max_seconds: float = 60.0,
        backoff_base_seconds: float = BACKOFF_BASE_SECONDS,
        confirmation_timeout: float = CONFIRMATION_TIMEOUT_SECONDS,
        bounding_boxes: Sequence[Any] = CANAL_BOUNDING_BOXES,
        rng: random.Random | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._url = url
        self._api_key = api_key
        self._queue = queue
        self._reconnect_max_seconds = reconnect_max_seconds
        self._backoff_base_seconds = backoff_base_seconds
        self._confirmation_timeout = confirmation_timeout
        self._bounding_boxes = bounding_boxes
        self._rng = rng or random.Random()  # noqa: S311 (jitter, no criptografía)
        self._clock = clock
        self._running = False
        self.stats = ConsumerStats()

    def __repr__(self) -> str:
        # Nunca la key: solo el host al que se conecta.
        return f"AisConsumer(host={urlsplit(self._url).hostname!r})"

    def _subscription(self) -> str:
        return json.dumps(
            {
                "APIKey": self._api_key.get_secret_value(),
                "BoundingBoxes": [[list(corner) for corner in box] for box in self._bounding_boxes],
                "FilterMessageTypes": list(MESSAGE_TYPES),
            }
        )

    async def run(self, stop: asyncio.Event) -> None:
        """Mantiene la conexión hasta que `stop` se active."""
        if self._running:
            # Dos bucles con la misma key serían dos conexiones: AISStream lo prohíbe.
            raise RuntimeError("AisConsumer ya está en marcha: una sola conexión por API key")
        self._running = True
        attempt = 0
        host = urlsplit(self._url).hostname
        try:
            while not stop.is_set():
                try:
                    await self._connect_once(stop)
                except (OSError, TimeoutError, WebSocketException, AisServerError) as error:
                    if stop.is_set():
                        break  # el cierre lo pedimos nosotros: no es un error
                    self.stats.last_error = type(error).__name__
                    code = (
                        error.rcvd.code
                        if isinstance(error, ConnectionClosed) and error.rcvd
                        else None
                    )
                    logger.warning(
                        "ais_disconnected", host=host, error=type(error).__name__, code=code
                    )
                else:
                    if not stop.is_set():
                        # El servidor cerró de forma ordenada: también hay que reconectar.
                        logger.warning("ais_disconnected", host=host, error=None, code=None)
                finally:
                    # Una conexión que llegó a confirmar la suscripción reinicia el backoff.
                    if self.stats.subscribed:
                        attempt = 0
                    self.stats.connected = False
                    self.stats.subscribed = False
                if stop.is_set():
                    break
                delay = backoff_delay(
                    attempt,
                    cap=self._reconnect_max_seconds,
                    rng=self._rng,
                    base=self._backoff_base_seconds,
                )
                attempt += 1
                logger.info(
                    "ais_reconnect_scheduled", attempt=attempt, delay_seconds=round(delay, 3)
                )
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=delay)
        finally:
            self._running = False

    async def _connect_once(self, stop: asyncio.Event) -> None:
        async with connect(
            self._url,
            open_timeout=OPEN_TIMEOUT_SECONDS,
            max_size=MAX_FRAME_BYTES,
            logger=_websocket_logger,
            # AISStream recomienda permessage-deflate (y limitará el ancho de banda sin él).
            compression="deflate",
        ) as connection:
            self.stats.connections += 1
            self.stats.connected = True
            logger.info("ais_connected", host=urlsplit(self._url).hostname)
            # Al instante: AISStream cierra si la suscripción no llega en 3 segundos.
            await connection.send(self._subscription())
            closer = asyncio.create_task(self._close_on_stop(connection, stop))
            try:
                await self._read(connection)
            finally:
                closer.cancel()

    @staticmethod
    async def _close_on_stop(connection: ClientConnection, stop: asyncio.Event) -> None:
        await stop.wait()
        await connection.close()

    async def _read(self, connection: ClientConnection) -> None:
        # El primer frame debe llegar pronto: sin confirmación, la suscripción no vale.
        first = await asyncio.wait_for(connection.recv(), timeout=self._confirmation_timeout)
        self._handle(first)
        async for frame in connection:
            self._handle(frame)

    def _handle(self, frame: str | bytes) -> None:
        received_at = self._clock()
        self.stats.received += 1
        try:
            record = parse_message(frame, received_at=received_at)
        except AisMessageRejected as rejection:
            # Se cuenta, no se registra el mensaje: es dato externo no confiable.
            self.stats.rejected[rejection.reason] += 1
            return
        if record is None:
            self._handle_control(frame)
            return
        self.stats.last_message_at = received_at
        self._enqueue(record)

    def _handle_control(self, frame: str | bytes) -> None:
        """Frames que no son datos AIS: la confirmación, errores del servidor y otros tipos."""
        # El parser ya comprobó que es un objeto JSON: solo devuelve None en ese caso.
        data = json.loads(frame)
        if data.get("MessageType") == "SubscriptionConfirmation":
            message = data.get("Message")
            compression = isinstance(message, dict) and message.get("CompressionEnabled") is True
            self.stats.subscribed = True
            logger.info("ais_subscription_confirmed", compression=compression)
            if not compression:
                logger.warning("ais_compression_disabled")
            return
        if "error" in data:
            # El texto viene del servidor: se recorta y se trata como dato, no como formato.
            logger.error("ais_server_error", error=str(data["error"])[:200])
            raise AisServerError
        self.stats.ignored += 1

    def _enqueue(self, record: AisRecord) -> None:
        if self._queue.full():
            # Descarta el más antiguo: la lectura del WebSocket no espera nunca al writer.
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
                self._queue.task_done()
            self.stats.dropped += 1
            if self.stats.dropped == 1 or self.stats.dropped % DROP_LOG_EVERY == 0:
                logger.warning("ais_queue_full", dropped=self.stats.dropped)
        self._queue.put_nowait(record)
        self.stats.queued += 1


# --- Proceso del worker ---------------------------------------------------------------------


def _stats_event(stats: ConsumerStats, writer: WriterStats) -> dict[str, Any]:
    return {
        "connected": stats.connected,
        "received": stats.received,
        "queued": stats.queued,
        "dropped": stats.dropped,
        "ignored": stats.ignored,
        "rejected": dict(stats.rejected),
        "positions_written": writer.positions_written,
        "positions_duplicated": writer.positions_duplicated,
        "rows_rejected_by_db": writer.rows_rejected_by_db,
        "batches_dropped": writer.batches_dropped,
    }


async def _publish_status(
    publisher: AisPublisher, status: Callable[[], WorkerStatus], interval: float
) -> None:
    """Estado del worker en Redis para `/admin/ingestion/status` (3.9)."""
    while True:
        await publisher.publish_status(status())
        await asyncio.sleep(interval)


async def _log_stats(consumer: ConsumerStats, writer: WriterStats, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        logger.info("ais_stats", **_stats_event(consumer, writer))


def _require_api_key(settings: Settings) -> SecretStr:
    key = settings.aisstream_api_key
    if key is None or not key.get_secret_value().strip():
        raise SystemExit(
            "AISSTREAM_API_KEY no está definida. Regístrate en https://aisstream.io o, para "
            "desarrollar sin key, usa AISSTREAM_URL=ws://127.0.0.1:8765 con cualquier valor de key "
            "y python scripts/ais_simulator.py serve"
        )
    return key


async def run_worker(
    settings: Settings,
    stop: asyncio.Event | None = None,
    *,
    stats_interval: float = STATS_LOG_INTERVAL_SECONDS,
    status_interval: float = STATUS_INTERVAL_SECONDS,
) -> ConsumerStats:
    """Consumer, writer y publisher juntos; se paran con SIGINT/SIGTERM (o cuando se active `stop`).

    Al parar: primero se cierra la conexión con AISStream, después el writer guarda (y publica)
    lo que quede en la cola, se deja el último estado en Redis y se cierran las conexiones.
    """
    api_key = _require_api_key(settings)
    queue: asyncio.Queue[AisRecord] = asyncio.Queue(maxsize=settings.ais_queue_max_size)
    consumer = AisConsumer(
        url=settings.aisstream_url,
        api_key=api_key,
        queue=queue,
        reconnect_max_seconds=settings.ais_reconnect_max_seconds,
    )
    engine = create_engine(settings)
    publisher = AisPublisher(create_redis(settings))
    writer = AisWriter(
        queue=queue,
        session_factory=create_session_factory(engine),
        batch_size=settings.ais_batch_size,
        flush_seconds=settings.ais_batch_flush_seconds,
        on_committed=publisher.publish_batch,
    )
    if stop is None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
    writer_stop = asyncio.Event()
    writer_task = asyncio.create_task(writer.run(writer_stop))
    stats_task = asyncio.create_task(_log_stats(consumer.stats, writer.stats, stats_interval))

    def current_status() -> WorkerStatus:
        return worker_status(consumer=consumer.stats, writer=writer.stats, queue_size=queue.qsize())

    status_task = asyncio.create_task(_publish_status(publisher, current_status, status_interval))
    logger.info("ais_worker_started", host=urlsplit(settings.aisstream_url).hostname)
    try:
        await consumer.run(stop)
    finally:
        # El writer vacía la cola después de que el consumer haya dejado de añadir.
        writer_stop.set()
        await writer_task
        for task in (stats_task, status_task):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        # Último estado (desconectado) antes de cerrar: caduca solo con su TTL.
        await publisher.publish_status(current_status())
        await publisher.close()
        await engine.dispose()
        logger.info("ais_worker_stopped", **_stats_event(consumer.stats, writer.stats))
    return consumer.stats


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    asyncio.run(run_worker(settings))


if __name__ == "__main__":
    main()
