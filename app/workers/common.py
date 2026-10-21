"""Piezas compartidas por el consumer (3.3) y el writer (3.4) del worker AIS."""

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
