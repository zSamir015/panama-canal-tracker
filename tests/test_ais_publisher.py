"""Publisher AIS sin Redis real: formato del mensaje, estado y tolerancia a fallos."""

import io
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.config import Settings
from app.core.logging import configure_logging
from app.repositories.ais import PositionRow, VesselRow
from app.workers.ais_consumer import ConsumerStats
from app.workers.ais_publisher import (
    LIVE_CHANNEL,
    MAX_VESSELS_PER_MESSAGE,
    STATUS_KEY,
    AisPublisher,
    create_redis,
    worker_status,
)
from app.workers.ais_writer import Batch, WriterStats

T0 = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
LIVE_FIELDS = {"mmsi", "lon", "lat", "cog", "sog", "ship_type", "name", "ts"}


class FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.published: list[tuple[str, bytes]] = []
        self.sets: list[tuple[str, bytes, int | None]] = []
        self.calls = 0

    async def publish(self, channel: str, payload: bytes) -> int:
        self.calls += 1
        if self.fail:
            raise RedisConnectionError("Error 61 connecting to redis:6379.")
        self.published.append((channel, payload))
        return 1

    async def set(self, key: str, payload: bytes, ex: int | None = None) -> bool:
        self.calls += 1
        if self.fail:
            raise RedisConnectionError("Error 61 connecting to redis:6379.")
        self.sets.append((key, payload, ex))
        return True


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def row(mmsi: int = 352000001, seconds: int = 0, **overrides: Any) -> PositionRow:
    values: dict[str, Any] = {
        "received_at": T0 + timedelta(seconds=seconds),
        "mmsi": mmsi,
        "lat": 9.35,
        "lon": -79.91,
        "sog": 7.8,
        "cog": 145.2,
        "heading": 146,
        "nav_status": 0,
    }
    return PositionRow(**(values | overrides))


def batch(positions: list[PositionRow], vessels: list[VesselRow] | None = None) -> Batch:
    return Batch(vessels=vessels or [], positions=positions, size=len(positions))


def messages(redis: FakeRedis) -> list[dict[str, Any]]:
    return [json.loads(payload) for _, payload in redis.published]


# --- Mensaje en vivo ------------------------------------------------------------------------


async def test_publishes_the_live_contract_on_the_live_channel() -> None:
    redis = FakeRedis()
    publisher = AisPublisher(redis)  # type: ignore[arg-type]

    await publisher.publish_batch(
        batch([row()], [VesselRow(352000001, T0, name="PACIFIC STAR", ship_type=70)])
    )

    [(channel, _)] = redis.published
    assert channel == LIVE_CHANNEL
    [message] = messages(redis)
    assert message["type"] == "update"
    [vessel] = message["vessels"]
    assert set(vessel) == LIVE_FIELDS  # docs/API_DESIGN.md, /ws/live
    assert vessel["lon"] == -79.91 and vessel["lat"] == 9.35  # por nombre, nunca en tupla
    assert vessel["name"] == "PACIFIC STAR"
    assert vessel["ship_type"] == 70
    assert datetime.fromisoformat(vessel["ts"]) == T0


async def test_only_the_latest_position_of_each_vessel_is_published() -> None:
    redis = FakeRedis()
    publisher = AisPublisher(redis)  # type: ignore[arg-type]

    await publisher.publish_batch(
        batch([row(seconds=30, lat=9.30), row(seconds=10, lat=9.10), row(636000002, seconds=5)])
    )

    [message] = messages(redis)
    by_mmsi = {vessel["mmsi"]: vessel for vessel in message["vessels"]}
    assert set(by_mmsi) == {352000001, 636000002}
    assert by_mmsi[352000001]["lat"] == 9.30


async def test_names_learned_in_earlier_batches_are_reused() -> None:
    redis = FakeRedis()
    publisher = AisPublisher(redis)  # type: ignore[arg-type]
    await publisher.publish_batch(
        batch([row()], [VesselRow(352000001, T0, name="PACIFIC STAR", ship_type=70)])
    )

    # Siguiente lote: solo posiciones (el ShipStaticData llega cada 6 minutos).
    await publisher.publish_batch(batch([row(seconds=30)], [VesselRow(352000001, T0)]))

    second = messages(redis)[1]["vessels"][0]
    assert (second["name"], second["ship_type"]) == ("PACIFIC STAR", 70)


async def test_unknown_names_are_null_not_invented() -> None:
    redis = FakeRedis()
    await AisPublisher(redis).publish_batch(batch([row()]))  # type: ignore[arg-type]

    [vessel] = messages(redis)[0]["vessels"]
    assert vessel["name"] is None
    assert vessel["ship_type"] is None


async def test_hostile_names_are_published_as_plain_text() -> None:
    redis = FakeRedis()
    name = "<img src=x onerror=alert(1)>"

    await AisPublisher(redis).publish_batch(  # type: ignore[arg-type]
        batch([row()], [VesselRow(352000001, T0, name=name)])
    )

    assert messages(redis)[0]["vessels"][0]["name"] == name  # §8.7: se escapa al mostrarlo


