"""Endpoints `/api/v1/stats` (docs/API_DESIGN.md "Stats").

Cuelga del router protegido de `app/main.py`: exige access token y aplica el límite general de
peticiones. Las estadísticas son de lectura para cualquier usuario autenticado (§8.5).
"""

from datetime import UTC, datetime
from http import HTTPStatus
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.core.db import DbSession
from app.schemas.stats import (
    DEFAULT_WINDOW_DAYS,
    MAX_WINDOW_DAYS,
    DailyItem,
    DailyStatsResponse,
    Distribution,
    StatsWindow,
    TransitDurationsResponse,
    WaitingTimesResponse,
)
from app.services.stats import StatsService, Summary

PROBLEM: dict[str, Any] = {"content": {"application/problem+json": {}}}
INVALID_WINDOW: dict[int | str, dict[str, Any]] = {
    HTTPStatus.UNPROCESSABLE_ENTITY: {"description": "Ventana inválida", **PROBLEM}
}
WINDOW_HELP = (
    f"Ventana `from`/`to` (con zona; por defecto, los últimos {DEFAULT_WINDOW_DAYS} días; como "
    f"mucho {MAX_WINDOW_DAYS} días entre ambos)."
)

router = APIRouter(prefix="/stats", tags=["stats"])


def get_stats_service(session: DbSession) -> StatsService:
    return StatsService(session)


Service = Annotated[StatsService, Depends(get_stats_service)]


def distribution(row: Summary) -> Distribution:
    return Distribution(
        count=row.count, mean_minutes=row.mean, p50_minutes=row.p50, p90_minutes=row.p90
    )


@router.get(
    "/daily",
    summary="Tránsitos por día",
    description=(
        "Tránsitos completados por día (UTC, el de la salida del Canal), sentido y categoría de "
        "buque (`cargo`, `tanker`, `passenger`, `tug`, `fishing`, `pleasure`, `other`, "
        "`unknown`: las del mapa). Solo salen las combinaciones con algún tránsito, ordenadas "
        f"por día. {WINDOW_HELP}"
    ),
    responses=INVALID_WINDOW,
)
async def daily_stats(
    window: Annotated[StatsWindow, Query()], service: Service
) -> DailyStatsResponse:
    start, end = window.window(datetime.now(UTC))
    rows = await service.daily(start, end)
    return DailyStatsResponse(
        start=start,
        end=end,
        items=[
            DailyItem(
                day=row.day,
                direction=row.direction,
                ship_category=row.ship_category,
                transits=row.transits,
            )
            for row in rows
        ],
    )


@router.get(
    "/transit-durations",
    summary="Duración de los tránsitos",
    description=(
        "Duración (media, mediana y percentil 90, en minutos) de los tránsitos completados que "
        "salieron del Canal en la ventana, en total y por sentido. Con ninguno, `count` es 0 y "
        f"el resto `null`. {WINDOW_HELP}"
    ),
    responses=INVALID_WINDOW,
)
async def transit_durations(
    window: Annotated[StatsWindow, Query()], service: Service
) -> TransitDurationsResponse:
    start, end = window.window(datetime.now(UTC))
    result = await service.transit_durations(start, end)
    return TransitDurationsResponse(
        start=start,
        end=end,
        overall=distribution(result.overall),
        by_direction={key: distribution(row) for key, row in result.by_key.items()},
    )


@router.get(
    "/waiting-times",
    summary="Espera en fondeo antes de entrar",
    description=(
        "Espera en fondeo (media, mediana y percentil 90, en minutos) de los tránsitos que "
        "empezaron en la ventana y tienen una visita a un fondeadero enlazada: desde que el "
        "buque llegó al fondeadero hasta que entró al Canal. En total y por fondeadero. "
        f"Cuenta también los tránsitos abortados. {WINDOW_HELP}"
    ),
    responses=INVALID_WINDOW,
)
async def waiting_times(
    window: Annotated[StatsWindow, Query()], service: Service
) -> WaitingTimesResponse:
    start, end = window.window(datetime.now(UTC))
    result = await service.waiting_times(start, end)
    return WaitingTimesResponse(
        start=start,
        end=end,
        overall=distribution(result.overall),
        by_anchorage={key: distribution(row) for key, row in result.by_key.items()},
    )
