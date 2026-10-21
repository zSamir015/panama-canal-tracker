"""Router de administración: `/api/v1/admin/*` (AGENTS.md §8.3).

`require_admin` se aplica a nivel de router: cualquier endpoint que se añada aquí queda protegido
aunque su función no lo declare. Sin token → 401; rol `user` → 403. Cada acción se registra en el
log de auditoría (quién y qué; el cuándo lo pone el log).
"""

from http import HTTPStatus
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Request
from redis.asyncio import Redis

from app.core.auth import AdminUser, require_admin
from app.schemas.ingestion import IngestionStatusResponse
from app.services.ingestion import IngestionService

PROBLEM: dict[str, Any] = {"content": {"application/problem+json": {}}}

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])

audit = structlog.get_logger("audit")


def get_redis(request: Request) -> "Redis":
    redis: Redis = request.app.state.redis
    return redis


def get_ingestion_service(redis: Annotated["Redis", Depends(get_redis)]) -> IngestionService:
    return IngestionService(redis)


@router.get(
    "/ingestion/status",
    summary="Estado de la ingesta AIS",
    description=(
        "Lo que el worker publica en Redis cada 5 s: conexión con AISStream, último mensaje, "
        "reconexiones, cola, rechazos por motivo y contadores del writer. `available=false` si "
        "no hay estado (worker parado); `stale=true` si tiene más de 30 s."
    ),
    responses={
        HTTPStatus.SERVICE_UNAVAILABLE: {"description": "Redis no responde", **PROBLEM},
    },
)
async def ingestion_status(
    admin: AdminUser,
    service: Annotated[IngestionService, Depends(get_ingestion_service)],
) -> IngestionStatusResponse:
    audit.info("admin_action", action="ingestion_status_viewed", user_id=str(admin.id))
    return await service.status()
