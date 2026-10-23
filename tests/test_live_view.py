"""Estado de cada cliente de `/ws/live` sin red: viewport, agrupación y `remove` (4.2)."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError

from app.schemas.live import (
    AuthMessage,
    BBox,
    LiveUpdate,
    LiveVessel,
    SubscribeMessage,
    client_message_adapter,
)
from app.services.live import ClientView, ConnectionLimiter, LiveHub

T0 = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
CANAL = BBox(min_lon=-80.2, min_lat=8.4, max_lon=-79.2, max_lat=9.7)


def vessel(
    mmsi: int = 352000001, lon: float = -79.9, lat: float = 9.3, seconds: int = 0
) -> LiveVessel:
    return LiveVessel(
        mmsi=mmsi,
        lon=lon,
        lat=lat,
        cog=180.0,
        sog=7.5,
        ship_type=70,
        name="PACIFIC STAR",
        ts=T0 + timedelta(seconds=seconds),
    )


OUTSIDE = {"lon": -78.0, "lat": 9.3}


# --- Viewport y agrupación ------------------------------------------------------------------


def test_nothing_is_sent_before_subscribing() -> None:
    view = ClientView()

    view.offer([vessel()])

    assert view.drain() == ([], [])


def test_only_vessels_inside_the_viewport_are_sent() -> None:
    view = ClientView()
    view.reset(CANAL, [])

    view.offer([vessel(352000001), vessel(352000002, **OUTSIDE)])

    updates, removes = view.drain()
    assert [v.mmsi for v in updates] == [352000001]
    assert removes == []


def test_updates_are_coalesced_keeping_the_latest_position() -> None:
    # Un cliente que tarda en recibir no acumula mensajes: solo la última posición de cada buque.
    view = ClientView()
    view.reset(CANAL, [])

    view.offer([vessel(seconds=0, lat=9.0)])
    view.offer([vessel(seconds=10, lat=9.1)])
    view.offer([vessel(seconds=5, lat=9.05)])  # llega tarde: no pisa a la más nueva

    updates, _ = view.drain()
    assert [(v.lat, v.ts) for v in updates] == [(9.1, T0 + timedelta(seconds=10))]
    assert view.drain() == ([], [])


def test_a_known_vessel_leaving_the_viewport_is_removed() -> None:
    view = ClientView()
    view.reset(CANAL, [vessel(352000001)])

    view.offer([vessel(352000001, seconds=10, **OUTSIDE)])

    assert view.drain() == ([], [352000001])
    # Ya no la conoce: otra posición fuera no repite el `remove`.
    view.offer([vessel(352000001, seconds=20, **OUTSIDE)])
    assert view.drain() == ([], [])


def test_a_vessel_that_enters_and_leaves_between_flushes_is_never_sent() -> None:
    view = ClientView()
    view.reset(CANAL, [])

    view.offer([vessel(seconds=0)])
    view.offer([vessel(seconds=10, **OUTSIDE)])

    assert view.drain() == ([], [])


def test_a_vessel_that_returns_is_sent_again() -> None:
    view = ClientView()
    view.reset(CANAL, [vessel()])
    view.offer([vessel(seconds=10, **OUTSIDE)])
    view.drain()

    view.offer([vessel(seconds=20)])

    updates, removes = view.drain()
    assert [v.mmsi for v in updates] == [352000001]
    assert removes == []


def test_a_new_viewport_discards_what_was_pending() -> None:
    # El snapshot del nuevo viewport sustituye todo lo anterior en el cliente.
    view = ClientView()
    view.reset(CANAL, [vessel(352000001)])
    view.offer([vessel(352000002)])

    view.reset(BBox(min_lon=-78.5, min_lat=9.0, max_lon=-77.5, max_lat=9.5), [])

    assert view.drain() == ([], [])


# --- Mensajes del cliente -------------------------------------------------------------------


def parse(payload: Any) -> AuthMessage | SubscribeMessage:
    return client_message_adapter.validate_json(json.dumps(payload))


def test_subscribe_uses_geojson_order() -> None:
    message = parse({"type": "subscribe", "bbox": [-80.2, 8.4, -79.2, 9.7]})

    assert isinstance(message, SubscribeMessage)
    assert message.viewport() == CANAL


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "subscribe", "bbox": [-79.2, 8.4, -80.2, 9.7]},  # min_lon > max_lon
        {"type": "subscribe", "bbox": [-80.2, 9.7, -79.2, 8.4]},  # min_lat > max_lat
        {"type": "subscribe", "bbox": [-181, 8.4, -79.2, 9.7]},
        {"type": "subscribe", "bbox": [-80.2, 8.4, -79.2]},
        {"type": "subscribe", "bbox": ["-80.2", 8.4, -79.2, 9.7]},
        {"type": "subscribe", "bbox": [-80.2, 8.4, -79.2, 9.7], "extra": 1},
        {"type": "auth", "token": ""},
        {"type": "auth", "token": "x" * 2049},
        {"type": "auth", "token": 123},
        {"type": "admin"},
        {"bbox": [-80.2, 8.4, -79.2, 9.7]},
        [],
    ],
)
def test_invalid_client_messages_are_rejected(payload: Any) -> None:
    with pytest.raises(ValidationError):
        parse(payload)


def test_auth_message_never_shows_the_token() -> None:
    message = parse({"type": "auth", "token": "eyJ.secreto.firmado"})

    assert "secreto" not in repr(message)
    assert "secreto" not in str(message)


# --- Hub y límite de conexiones sin Redis real ----------------------------------------------


class BrokenRedis:
    """Redis que no responde: toda operación falla como un timeout de red."""

    def pipeline(self, **_: Any) -> Any:
        raise RedisConnectionError("caído")

    async def zrem(self, *_: Any) -> int:
        raise RedisConnectionError("caído")


async def test_connection_limit_still_applies_per_replica_when_redis_is_down() -> None:
    limiter = ConnectionLimiter(BrokenRedis(), max_per_user=2)  # type: ignore[arg-type]

    assert await limiter.acquire("user-a", "c1")
    assert await limiter.acquire("user-a", "c2")
    assert not await limiter.acquire("user-a", "c3")
    assert await limiter.acquire("user-b", "c4")  # otro usuario, su propio cupo

    await limiter.release("user-a", "c1")
    assert await limiter.acquire("user-a", "c5")


def test_hub_dispatches_valid_updates_and_counts_invalid_ones() -> None:
    hub = LiveHub(BrokenRedis())  # type: ignore[arg-type]
    inside, outside = ClientView(), ClientView()
    inside.reset(CANAL, [])
    outside.reset(BBox(min_lon=-78.5, min_lat=9.0, max_lon=-77.5, max_lat=9.5), [])
    hub._clients.update({inside, outside})

    hub.dispatch(LiveUpdate(vessels=[vessel()]).model_dump_json())
    hub.dispatch(b"no es JSON")
    hub.dispatch(b'{"type": "update", "vessels": [{"mmsi": 1}]}')

    assert [v.mmsi for v in inside.drain()[0]] == [352000001]
    assert outside.drain() == ([], [])
    assert (hub.stats.messages, hub.stats.invalid) == (1, 2)


class FlakyPubSub:
    def __init__(self, fail: bool, messages: list[Any]) -> None:
        self._fail = fail
        self._messages = messages

    async def __aenter__(self) -> "FlakyPubSub":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def subscribe(self, *_: Any) -> None:
        if self._fail:
            raise RedisConnectionError("caído")

    async def get_message(self, **_: Any) -> Any:
        if self._messages:
            return self._messages.pop(0)
        await asyncio.sleep(0.01)
        return None


class FlakyRedis:
    """La primera suscripción falla (Redis caído); la segunda entrega un `update`."""

    def __init__(self, payload: str) -> None:
        self.calls = 0
        self._payload = payload

    def pubsub(self) -> FlakyPubSub:
        self.calls += 1
        message = {"type": "message", "data": self._payload.encode()}
        return FlakyPubSub(fail=self.calls == 1, messages=[message])


async def test_hub_resubscribes_after_redis_fails() -> None:
    redis = FlakyRedis(LiveUpdate(vessels=[vessel()]).model_dump_json())
    hub = LiveHub(redis, reconnect_max_seconds=0.01)  # type: ignore[arg-type]
    view = ClientView()
    view.reset(CANAL, [])

    hub.register(view)
    try:
        async with asyncio.timeout(3):
            while True:
                if hub.stats.messages:
                    break
                await asyncio.sleep(0.01)
    finally:
        await hub.close()

    assert redis.calls == 2
    assert hub.stats.failures == 1
    assert [v.mmsi for v in view.drain()[0]] == [352000001]
    assert hub.stats.subscribed is False  # tras `close`
