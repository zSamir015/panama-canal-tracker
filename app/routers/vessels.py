"""Endpoints `/api/v1/vessels` (docs/API_DESIGN.md "Vessels").

Cuelga del router protegido de `app/main.py`: exige access token y aplica el límite general de
peticiones. Los datos de buques son de lectura para cualquier usuario autenticado (§8.5).
"""

from http import HTTPStatus
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query

from app.core.db import DbSession
from app.schemas.vessels import (
    DEFAULT_REPORTED_DAYS,
    CanalBoundFilters,
    CanalBoundPageResponse,
    CanalBoundVesselResponse,
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


# Antes de `/{mmsi}`: si no, "canal-bound" se tomaría por un MMSI (y daría 422).
@router.get(
    "/canal-bound",
    summary="Buques con destino al Canal",
    description=(
        "Buques de cualquier parte del mundo cuyo destino AIS declarado es el Canal de Panamá o "
        "uno de sus puertos, con su última posición conocida y la ETA declarada. Orden: ETA "
        "próximas primero; después las vencidas hace más de un día (suelen ser datos sin "
        "actualizar) y al final los buques sin ETA. Solo aparecen los que lo **declaran** y "
        "están al alcance de un receptor terrestre de AISStream (ADR-0009). `port` filtra por "
        "UN/LOCODE (`PABLB`, `PACTB`...; `PA` = solo Panamá). Por defecto, informes de los últimos "
        f"{DEFAULT_REPORTED_DAYS} días (`reported_since`, máx. 90). `size` máximo: 200."
    ),
    responses={HTTPStatus.UNPROCESSABLE_ENTITY: {"description": "Parámetros inválidos", **PROBLEM}},
)
async def list_canal_bound(
    filters: Annotated[CanalBoundFilters, Query()], service: Service
) -> CanalBoundPageResponse:
    page = await service.canal_bound(
        page=filters.page,
        size=filters.size,
        default_days=DEFAULT_REPORTED_DAYS,
        port=filters.port,
        reported_since=filters.reported_since,
    )
    return CanalBoundPageResponse(
        items=[CanalBoundVesselResponse.model_validate(item) for item in page.items],
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
