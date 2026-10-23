"""Posiciones en vivo para `/ws/live` (tarea 4.2, docs/ARCHITECTURE.md §2.3).

- `ClientView`: lo que cada navegador debe recibir. Filtra por su viewport, se queda con la última
  posición de cada buque hasta el siguiente envío (1 por segundo) y calcula los `remove`. Es la
  backpressure: un cliente lento no acumula mensajes, solo el estado más reciente.
- `LiveHub`: una suscripción a Redis por réplica de la API (ADR-0004) que reparte cada `update`
  del worker entre los `ClientView` conectados a esa réplica.
- `ConnectionLimiter`: como mucho 5 conexiones por usuario entre todas las réplicas (AGENTS.md
  §8.8), con un sorted set en Redis.
"""

import asyncio
import contextlib
import random
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog
from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.core.db import SessionFactory
from app.core.redis import KEY_PREFIX, LIVE_CHANNEL
from app.core.security import InvalidTokenError, decode_access_token
from app.repositories.user import UserRepository
from app.repositories.vessels import VesselRepository
from app.schemas.live import BBox, LiveUpdate, LiveVessel

# Un buque sin señal desde hace más de esto no está "en vivo" (es la estela de la 4.4).
LIVE_WINDOW = timedelta(minutes=30)
# Tope del snapshot: con la bbox del Canal sobra; protege de un viewport con medio mundo.
MAX_SNAPSHOT_VESSELS = 2_000
MAX_CONNECTIONS_PER_USER = 5
# Una conexión que no renueva su entrada en Redis en este tiempo se da por muerta (réplica caída).
CONNECTION_TTL_SECONDS = 90
HUB_RECONNECT_MAX_SECONDS = 30.0
# Espera de cada lectura de la suscripción: por debajo del timeout de socket de `create_redis`.
HUB_POLL_SECONDS = 0.5

logger = structlog.get_logger(__name__)


