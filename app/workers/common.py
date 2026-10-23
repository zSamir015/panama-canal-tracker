"""Piezas compartidas por los consumers (3.3, #59) y los writers (3.4, #59) del worker AIS."""

import asyncio
import random

from app.services.ais_parser import PositionUpdate, VesselStatic

BACKOFF_BASE_SECONDS = 1.0

# Lo que el consumer deja en la cola y el writer guarda.
AisRecord = PositionUpdate | VesselStatic


def backoff_delay(
    attempt: int, *, cap: float, rng: random.Random, base: float = BACKOFF_BASE_SECONDS
) -> float:
    """Espera antes del reintento `attempt` (0 = el primero): exponencial con jitter.

    El techo se duplica en cada intento hasta `cap`, y la espera es un valor aleatorio entre la
    mitad del techo y el techo ("equal jitter"). Así nunca se reintenta al instante y, si caen
    muchos clientes a la vez, no vuelven todos en el mismo segundo.
    """
    ceiling = min(cap, base * 2.0 ** min(attempt, 30))
    return ceiling / 2 + rng.uniform(0, ceiling / 2)


async def collect_batch[T](
    queue: asyncio.Queue[T], stop: asyncio.Event, *, batch_size: int, flush_seconds: float
) -> list[T]:
    """Junta registros hasta llenar el lote o agotar el plazo desde el primero.

    Con `stop` activo no espera: recoge lo que quede en la cola para vaciarla antes de salir.
    """
    loop = asyncio.get_running_loop()
    records: list[T] = []
    deadline: float | None = None
    while len(records) < batch_size:
        if stop.is_set():
            try:
                records.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                break
            queue.task_done()
            continue
        timeout = flush_seconds if deadline is None else deadline - loop.time()
        if timeout <= 0:
            break
        record = await next_record(queue, stop, timeout)
        if record is None:
            if stop.is_set():
                continue  # vaciar la cola sin esperar (rama de arriba)
            break  # plazo agotado
        records.append(record)
        if deadline is None:
            deadline = loop.time() + flush_seconds
    return records


async def next_record[T](
    queue: asyncio.Queue[T], stop: asyncio.Event, wait_seconds: float
) -> T | None:
    """El siguiente registro, o None si vence el plazo o se activa `stop` antes."""
    getter = asyncio.ensure_future(queue.get())
    stopper = asyncio.ensure_future(stop.wait())
    try:
        await asyncio.wait(
            {getter, stopper}, timeout=wait_seconds, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        stopper.cancel()
        getter.cancel()
    # `get` pudo terminar justo a la vez que `stop`: ese registro no se puede perder.
    if getter.done() and not getter.cancelled():
        queue.task_done()
        return getter.result()
    return None