async def test_large_batches_are_split_into_several_messages() -> None:
    redis = FakeRedis()
    rows = [row(352000000 + index) for index in range(1, MAX_VESSELS_PER_MESSAGE + 51)]

    await AisPublisher(redis).publish_batch(batch(rows))  # type: ignore[arg-type]

    sizes = [len(message["vessels"]) for message in messages(redis)]
    assert sizes == [MAX_VESSELS_PER_MESSAGE, 50]


async def test_an_invalid_vessel_is_left_out_of_the_message() -> None:
    redis = FakeRedis()
    publisher = AisPublisher(redis)  # type: ignore[arg-type]

    await publisher.publish_batch(batch([row(352000001), row(636000002, sog=150.0)]))

    [vessel] = messages(redis)[0]["vessels"]
    assert vessel["mmsi"] == 352000001
    assert publisher.stats.invalid == 1


async def test_empty_batch_publishes_nothing() -> None:
    redis = FakeRedis()

    await AisPublisher(redis).publish_batch(batch([]))  # type: ignore[arg-type]

    assert redis.calls == 0


# --- Redis caído ----------------------------------------------------------------------------


async def test_redis_failure_is_counted_never_raised() -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    redis = FakeRedis(fail=True)
    publisher = AisPublisher(redis)  # type: ignore[arg-type]

    await publisher.publish_batch(batch([row()]))

    assert publisher.stats.failures == 1
    assert publisher.stats.messages_published == 0
    [event] = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert event["event"] == "redis_publish_failed"
    assert event["error"] == "ConnectionError"
    assert "6379" not in stream.getvalue()  # ni host ni puerto: solo el tipo de error


async def test_after_a_failure_publishing_pauses_then_recovers() -> None:
    # Un Redis colgado no puede añadir un timeout a cada lote.
    redis = FakeRedis(fail=True)
    clock = Clock()
    publisher = AisPublisher(redis, cooldown_seconds=5, monotonic=clock)  # type: ignore[arg-type]

    await publisher.publish_batch(batch([row()]))
    await publisher.publish_batch(batch([row(seconds=2)]))
    assert redis.calls == 1  # el segundo ni lo intenta
    assert publisher.stats.skipped == 1

    redis.fail = False
    clock.now += 5.1
    await publisher.publish_batch(batch([row(seconds=10)]))

    assert len(redis.published) == 1
    assert publisher.stats.messages_published == 1


def test_client_has_short_timeouts_and_no_retries() -> None:
    settings = Settings(_env_file=None, redis_url="redis://:pw-redis-falsa@127.0.0.1:6379/0")  # type: ignore[arg-type]

    client = create_redis(settings)

    connection = client.connection_pool.connection_kwargs
    assert connection["socket_timeout"] == 1.0
    assert connection["socket_connect_timeout"] == 1.0
    assert client.get_retry() is not None
    assert client.get_retry()._retries == 0  # type: ignore[union-attr]
    assert "pw-redis-falsa" not in repr(client)


# --- Estado del worker ----------------------------------------------------------------------


def stats() -> tuple[ConsumerStats, WriterStats]:
    consumer = ConsumerStats(connections=3, connected=True, subscribed=True, received=120)
    consumer.rejected["invalid_mmsi"] = 2
    consumer.last_message_at = T0
    writer = WriterStats(batches=4, positions_written=100, last_flush_at=T0)
    return consumer, writer


async def test_status_is_stored_with_an_expiry_and_its_update_time() -> None:
    redis = FakeRedis()
    consumer, writer = stats()
    status = worker_status(consumer=consumer, writer=writer, queue_size=7, now=T0)

    await AisPublisher(redis, status_ttl_seconds=15).publish_status(status)  # type: ignore[arg-type]

    [(key, payload, ttl)] = redis.sets
    assert key == STATUS_KEY
    assert ttl == 15  # si el worker muere, el estado caduca
    stored = json.loads(payload)
    assert datetime.fromisoformat(stored["updated_at"]) == T0
    assert stored["connected"] is True
    assert stored["connections"] == 3
    assert stored["queue_size"] == 7
    assert stored["rejected"] == {"invalid_mmsi": 2}
    assert stored["positions_written"] == 100


async def test_status_failure_is_counted_never_raised() -> None:
    redis = FakeRedis(fail=True)
    consumer, writer = stats()
    publisher = AisPublisher(redis)  # type: ignore[arg-type]

    await publisher.publish_status(worker_status(consumer=consumer, writer=writer, queue_size=0))

    assert publisher.stats.failures == 1


def test_publisher_repr_shows_no_connection_details() -> None:
    assert repr(AisPublisher(FakeRedis())) == "AisPublisher()"  # type: ignore[arg-type]


async def test_static_data_with_a_type_but_no_name_keeps_the_known_name() -> None:
    redis = FakeRedis()
    publisher = AisPublisher(redis)  # type: ignore[arg-type]
    await publisher.publish_batch(
        batch([row()], [VesselRow(352000001, T0, name="PACIFIC STAR", ship_type=70)])
    )

    await publisher.publish_batch(
        batch([row(seconds=30)], [VesselRow(352000001, T0, name=None, ship_type=80)])
    )

    vessel = messages(redis)[1]["vessels"][0]
    assert (vessel["name"], vessel["ship_type"]) == ("PACIFIC STAR", 80)
