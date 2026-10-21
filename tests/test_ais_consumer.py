"""Worker AIS (`app/workers/ais_consumer.py`) contra servidores WebSocket locales.

Nada de AISStream real: el simulador (3.6) para el tráfico normal y servidores mínimos para cada
fallo (no confirmar, cerrar, key inválida...). El backoff se reduce a milisegundos.
"""

import asyncio
import io
import json
import logging
import os
import random
import signal
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import SecretStr
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from app.core.config import Settings
from app.core.logging import configure_logging
from app.services.ais_parser import PositionUpdate, VesselStatic
from app.workers import ais_consumer
from app.workers.ais_consumer import AisConsumer, AisRecord, backoff_delay, run_worker
from app.workers.ais_writer import WriterStats
from tests.scripts_loader import load_script

sim = load_script("ais_simulator")

API_KEY = "clave-de-pruebas-del-worker"
START = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
FIXED_NOW = datetime(2026, 10, 20, 15, 30, tzinfo=UTC)
CONFIRMATION = json.dumps(
    {"MessageType": "SubscriptionConfirmation", "Message": {"CompressionEnabled": True}}
).encode()

Handler = Callable[[ServerConnection], Awaitable[None]]


# Los servidores falsos de los tests corren en el mismo proceso: su logger (`websockets.server`)
# escribiría en DEBUG la suscripción recibida, con la key, y ensuciaría el test de los logs.
quiet_server_logger = logging.getLogger("tests.fake_aisstream")
quiet_server_logger.setLevel(logging.WARNING)


@asynccontextmanager
async def ws_server(handler: Handler) -> AsyncIterator[str]:
    async with serve(handler, "127.0.0.1", 0, logger=quiet_server_logger) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        yield f"ws://127.0.0.1:{port}"


@asynccontextmanager
async def simulator(**generate: Any) -> AsyncIterator[str]:
    options: dict[str, Any] = {"start": START, "duration": timedelta(minutes=10), "seed": 1}
    messages = sim.generate(**(options | generate))
    server = await sim.start_server(messages, port=0, speed=0)
    port = next(iter(server.sockets)).getsockname()[1]
    try:
        yield f"ws://127.0.0.1:{port}"
    finally:
        server.close()
        await server.wait_closed()


def make_consumer(
    url: str, queue: asyncio.Queue[AisRecord] | None = None, **kwargs: Any
) -> AisConsumer:
    options: dict[str, Any] = {
        "url": url,
        "api_key": SecretStr(API_KEY),
        "queue": queue if queue is not None else asyncio.Queue(),
        "reconnect_max_seconds": 0.02,
        "backoff_base_seconds": 0.002,
        "confirmation_timeout": 0.5,
        "rng": random.Random(0),
        "clock": lambda: FIXED_NOW,
    }
    return AisConsumer(**(options | kwargs))


async def eventually(condition: Callable[[], bool], task: asyncio.Task[None] | None = None) -> None:
    """Espera (máx. 5 s) a que se cumpla `condition`; si `task` falla antes, propaga su error."""
    async with asyncio.timeout(5):
        while not condition():
            if task is not None and task.done():
                task.result()
            await asyncio.sleep(0.005)


async def run_until(consumer: AisConsumer, condition: Callable[[], bool]) -> None:
    stop = asyncio.Event()
    task = asyncio.create_task(consumer.run(stop))
    try:
        await eventually(condition, task)
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=5)


