"""Writer AIS sin base de datos: cómo forma los lotes y cómo reintenta (el SQL, en integración)."""

import asyncio
import io
import json
import random
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from app.core.logging import configure_logging
from app.services.ais_parser import PositionUpdate, VesselStatic
from app.workers import ais_writer as ais_writer_module
from app.workers.ais_writer import AisWriter, build_batch
from app.workers.common import AisRecord

T0 = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


def position(mmsi: int = 352000001, seconds: int = 0, **overrides: Any) -> PositionUpdate:
    values: dict[str, Any] = {
        "mmsi": mmsi,
        "received_at": T0 + timedelta(seconds=seconds),
        "lat": 9.3,
        "lon": -79.9,
        "sog": 7.5,
        "cog": 180.0,
        "heading": 181,
        "nav_status": 0,
    }
    return PositionUpdate(**(values | overrides))


def static(mmsi: int = 352000001, name: str | None = "PACIFIC STAR") -> VesselStatic:
    return VesselStatic(
        mmsi=mmsi, name=name, imo=9100001, ship_type=70, length_m=225.0, beam_m=32.0
    )


# --- Formar el lote -------------------------------------------------------------------------


def test_batch_has_one_vessel_per_mmsi_with_its_last_position_time() -> None:
    batch = build_batch(
        [position(seconds=30), position(seconds=10), position(mmsi=636000002, seconds=5)]
    )

    assert [v.mmsi for v in batch.vessels] == [352000001, 636000002]
    assert batch.vessels[0].last_seen_at == T0 + timedelta(seconds=30)
    assert batch.vessels[0].name is None  # sin datos estáticos en el lote
    assert len(batch.positions) == 3
    assert batch.size == 3


def test_repeated_position_in_the_same_batch_is_kept_once() -> None:
    batch = build_batch([position(seconds=10), position(seconds=10), position(seconds=20)])

    assert len(batch.positions) == 2
    assert batch.size == 3


def test_static_data_merges_into_the_vessel_and_the_last_one_wins() -> None:
    batch = build_batch([static(name="OLD NAME"), position(seconds=10), static(name="NEW NAME")])

    [vessel] = batch.vessels
    assert vessel.name == "NEW NAME"
    assert vessel.length_m == 225.0
    assert vessel.last_seen_at == T0 + timedelta(seconds=10)


def test_static_only_vessel_has_no_last_seen_time() -> None:
    [vessel] = build_batch([static()]).vessels

    assert vessel.last_seen_at is None
    assert build_batch([static()]).positions == []


# --- Lotes por tamaño y por tiempo ----------------------------------------------------------


class RecordingWriter(AisWriter):
    def __init__(self, queue: asyncio.Queue[AisRecord], **kwargs: Any) -> None:
        super().__init__(queue=queue, session_factory=None, **kwargs)  # type: ignore[arg-type]
        self.batches: list[int] = []

    async def flush(self, records: Sequence[AisRecord]) -> None:
        self.batches.append(len(records))


async def test_batches_are_cut_at_the_batch_size() -> None:
    queue: asyncio.Queue[AisRecord] = asyncio.Queue()
    for second in range(7):
        queue.put_nowait(position(seconds=second))
    writer = RecordingWriter(queue, batch_size=3, flush_seconds=10)
    stop = asyncio.Event()

    task = asyncio.create_task(writer.run(stop))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=1)

    assert writer.batches == [3, 3, 1]


async def test_a_partial_batch_is_written_after_the_flush_interval() -> None:
    queue: asyncio.Queue[AisRecord] = asyncio.Queue()
    writer = RecordingWriter(queue, batch_size=100, flush_seconds=0.05)
    stop = asyncio.Event()
    task = asyncio.create_task(writer.run(stop))

    queue.put_nowait(position(seconds=1))
    queue.put_nowait(position(seconds=2))
    await asyncio.sleep(0.2)

    assert writer.batches == [2]  # sin esperar a llenar los 100
    stop.set()
    await asyncio.wait_for(task, timeout=1)


