"""Endpoints `/api/v1/transits` (docs/API_DESIGN.md "Transits").

Cuelga del router protegido de `app/main.py`: exige access token y aplica el límite general de
peticiones. Los tránsitos son de lectura para cualquier usuario autenticado (§8.5).
"""

from datetime import UTC, datetime
from http import HTTPStatus
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query

from app.core.db import DbSession
from app.schemas.transits import (
    DEFAULT_WINDOW_DAYS,
    MAX_CURRENT,
    MAX_WINDOW_DAYS,
    AnchorageWaitResponse,
    CurrentTransitsResponse,
    TransitDetailResponse,
    TransitFilters,
    TransitPageResponse,
    TransitResponse,
)
from app.services.transits import TransitService

PROBLEM: dict[str, Any] = {"content": {"application/problem+json": {}}}

router = APIRouter(prefix="/transits", tags=["transits"])


def get_transit_service(session: DbSession) -> TransitService:
    return TransitService(session)


Service = Annotated[TransitService, Depends(get_transit_service)]


@router.get(
    "",
    summary="Histórico de tránsitos",
    description=(
        "Lista paginada de tránsitos del Canal detectados a partir de AIS, los que entraron más "
        "recientemente primero. Filtros opcionales: `direction` (`southbound` = Atlántico a "
        "Pacífico), `status` y la ventana de entrada `from`/`to` (con zona; por defecto, los "
        f"últimos {DEFAULT_WINDOW_DAYS} días; como mucho {MAX_WINDOW_DAYS} días entre ambos). "
        "`size` máximo: 200."
    ),
    responses={HTTPStatus.UNPROCESSABLE_ENTITY: {"description": "Parámetros inválidos", **PROBLEM}},
)
async def list_transits(
    filters: Annotated[TransitFilters, Query()], service: Service
) -> TransitPageResponse:
    start, end = filters.window(datetime.now(UTC))
    page = await service.list(
        page=filters.page,
        size=filters.size,
        entered_from=start,
        entered_to=end,
        direction=filters.direction,
        status=filters.status,
    )
    return TransitPageResponse(
        items=[TransitResponse.model_validate(item) for item in page.items],
        total=page.total,
        page=page.page,
        size=page.size,
    )


# Antes de `/{transit_id}`: si no, "current" se tomaría por un id (y daría 422).
@router.get(
    "/current",
    summary="Tránsitos en curso",
    description=(
        "Los tránsitos `in_progress`: buques que entraron por una entrada del Canal y todavía no "
        "han salido por la otra. Como mucho uno por buque; el que entró antes, primero. Sin "
        f"paginación: se devuelven como mucho {MAX_CURRENT} y `total` dice cuántos hay."
    ),
)
async def current_transits(service: Service) -> CurrentTransitsResponse:
    current = await service.current(limit=MAX_CURRENT)
    return CurrentTransitsResponse(
        items=[TransitResponse.model_validate(item) for item in current.items],
        total=current.total,
    )


@router.get(
    "/{transit_id}",
    summary="Detalle de un tránsito",
    description=(
        "Un tránsito con los datos del buque y, si se detectó, la espera en fondeo previa "
        "(`anchorage_wait`): fondeadero, llegada, salida y minutos hasta que el buque entró al "
        "Canal. Es `null` si no se vio al buque esperando."
    ),
    responses={
        HTTPStatus.NOT_FOUND: {"description": "Tránsito no encontrado", **PROBLEM},
        HTTPStatus.UNPROCESSABLE_ENTITY: {"description": "Id inválido (UUID)", **PROBLEM},
    },
)
async def get_transit(
    transit_id: Annotated[UUID, Path(description="Id del tránsito (UUID)")], service: Service
) -> TransitDetailResponse:
    detail = await service.get(transit_id)
    wait = detail.wait
    return TransitDetailResponse(
        **TransitResponse.model_validate(detail.transit).model_dump(),
        anchorage_wait=(
            AnchorageWaitResponse(
                anchorage=wait.anchorage,
                arrived_at=wait.arrived_at,
                departed_at=wait.departed_at,
                wait_minutes=round(
                    (detail.transit.entered_at - wait.arrived_at).total_seconds() / 60
                ),
            )
            if wait
            else None
        ),
    )