def log_events(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


# --- Suscripción y flujo normal -------------------------------------------------------------


async def test_subscribes_to_the_canal_bounding_box_right_after_connecting() -> None:
    received: list[str | bytes] = []

    async def handler(connection: ServerConnection) -> None:
        received.append(await connection.recv())
        await connection.send(CONFIRMATION)
        await connection.wait_closed()

    async with ws_server(handler) as url:
        consumer = make_consumer(url)
        await run_until(consumer, lambda: consumer.stats.subscribed)

    subscription = json.loads(received[0])
    assert subscription == {
        "APIKey": API_KEY,
        "BoundingBoxes": [[[8.4, -80.2], [9.7, -79.2]]],  # [lat, lon], como pide AISStream
        "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
    }


async def test_parsed_records_reach_the_queue_with_the_reception_time() -> None:
    queue: asyncio.Queue[AisRecord] = asyncio.Queue()
    async with simulator() as url:
        consumer = make_consumer(url, queue)
        await run_until(consumer, lambda: queue.qsize() >= 50)

    records = [queue.get_nowait() for _ in range(queue.qsize())]
    assert {type(record) for record in records} == {PositionUpdate, VesselStatic}
    positions = [record for record in records if isinstance(record, PositionUpdate)]
    assert all(position.received_at == FIXED_NOW for position in positions)
    assert consumer.stats.queued >= 50
    assert consumer.stats.last_message_at == FIXED_NOW


async def test_rejected_messages_are_counted_and_never_queued() -> None:
    queue: asyncio.Queue[AisRecord] = asyncio.Queue()
    async with simulator(invalid_ratio=0.5) as url:
        consumer = make_consumer(url, queue)
        await run_until(consumer, lambda: sum(consumer.stats.rejected.values()) >= 20)

    assert set(consumer.stats.rejected) <= {
        "invalid_json",
        "invalid_mmsi",
        "invalid_position",
        "no_position",
        "mmsi_mismatch",
        "invalid_message",
    }
    while not queue.empty():
        assert isinstance(queue.get_nowait(), PositionUpdate | VesselStatic)


async def test_unknown_control_frames_are_ignored() -> None:
    async def handler(connection: ServerConnection) -> None:
        await connection.recv()
        await connection.send(CONFIRMATION)
        await connection.send(b'{"MessageType": "BaseStationReport", "Message": {}}')
        await connection.send(b"[1, 2, 3]")
        await connection.wait_closed()

    async with ws_server(handler) as url:
        consumer = make_consumer(url)
        await run_until(consumer, lambda: consumer.stats.ignored >= 1)

    assert consumer.stats.rejected["invalid_schema"] == 1  # la lista no es un objeto
    assert consumer.stats.queued == 0


# --- Reconexión y backoff -------------------------------------------------------------------


def test_backoff_doubles_up_to_the_cap_with_jitter() -> None:
    rng = random.Random(1)

    for attempt in range(12):
        ceiling = min(60.0, 2.0**attempt)
        delays = [backoff_delay(attempt, cap=60, rng=rng) for _ in range(50)]
        assert all(ceiling / 2 <= delay <= ceiling for delay in delays)
        assert len(set(delays)) > 1  # jitter: no todos esperan lo mismo

    assert backoff_delay(10_000, cap=60, rng=rng) <= 60  # sin desbordarse


async def test_reconnects_when_the_server_closes_and_resets_the_backoff() -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    async with simulator(duration=timedelta(minutes=1)) as url:
        consumer = make_consumer(url)
        await run_until(consumer, lambda: consumer.stats.connections >= 3)

    scheduled = [e for e in log_events(stream) if e["event"] == "ais_reconnect_scheduled"]
    assert len(scheduled) >= 2
    # Cada conexión llegó a confirmar: el backoff vuelve siempre al primer intento.
    assert {event["attempt"] for event in scheduled} == {1}


async def test_backoff_grows_while_the_subscription_is_never_confirmed() -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)

    async def handler(connection: ServerConnection) -> None:
        await connection.recv()
        await connection.close(1008, "invalid subscription")  # como AISStream: sin confirmación

    async with ws_server(handler) as url:
        consumer = make_consumer(url, reconnect_max_seconds=10.0, backoff_base_seconds=0.001)
        await run_until(consumer, lambda: consumer.stats.connections >= 5)

    scheduled = [e for e in log_events(stream) if e["event"] == "ais_reconnect_scheduled"]
    attempts = [event["attempt"] for event in scheduled]
    assert attempts[:4] == [1, 2, 3, 4]
    delays = [event["delay_seconds"] for event in scheduled[:4]]
    assert delays[3] > delays[0]
    assert consumer.stats.last_error == "ConnectionClosedError"


