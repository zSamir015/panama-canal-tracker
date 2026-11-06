"""Enlace entre visitas a un fondeadero y el tránsito siguiente (tarea 6.2). Lógica pura.

El tiempo de espera real de un tránsito es lo que el buque esperó en el fondeadero antes de
entrar: desde la llegada (`arrived_at`) hasta la entrada al Canal (`entered_at`). Para saberlo hay
que decidir qué visita precede a qué tránsito. Las reglas:

- el fondeadero tiene que ser el del lado por el que el buque entra: el del Atlántico para un
  tránsito `southbound` y el del Pacífico para uno `northbound`;
- la visita empieza antes que el tránsito y termina (si ya terminó) antes de que empiece, con
  `CLOCK_TOLERANCE` de margen: el worker cierra la visita y abre el tránsito en pasos distintos y
  la hora de uno puede quedar un poco por detrás de la del otro;
- no pueden haber pasado más de `MAX_WAIT_GAP` entre que el buque se fue del fondeadero y entró al
  Canal: pasado ese tiempo, la espera no es la de ese tránsito;
- un tránsito se enlaza con **una** visita, la más reciente que cumpla lo anterior, y cada visita
  con **un** tránsito, el primero que empiece después de ella.

Sin base de datos: `TransitRepository` y `AnchorageRepository` aportan los candidatos y el
`AnchorageTracker` aplica el resultado.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

MAX_WAIT_GAP = timedelta(hours=24)
CLOCK_TOLERANCE = timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class VisitCandidate:
    id: UUID
    mmsi: int
    anchorage: str  # `atlantic` o `pacific`
    arrived_at: datetime
    departed_at: datetime | None


@dataclass(frozen=True, slots=True)
class TransitCandidate:
    id: UUID
    mmsi: int
    direction: str  # `southbound` o `northbound`
    entered_at: datetime


def entry_side(direction: str) -> str:
    """Fondeadero por el que se espera para un tránsito con este sentido."""
    return "atlantic" if direction == "southbound" else "pacific"


def precedes(visit: VisitCandidate, transit: TransitCandidate) -> bool:
    """Si la visita puede ser la espera previa de este tránsito (mismo buque, ver las reglas)."""
    if visit.mmsi != transit.mmsi or visit.anchorage != entry_side(transit.direction):
        return False
    if visit.arrived_at >= transit.entered_at:
        return False
    if visit.departed_at is None:
        return True
    if visit.departed_at > transit.entered_at + CLOCK_TOLERANCE:
        return False
    return transit.entered_at - visit.departed_at <= MAX_WAIT_GAP


def match_visits_to_transits(
    visits: Sequence[VisitCandidate], transits: Sequence[TransitCandidate]
) -> list[tuple[UUID, UUID]]:
    """Pares `(visita, tránsito)` a enlazar. Cada visita y cada tránsito salen como mucho una vez.

    Las visitas se reparten de la más reciente a la más antigua: así, con dos esperas seguidas
    antes de un tránsito, la última es la que lo precede y la anterior se queda sin enlazar.
    """
    by_vessel: dict[int, list[TransitCandidate]] = defaultdict(list)
    for transit in sorted(transits, key=lambda item: item.entered_at):
        by_vessel[transit.mmsi].append(transit)

    pairs: list[tuple[UUID, UUID]] = []
    for visit in sorted(visits, key=lambda item: (item.arrived_at, str(item.id)), reverse=True):
        available = by_vessel.get(visit.mmsi, [])
        match = next((transit for transit in available if precedes(visit, transit)), None)
        if match is not None:
            available.remove(match)
            pairs.append((visit.id, match.id))
    return pairs
