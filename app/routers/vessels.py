"""Endpoints `/api/v1/vessels` (docs/API_DESIGN.md "Vessels").

Cuelga del router protegido de `app/main.py`: exige access token y aplica el límite general de
peticiones. Los datos de buques son de lectura para cualquier usuario autenticado (§8.5).
"""

from http import HTTPStatus
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query

from app.core.db import DbSession
from app.schemas.vessels import (
    Mmsi,
    PositionResponse,
    VesselDetailResponse,
    VesselFilters,
    VesselPageResponse,
    VesselResponse,
)
from app.services.vessels import VesselService

PROBLEM: dict[str, Any] = {"content": {"application/problem+json": {}}}

router = APIRouter(prefix="/vessels", tags=["vessels"])


def get_vessel_service(session: DbSession) -> VesselService:
    return VesselService(session)


Service = Annotated[VesselService, Depends(get_vessel_service)]


@router.get(
    "",
    summary="Buques vistos",
    description=(
        "Lista paginada de buques, los vistos más recientemente primero. Filtros opcionales por "
        "tipo AIS (`ship_type`) y por última señal (`seen_since`, máx. 90 días atrás). "
        "`size` máximo: 200."
    ),
    responses={HTTPStatus.UNPROCESSABLE_ENTITY: {"description": "Parámetros inválidos", **PROBLEM}},
)
async def list_vessels(
    filters: Annotated[VesselFilters, Query()], service: Service
) -> VesselPageResponse:
    page = await service.list(
        page=filters.page,
        size=filters.size,
        ship_type=filters.ship_type,
        seen_since=filters.seen_since,
    )
    return VesselPageResponse(
        items=[VesselResponse.model_validate(item) for item in page.items],
        total=page.total,
        page=page.page,
        size=page.size,
    )


@router.get(
    "/{mmsi}",
    summary="Ficha de un buque",
    description="Datos estáticos del buque y su última posición conocida (`null` si no tiene).",
    responses={
        HTTPStatus.NOT_FOUND: {"description": "Buque no encontrado", **PROBLEM},
        HTTPStatus.UNPROCESSABLE_ENTITY: {"description": "MMSI inválido (9 dígitos)", **PROBLEM},
    },
)
async def get_vessel(
    mmsi: Annotated[Mmsi, Path(description="MMSI de 9 dígitos")], service: Service
) -> VesselDetailResponse:
    detail = await service.get(mmsi)
    return VesselDetailResponse(
        **VesselResponse.model_validate(detail.vessel).model_dump(),
        last_position=(
            PositionResponse.model_validate(detail.last_position) if detail.last_position else None
        ),
    )