async def test_connection_refused_is_retried() -> None:
    async with ws_server(lambda connection: connection.wait_closed()) as url:
        pass  # el servidor ya está cerrado: el puerto rechaza la conexión

    consumer = make_consumer(url)
    await run_until(consumer, lambda: consumer.stats.last_error is not None)

    assert consumer.stats.connections == 0
    assert consumer.stats.last_error in {"ConnectionRefusedError", "OSError"}


async def test_unconfirmed_subscription_times_out_and_reconnects() -> None:
    connections = 0

    async def handler(connection: ServerConnection) -> None:
        nonlocal connections
        connections += 1
        await connection.recv()
        await connection.wait_closed()  # nunca confirma

    async with ws_server(handler) as url:
        consumer = make_consumer(url, confirmation_timeout=0.05)
        await run_until(consumer, lambda: connections >= 2)

    assert consumer.stats.last_error == "TimeoutError"


async def test_server_error_is_logged_and_triggers_a_reconnect() -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)

    async def handler(connection: ServerConnection) -> None:
        await connection.recv()
        await connection.send(b'{"error": "Api Key Is Not Valid"}')
        await connection.wait_closed()

    async with ws_server(handler) as url:
        consumer = make_consumer(url)
        await run_until(consumer, lambda: consumer.stats.connections >= 2)

    errors = [e for e in log_events(stream) if e["event"] == "ais_server_error"]
    assert errors[0]["error"] == "Api Key Is Not Valid"
    assert consumer.stats.last_error == "AisServerError"


async def test_only_one_connection_at_a_time() -> None:
    open_now = 0
    max_open = 0

    async def handler(connection: ServerConnection) -> None:
        nonlocal open_now, max_open
        open_now += 1
        max_open = max(max_open, open_now)
        try:
            await connection.recv()
            await connection.send(CONFIRMATION)
            await asyncio.sleep(0.01)
        finally:
            open_now -= 1

    async with ws_server(handler) as url:
        consumer = make_consumer(url)
        stop = asyncio.Event()
        task = asyncio.create_task(consumer.run(stop))
        await asyncio.sleep(0.01)
        # Un segundo bucle con la misma key abriría otra conexión: se rechaza.
        with pytest.raises(RuntimeError, match="una sola conexión"):
            await asyncio.wait_for(consumer.run(stop), timeout=1)
        await eventually(lambda: consumer.stats.connections >= 5)
        stop.set()
        await asyncio.wait_for(task, timeout=5)

    assert max_open == 1


async def test_stop_closes_the_connection_promptly() -> None:
    closed = asyncio.Event()

    async def handler(connection: ServerConnection) -> None:
        await connection.recv()
        await connection.send(CONFIRMATION)
        await connection.wait_closed()
        closed.set()

    async with ws_server(handler) as url:
        consumer = make_consumer(url, reconnect_max_seconds=60.0)
        stop = asyncio.Event()
        task = asyncio.create_task(consumer.run(stop))
        await eventually(lambda: consumer.stats.subscribed)
        stop.set()
        await asyncio.wait_for(task, timeout=1)
        await asyncio.wait_for(closed.wait(), timeout=1)

    assert consumer.stats.connected is False


async def test_stop_interrupts_the_backoff_wait() -> None:
    async def handler(connection: ServerConnection) -> None:
        await connection.close()

    async with ws_server(handler) as url:
        # Backoff largo: si `stop` no interrumpiera la espera, el test tardaría minutos.
        consumer = make_consumer(url, reconnect_max_seconds=600.0, backoff_base_seconds=300.0)
        stop = asyncio.Event()
        task = asyncio.create_task(consumer.run(stop))
        await eventually(lambda: consumer.stats.connections >= 1)
        await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, timeout=1)


# --- Cola acotada ---------------------------------------------------------------------------