async def test_stop_writes_what_is_left_in_the_queue_and_exits() -> None:
    queue: asyncio.Queue[AisRecord] = asyncio.Queue()
    writer = RecordingWriter(queue, batch_size=100, flush_seconds=60)
    stop = asyncio.Event()
    task = asyncio.create_task(writer.run(stop))
    await asyncio.sleep(0.01)

    for second in range(5):
        queue.put_nowait(position(seconds=second))
    stop.set()
    await asyncio.wait_for(task, timeout=1)

    assert sum(writer.batches) == 5
    assert queue.empty()


async def test_idle_writer_stops_promptly() -> None:
    writer = RecordingWriter(asyncio.Queue(), batch_size=10, flush_seconds=0.05)
    stop = asyncio.Event()
    task = asyncio.create_task(writer.run(stop))
    await asyncio.sleep(0.02)

    stop.set()
    await asyncio.wait_for(task, timeout=1)

    assert writer.batches == []


# --- Base caída -----------------------------------------------------------------------------


class UnreachableDatabase:
    """Fábrica de sesiones cuya base nunca responde."""

    calls = 0

    def __call__(self) -> Any:
        type(self).calls += 1
        raise OperationalError("connect", {}, ConnectionRefusedError("refused"))


async def test_unreachable_database_is_retried_then_the_batch_is_dropped() -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    factory = UnreachableDatabase()
    UnreachableDatabase.calls = 0
    writer = AisWriter(
        queue=asyncio.Queue(),
        session_factory=factory,  # type: ignore[arg-type]
        max_attempts=4,
        retry_base_seconds=0.001,
        retry_max_seconds=0.01,
    )

    await writer.flush([position(seconds=1), position(seconds=2)])

    assert UnreachableDatabase.calls == 4
    assert writer.stats.batches_retried == 4
    assert writer.stats.batches_dropped == 1
    assert writer.stats.records_dropped == 2
    assert writer.stats.last_error == "OperationalError"
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [e["attempt"] for e in events if e["event"] == "ais_batch_retry"] == [1, 2, 3, 4]
    [dropped] = [e for e in events if e["event"] == "ais_batch_dropped"]
    assert dropped["size"] == 2


@pytest.mark.parametrize("value", [0, -1], ids=["cero", "negativo"])
def test_batch_settings_are_bounded(value: int) -> None:
    from app.core.config import Settings

    with pytest.raises(ValueError):
        Settings(_env_file=None, ais_batch_size=value)
    with pytest.raises(ValueError):
        Settings(_env_file=None, ais_batch_flush_seconds=value)


async def test_a_record_arriving_together_with_stop_is_not_lost() -> None:
    # `get` y `stop` terminan en el mismo instante: el registro tiene que llegar al lote.
    queue: asyncio.Queue[AisRecord] = asyncio.Queue()
    queue.put_nowait(position(seconds=1))
    stop = asyncio.Event()
    stop.set()
    writer = RecordingWriter(queue, batch_size=10, flush_seconds=1)

    record = await writer._next(stop, 1)

    assert record == position(seconds=1)
    assert queue.empty()


async def test_retries_wait_longer_each_time(monkeypatch: pytest.MonkeyPatch) -> None:
    # Sin espera, el worker machacaría una base que ya está caída.
    waits: list[float] = []

    async def record_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(ais_writer_module.asyncio, "sleep", record_sleep)
    writer = AisWriter(
        queue=asyncio.Queue(),
        session_factory=UnreachableDatabase(),  # type: ignore[arg-type]
        max_attempts=4,
        retry_base_seconds=1.0,
        retry_max_seconds=60.0,
        rng=random.Random(0),
    )

    await writer.flush([position()])

    assert len(waits) == 4
    for attempt, wait in enumerate(waits):
        ceiling = 2.0**attempt
        assert ceiling / 2 <= wait <= ceiling  # 0,5 a 1 s, 1 a 2 s, 2 a 4 s, 4 a 8 s
