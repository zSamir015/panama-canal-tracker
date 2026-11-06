"""Prueba de carga de `WS /ws/live` (tarea 4.8).

Abre muchos clientes WebSocket a la vez contra una API local, con tráfico del simulador AIS
corriendo, y mide si el WebSocket aguanta y si la ingesta se degrada.

Cada usuario puede tener `MAX_CONNECTIONS_PER_USER` sockets (5), así que 500 clientes necesitan
100 usuarios. El script crea esos usuarios directamente en la base (con `DATABASE_URL` de `.env`,
como `scripts/create_admin.py`), acuña un access token por usuario y los borra al terminar. No
pasa por `/auth/login` a propósito: ese endpoint tiene límite por IP y la prueba mide el
WebSocket, no el login. La contraseña de los usuarios es aleatoria y nadie la conoce.

    python scripts/ws_load_test.py --clients 500 --duration 60 --api-pid <pid-de-uvicorn>

Mide: conexiones logradas y fallidas (con su código de cierre), tiempo hasta el primer snapshot,
mensajes recibidos por segundo y, con `--api-pid`, CPU y memoria de la API. La ingesta se mide
como filas nuevas por segundo en `positions` antes de abrir los clientes y mientras están abiertos.
"""

import argparse
import asyncio
import json
import secrets
import statistics
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import delete, func, select
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed
from websockets.typing import Origin

from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.core.security import create_access_token, hash_password
from app.models.position import Position
from app.models.user import User, UserRole
from app.repositories.user import UserRepository

EMAIL_DOMAIN = "loadtest.invalid"
CONNECTIONS_PER_USER = 5
# Bbox del Canal de Panamá (lon mín, lat mín, lon máx, lat máx).
CANAL_BBOX = (-80.2, 8.8, -79.4, 9.5)


@dataclass
class ClientResult:
    connected: bool = False
    close_code: int | None = None
    error: str | None = None
    first_snapshot_s: float | None = None
    messages: int = 0
    gaps_s: list[float] = field(default_factory=list)


async def create_users(count: int) -> list[UUID]:
    """Crea `count` usuarios de prueba. Un solo hash: la contraseña no se usa para entrar."""
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    hashed = hash_password(secrets.token_urlsafe(24))
    ids: list[UUID] = []
    try:
        async with sessions() as session:
            users = UserRepository(session)
            for index in range(count):
                user = await users.add(
                    email=f"ws-load-{index:03d}@{EMAIL_DOMAIN}",
                    hashed_password=hashed,
                    role=UserRole.USER,
                )
                ids.append(user.id)
            await session.commit()
    finally:
        await engine.dispose()
    return ids


async def delete_users() -> int:
    engine = create_engine(get_settings())
    sessions = create_session_factory(engine)
    try:
        async with sessions() as session:
            result = await session.execute(delete(User).where(User.email.like(f"%@{EMAIL_DOMAIN}")))
            await session.commit()
            return int(getattr(result, "rowcount", 0) or 0)
    finally:
        await engine.dispose()


async def count_positions() -> int:
    engine = create_engine(get_settings())
    sessions = create_session_factory(engine)
    try:
        async with sessions() as session:
            return int(
                (await session.execute(select(func.count()).select_from(Position))).scalar_one()
            )
    finally:
        await engine.dispose()


async def ingest_rate(seconds: float) -> float:
    """Filas nuevas por segundo en `positions` durante `seconds`."""
    before = await count_positions()
    started = time.monotonic()
    await asyncio.sleep(seconds)
    after = await count_positions()
    return (after - before) / (time.monotonic() - started)


async def run_client(
    url: str, origin: str, token: str, stop_at: float, result: ClientResult
) -> None:
    started = time.monotonic()
    try:
        async with connect(url, origin=Origin(origin), open_timeout=30, max_size=2**20) as socket:
            await socket.send(json.dumps({"type": "auth", "token": token}))
            await socket.send(json.dumps({"type": "subscribe", "bbox": list(CANAL_BBOX)}))
            result.connected = True
            last = time.monotonic()
            while time.monotonic() < stop_at:
                try:
                    raw = await asyncio.wait_for(
                        socket.recv(), timeout=max(0.1, stop_at - time.monotonic())
                    )
                except TimeoutError:
                    break
                now = time.monotonic()
                if result.messages == 0:
                    result.first_snapshot_s = now - started
                else:
                    result.gaps_s.append(now - last)
                last = now
                result.messages += 1
                json.loads(raw)  # el cliente real también interpreta el mensaje
    except ConnectionClosed as closed:
        result.close_code = closed.rcvd.code if closed.rcvd else None
    except Exception as error:
        result.error = type(error).__name__