async def test_full_queue_drops_the_oldest_and_keeps_reading() -> None:
    queue: asyncio.Queue[AisRecord] = asyncio.Queue(maxsize=5)
    async with simulator(duration=timedelta(minutes=5)) as url:
        consumer = make_consumer(url, queue)
        # Nadie vacía la cola: aun así el consumer lee todo lo que llega.
        await run_until(consumer, lambda: consumer.stats.dropped >= 20)

    assert queue.qsize() == 5
    assert consumer.stats.queued - consumer.stats.dropped == 5
    kept = [queue.get_nowait() for _ in range(5)]
    times = [record.received_at for record in kept if isinstance(record, PositionUpdate)]
    assert times == sorted(times)


# --- La API key nunca sale ------------------------------------------------------------------


async def test_api_key_never_reaches_the_logs_even_in_debug() -> None:
    stream = io.StringIO()
    configure_logging("DEBUG", stream=stream)

    async def handler(connection: ServerConnection) -> None:
        await connection.recv()
        await connection.close(1008, "invalid subscription")

    async with ws_server(handler) as url:
        consumer = make_consumer(url)
        await run_until(consumer, lambda: consumer.stats.connections >= 2)

    output = stream.getvalue()
    assert "ais_connected" in output
    assert API_KEY not in output
    assert API_KEY not in repr(consumer)
    assert API_KEY not in repr(consumer.stats)


def test_websocket_library_logger_never_logs_frames() -> None:
    # La librería escribe cada frame enviado en DEBUG (la suscripción lleva la key).
    assert not ais_consumer._websocket_logger.isEnabledFor(10)  # DEBUG


# --- Proceso del worker ---------------------------------------------------------------------


class DrainingWriter:
    """Writer falso para los tests sin base: vacía la cola y cuenta (el real, en integración)."""

    def __init__(self, *, queue: asyncio.Queue[AisRecord], **_: Any) -> None:
        self._queue = queue
        self.stats = WriterStats()

    async def run(self, stop: asyncio.Event) -> None:
        while not (stop.is_set() and self._queue.empty()):
            try:
                await asyncio.wait_for(self._queue.get(), timeout=0.01)
            except TimeoutError:
                continue
            self._queue.task_done()
            self.stats.positions_written += 1


class SilentRedis:
    """Redis falso para los tests sin red: acepta todo y recuerda los estados guardados."""

    def __init__(self) -> None:
        self.statuses: list[dict[str, Any]] = []

    async def publish(self, *_: Any) -> int:
        return 0

    async def set(self, _key: str, payload: bytes, **__: Any) -> bool:
        self.statuses.append(json.loads(payload))
        return True

    async def aclose(self) -> None:
        return None


@pytest.fixture(autouse=True)
def no_database_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ais_consumer, "AisWriter", DrainingWriter)
    monkeypatch.setattr(ais_consumer, "create_redis", lambda _settings: silent_redis)


silent_redis = SilentRedis()


def worker_settings(**overrides: Any) -> Settings:
    # Nunca la URL real por defecto: ningún test debe poder conectarse a AISStream.
    options: dict[str, Any] = {
        "_env_file": None,
        "aisstream_api_key": API_KEY,
        "aisstream_url": "ws://127.0.0.1:9",
    }
    return Settings(**(options | overrides))


@pytest.mark.parametrize("key", [None, "", "   "], ids=["ausente", "vacia", "espacios"])
async def test_worker_refuses_to_start_without_an_api_key(key: str | None) -> None:
    # URL local que no responde: si el worker arrancara, nunca tocaría AISStream real.
    settings = worker_settings(aisstream_api_key=key, aisstream_url="ws://127.0.0.1:9")
    with pytest.raises(SystemExit, match="AISSTREAM_API_KEY"):
        await asyncio.wait_for(run_worker(settings, asyncio.Event()), timeout=1)


async def test_worker_reads_from_the_configured_url_until_stopped() -> None:
    stop = asyncio.Event()
    async with simulator() as url:
        task = asyncio.create_task(run_worker(worker_settings(aisstream_url=url), stop))
        await asyncio.sleep(0.3)
        stop.set()
        stats = await asyncio.wait_for(task, timeout=5)

    assert stats.connections >= 1
    assert stats.received > 0