class LiveAuthError(Exception):
    """El token del primer mensaje no vale. `reason` va al log; el cliente solo ve `4401`."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class LiveUnavailableError(Exception):
    """La base no respondió (al autenticar o al preparar el snapshot)."""


async def authenticate(token: str, settings: Settings, sessions: SessionFactory) -> str:
    """Id del usuario dueño de un access token válido (mismas reglas que `get_current_user`)."""
    try:
        claims = decode_access_token(token, settings)
    except InvalidTokenError as error:
        raise LiveAuthError(f"token_{error}") from None
    try:
        async with sessions() as session:
            user = await UserRepository(session).get_by_id(claims.user_id)
    except (SQLAlchemyError, OSError) as error:
        logger.error("live_auth_unavailable", error=type(error).__name__)
        raise LiveUnavailableError from None
    if user is None:
        raise LiveAuthError("unknown_user")
    return str(user.id)


class ClientView:
    def __init__(self) -> None:
        self.viewport: BBox | None = None
        # Buques que el cliente tiene pintados (enviados en el snapshot o en un update).
        self._known: set[int] = set()
        self._pending: dict[int, LiveVessel] = {}
        self._removed: set[int] = set()

    def reset(self, viewport: BBox, snapshot: Sequence[LiveVessel]) -> None:
        """Nuevo viewport: el cliente sustituye lo que tenía por `snapshot`."""
        self.viewport = viewport
        self._known = {vessel.mmsi for vessel in snapshot}
        self._pending.clear()
        self._removed.clear()

    def add_known(self, vessels: Iterable[LiveVessel]) -> None:
        """El snapshot ya enviado: esos buques están pintados en el cliente."""
        self._known.update(vessel.mmsi for vessel in vessels)

    def offer(self, vessels: Iterable[LiveVessel]) -> None:
        """Posiciones recién publicadas por el worker."""
        if self.viewport is None:
            return  # sin `subscribe` todavía: no hay nada que enviar
        for vessel in vessels:
            mmsi = vessel.mmsi
            if self.viewport.contains(vessel.lon, vessel.lat):
                current = self._pending.get(mmsi)
                if current is None or vessel.ts >= current.ts:
                    self._pending[mmsi] = vessel
                self._removed.discard(mmsi)
            else:
                self._pending.pop(mmsi, None)
                if mmsi in self._known:
                    self._removed.add(mmsi)

    def drain(self) -> tuple[list[LiveVessel], list[int]]:
        """Lo que hay que enviar ahora (`update`, `remove`); deja el estado vacío."""
        updates = [self._pending[mmsi] for mmsi in sorted(self._pending)]
        removes = sorted(self._removed)
        self._known.update(self._pending)
        self._known.difference_update(self._removed)
        self._pending.clear()
        self._removed.clear()
        return updates, removes


async def snapshot(sessions: SessionFactory, viewport: BBox, *, now: datetime) -> list[LiveVessel]:
    """Estado inicial de un viewport: última posición de cada buque con señal reciente."""
    try:
        async with sessions() as session:
            records = await VesselRepository(session).latest_positions_in(
                min_lon=viewport.min_lon,
                min_lat=viewport.min_lat,
                max_lon=viewport.max_lon,
                max_lat=viewport.max_lat,
                since=now - LIVE_WINDOW,
                limit=MAX_SNAPSHOT_VESSELS,
            )
    except (SQLAlchemyError, OSError) as error:
        logger.error("live_snapshot_failed", error=type(error).__name__)
        raise LiveUnavailableError from None
    return [
        LiveVessel(
            mmsi=record.mmsi,
            lon=record.lon,
            lat=record.lat,
            cog=record.cog,
            sog=record.sog,
            # El 0 de AIS es "no disponible"; el formato en vivo solo admite de 1 a 99.
            ship_type=record.ship_type or None,
            name=record.name,
            ts=record.received_at,
        )
        for record in records
    ]


# --- Suscripción a Redis --------------------------------------------------------------------


@dataclass
class HubStats:
    subscribed: bool = False
    messages: int = 0
    invalid: int = 0
    failures: int = 0


class LiveHub:
    """Reparte las posiciones que el worker publica en Redis entre los clientes de esta réplica."""

    def __init__(
        self,
        redis: "Redis",
        *,
        reconnect_max_seconds: float = HUB_RECONNECT_MAX_SECONDS,
        rng: random.Random | None = None,
    ) -> None:
        self._redis = redis
        self._reconnect_max_seconds = reconnect_max_seconds
        self._rng = rng or random.Random()  # noqa: S311 (jitter, no criptografía)
        self._clients: set[ClientView] = set()
        self._task: asyncio.Task[None] | None = None
        self.stats = HubStats()

    @property
    def clients(self) -> int:
        return len(self._clients)

    def register(self, view: ClientView) -> None:
        self._clients.add(view)
        # Se suscribe con el primer cliente: una réplica sin clientes no escucha a Redis.
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="live-hub")

    def unregister(self, view: ClientView) -> None:
        self._clients.discard(view)

    def dispatch(self, data: bytes | str) -> None:
        """Un mensaje del canal: se valida (Redis es otro sistema) y se reparte."""
        try:
            update = LiveUpdate.model_validate_json(data)
        except ValidationError:
            self.stats.invalid += 1
            logger.warning("live_message_invalid", invalid=self.stats.invalid)
            return
        self.stats.messages += 1
        for view in tuple(self._clients):
            view.offer(update.vessels)

    async def _run(self) -> None:
        attempt = 0
        while True:
            try:
                async with self._redis.pubsub() as pubsub:
                    await pubsub.subscribe(LIVE_CHANNEL)
                    self.stats.subscribed = True
                    attempt = 0
                    logger.info("live_hub_subscribed")
                    while True:
                        message = await pubsub.get_message(
                            ignore_subscribe_messages=True, timeout=HUB_POLL_SECONDS
                        )
                        if message is not None and message.get("type") == "message":
                            self.dispatch(message["data"])
            except (RedisError, OSError, TimeoutError) as error:
                self.stats.subscribed = False
                self.stats.failures += 1
                # Sin datos en vivo, los clientes siguen conectados con su snapshot.
                ceiling = min(self._reconnect_max_seconds, 2.0 ** min(attempt, 10))
                delay = ceiling / 2 + self._rng.uniform(0, ceiling / 2)
                attempt += 1
                logger.warning(
                    "live_hub_disconnected",
                    error=type(error).__name__,
                    delay_seconds=round(delay, 3),
                )
                await asyncio.sleep(delay)

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self.stats.subscribed = False


# --- Límite de conexiones por usuario -------------------------------------------------------


class ConnectionLimiter:
    """Como mucho `max_per_user` conexiones abiertas por usuario entre todas las réplicas.

    Cada conexión es un miembro de un sorted set en Redis (`canal:ws:connections:<user_id>`)
    con la hora de su último latido. Las que no laten en `ttl_seconds` (réplica caída) dejan de
    contar solas. Si Redis no responde, se cuenta en memoria: el límite pasa a ser por réplica,
    pero no desaparece.
    """

    def __init__(
        self,
        redis: "Redis",
        *,
        max_per_user: int = MAX_CONNECTIONS_PER_USER,
        ttl_seconds: int = CONNECTION_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._redis = redis
        self._max_per_user = max_per_user
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._local: defaultdict[str, set[str]] = defaultdict(set)

    @staticmethod
    def _key(user_id: str) -> str:
        return f"{KEY_PREFIX}ws:connections:{user_id}"

    async def acquire(self, user_id: str, connection_id: str) -> bool:
        key = self._key(user_id)
        now = self._clock()
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(key, "-inf", now - self._ttl_seconds)
                pipe.zadd(key, {connection_id: now})
                pipe.zcard(key)
                pipe.expire(key, self._ttl_seconds)
                _, _, count, _ = await pipe.execute()
            if int(count) > self._max_per_user:
                await self._redis.zrem(key, connection_id)
                return False
            return True
        except (RedisError, OSError, TimeoutError) as error:
            logger.warning("ws_connection_limit_local", error=type(error).__name__)
            local = self._local[user_id]
            if len(local) >= self._max_per_user:
                return False
            local.add(connection_id)
            return True

    async def refresh(self, user_id: str, connection_id: str) -> None:
        """Latido: la conexión sigue viva."""
        if connection_id in self._local.get(user_id, ()):
            return
        key = self._key(user_id)
        with contextlib.suppress(RedisError, OSError, TimeoutError):
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.zadd(key, {connection_id: self._clock()})
                pipe.expire(key, self._ttl_seconds)
                await pipe.execute()

    async def release(self, user_id: str, connection_id: str) -> None:
        local = self._local.get(user_id)
        if local is not None and connection_id in local:
            local.discard(connection_id)
            if not local:
                del self._local[user_id]
            return
        with contextlib.suppress(RedisError, OSError, TimeoutError):
            await self._redis.zrem(self._key(user_id), connection_id)