def process_stats(pid: int) -> tuple[float, float] | None:
    """(%CPU, RSS en MB) del proceso, con `ps`. None si ya no existe."""
    # Ruta fija y PID numérico: no hay entrada de texto que inyectar.
    command = ["/bin/ps", "-o", "pcpu=,rss=", "-p", str(int(pid))]
    out = subprocess.run(command, capture_output=True, text=True, check=False).stdout.split()  # noqa: S603
    if len(out) != 2:
        return None
    return float(out[0]), int(out[1]) / 1024


async def sample_process(pid: int, stop: asyncio.Event, samples: list[tuple[float, float]]) -> None:
    while not stop.is_set():
        stats = process_stats(pid)
        if stats is not None:
            samples.append(stats)
        try:
            await asyncio.wait_for(stop.wait(), timeout=2)
        except TimeoutError:
            pass


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * pct))]


async def main_async(args: argparse.Namespace) -> int:
    settings = get_settings()
    origin = settings.cors_origins[0] if settings.cors_origins else "http://localhost:5173"
    user_count = -(-args.clients // CONNECTIONS_PER_USER)
    print(f"Creando {user_count} usuarios de prueba…")
    await delete_users()  # restos de una ejecución interrumpida
    user_ids = await create_users(user_count)
    try:
        tokens = [create_access_token(user_id, settings)[0] for user_id in user_ids]
        print(f"Midiendo la ingesta sin clientes durante {args.baseline}s…")
        baseline = await ingest_rate(args.baseline)

        results = [ClientResult() for _ in range(args.clients)]
        stop_at = time.monotonic() + args.ramp + args.duration
        samples: list[tuple[float, float]] = []
        stop_sampling = asyncio.Event()
        sampler = (
            asyncio.create_task(sample_process(args.api_pid, stop_sampling, samples))
            if args.api_pid
            else None
        )
        under_load = asyncio.create_task(ingest_rate(args.ramp + args.duration))

        print(
            f"Abriendo {args.clients} clientes en {args.ramp}s y manteniéndolos {args.duration}s…"
        )
        tasks = []
        for index, result in enumerate(results):
            token = tokens[index // CONNECTIONS_PER_USER]
            tasks.append(asyncio.create_task(run_client(args.url, origin, token, stop_at, result)))
            await asyncio.sleep(args.ramp / args.clients)
        await asyncio.gather(*tasks)
        loaded = await under_load
        stop_sampling.set()
        if sampler:
            await sampler
    finally:
        removed = await delete_users()
        print(f"Usuarios de prueba borrados: {removed}")

    connected = [r for r in results if r.connected]
    failures = Counter(
        f"close {r.close_code}" if r.close_code is not None else (r.error or "sin mensajes")
        for r in results
        if not r.connected or r.messages == 0
    )
    firsts = [r.first_snapshot_s for r in results if r.first_snapshot_s is not None]
    gaps = [gap for r in results for gap in r.gaps_s]
    messages = sum(r.messages for r in results)
    report = {
        "clients_requested": args.clients,
        "clients_connected": len(connected),
        "clients_with_snapshot": len(firsts),
        "failures": dict(failures),
        "first_snapshot_s": {
            "p50": round(statistics.median(firsts), 3) if firsts else None,
            "p95": round(percentile(firsts, 0.95), 3) if firsts else None,
            "max": round(max(firsts), 3) if firsts else None,
        },
        "message_gap_s": {
            "p50": round(statistics.median(gaps), 3) if gaps else None,
            "p95": round(percentile(gaps, 0.95), 3) if gaps else None,
            "max": round(max(gaps), 3) if gaps else None,
        },
        "messages_total": messages,
        "ingest_rows_per_s": {"baseline": round(baseline, 2), "under_load": round(loaded, 2)},
    }
    if samples:
        report["api_process"] = {
            "cpu_pct_max": round(max(s[0] for s in samples), 1),
            "cpu_pct_mean": round(statistics.mean(s[0] for s in samples), 1),
            "rss_mb_max": round(max(s[1] for s in samples), 1),
        }
    print(json.dumps(report, indent=2))
    return 0 if len(firsts) == args.clients else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prueba de carga de /ws/live.")
    parser.add_argument("--url", default="ws://127.0.0.1:8000/ws/live")
    parser.add_argument("--clients", type=int, default=500)
    parser.add_argument("--duration", type=int, default=60, help="segundos con todos conectados")
    parser.add_argument(
        "--ramp", type=int, default=20, help="segundos para abrir todos los clientes"
    )
    parser.add_argument("--baseline", type=int, default=20, help="segundos de ingesta sin clientes")
    parser.add_argument("--api-pid", type=int, default=None, help="PID de uvicorn, para CPU y RAM")
    return asyncio.run(main_async(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