@pytest.mark.parametrize(
    "url",
    [
        "http://stream.aisstream.io/v0/stream",
        "wss://user:pass@stream.aisstream.io/v0/stream",
        "wss://stream.aisstream.io/v0/stream?key=x",
        "wss:///sin-host",
    ],
    ids=["http", "credenciales", "query", "sin_host"],
)
def test_invalid_aisstream_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValueError, match="AISSTREAM_URL"):
        worker_settings(aisstream_url=url)


def test_production_requires_wss() -> None:
    with pytest.raises(ValueError, match="wss://"):
        Settings(
            _env_file=None,
            app_env="production",
            cors_origins=["https://tracker.example.com"],  # type: ignore[arg-type]
            jwt_secret_key="x" * 32,  # type: ignore[arg-type]
            database_url="postgresql+asyncpg://canal_app:pw-falsa@db:5432/canal",  # type: ignore[arg-type]
            redis_url="redis://:pw-redis-falsa@redis:6379/0",  # type: ignore[arg-type]
            aisstream_url="ws://127.0.0.1:8765",
        )


def test_api_key_is_masked_in_settings() -> None:
    assert API_KEY not in repr(worker_settings())


async def test_connection_closed_during_read_is_handled() -> None:
    async def handler(connection: ServerConnection) -> None:
        await connection.recv()
        await connection.send(CONFIRMATION)
        try:
            await connection.send(b"x" * (ais_consumer.MAX_FRAME_BYTES + 1))
        except ConnectionClosed:
            pass

    async with ws_server(handler) as url:
        consumer = make_consumer(url)
        # Un frame por encima del límite corta la conexión (1009) y se reconecta.
        await run_until(consumer, lambda: consumer.stats.connections >= 2)

    assert consumer.stats.last_error == "ConnectionClosedError"


async def test_disabled_compression_is_warned_about() -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    uncompressed = json.dumps(
        {"MessageType": "SubscriptionConfirmation", "Message": {"CompressionEnabled": False}}
    ).encode()

    async def handler(connection: ServerConnection) -> None:
        await connection.recv()
        await connection.send(uncompressed)
        await connection.wait_closed()

    async with ws_server(handler) as url:
        consumer = make_consumer(url)
        await run_until(consumer, lambda: consumer.stats.subscribed)

    events = [e["event"] for e in log_events(stream)]
    assert "ais_compression_disabled" in events


async def test_worker_logs_its_stats_periodically() -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    stop = asyncio.Event()
    async with simulator() as url:
        task = asyncio.create_task(
            run_worker(worker_settings(aisstream_url=url), stop, stats_interval=0.05)
        )
        await eventually(lambda: "ais_stats" in stream.getvalue())
        stop.set()
        await asyncio.wait_for(task, timeout=5)

    [first, *_] = [e for e in log_events(stream) if e["event"] == "ais_stats"]
    assert set(first) >= {
        "connected",
        "received",
        "queued",
        "dropped",
        "ignored",
        "rejected",
        "positions_written",
    }
    assert API_KEY not in stream.getvalue()


async def test_worker_stops_cleanly_on_sigterm() -> None:
    # Docker para el contenedor con SIGTERM: el worker debe cerrar la conexión y salir.
    async with simulator() as url:
        loop = asyncio.get_running_loop()
        loop.call_later(0.2, os.kill, os.getpid(), signal.SIGTERM)
        stats = await asyncio.wait_for(run_worker(worker_settings(aisstream_url=url)), timeout=5)

    assert stats.connections >= 1
    assert stats.connected is False


async def test_worker_leaves_a_final_disconnected_status_when_it_stops() -> None:
    silent_redis.statuses.clear()
    stop = asyncio.Event()
    async with simulator() as url:
        # Intervalo de una hora: solo hay el estado inicial y el final.
        task = asyncio.create_task(
            run_worker(worker_settings(aisstream_url=url), stop, status_interval=3600)
        )
        await eventually(lambda: len(silent_redis.statuses) >= 1)
        await asyncio.sleep(0.2)
        stop.set()
        stats = await asyncio.wait_for(task, timeout=5)

    assert len(silent_redis.statuses) == 2
    final = silent_redis.statuses[-1]
    assert final["connected"] is False
    assert final["received"] == stats.received
