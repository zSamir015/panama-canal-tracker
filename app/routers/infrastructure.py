"""Endpoints de infraestructura en la raíz: `/ready` y `/metrics` (tarea 7.1).

Los usan el orquestador y Prometheus, no los clientes de la API, así que van fuera de `/api/v1`
(docs/API_DESIGN.md). `/health` está en `app/main.py`.
"""

from http import HTTPStatus
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from redis.asyncio import Redis

from app.core.auth import require_metrics_token
from app.core.db import SessionFactory
from app.schemas import examples
from app.schemas.examples import with_example
from app.services.metrics import CONTENT_TYPE, MetricsService, readiness, render

router = APIRouter(tags=["infrastructure"])


@with_example(examples.READY)
class ReadyResponse(BaseModel):
    status: Literal["ready", "unavailable"]
    checks: dict[Literal["database", "redis"], Literal["ok", "failed"]]


def _redis(request: Request) -> "Redis":
    redis: Redis = request.app.state.redis
    return redis


def _session_factory(request: Request) -> SessionFactory:
    factory: SessionFactory = request.app.state.session_factory
    return factory


@router.get(
    "/ready",
    summary="La app está lista para recibir tráfico",
    description=(
        "Comprueba que la base de datos y Redis responden (máx. 2 s cada una). `200` si las dos "
        "van bien, `503` si alguna falla; el cuerpo dice cuál, sin detalles internos. Es público "
        "y no lleva datos: lo usa el orquestador. `/health` solo dice que el proceso vive."
    ),
    response_model=ReadyResponse,
    responses={
        HTTPStatus.SERVICE_UNAVAILABLE: {
            "model": ReadyResponse,
            "description": "Alguna dependencia falla",
            "content": {"application/json": {"example": examples.READY_UNAVAILABLE}},
        }
    },
)
async def ready(
    response: Response,
    session_factory: Annotated[SessionFactory, Depends(_session_factory)],
    redis: Annotated["Redis", Depends(_redis)],
) -> ReadyResponse:
    result = await readiness(session_factory, redis)
    if not result.ready:
        response.status_code = HTTPStatus.SERVICE_UNAVAILABLE
    return ReadyResponse(
        status="ready" if result.ready else "unavailable",
        checks={
            "database": "ok" if result.database else "failed",
            "redis": "ok" if result.redis else "failed",
        },
    )


@router.get(
    "/metrics",
    summary="Métricas para Prometheus",
    description=(
        "Formato de texto de Prometheus. Exige `Authorization: Bearer <METRICS_TOKEN>` (el token "
        "estático de la configuración, no un JWT de usuario); sin token configurado responde 401 "
        "siempre. No debe exponerse a Internet: el proxy tiene que bloquearlo además. Si la base "
        "o Redis no responden, sus métricas se omiten y `canal_dependency_up` lo indica."
    ),
    response_class=Response,
    responses={
        HTTPStatus.OK: {
            "content": {"text/plain": {"example": examples.METRICS_TEXT}},
            "description": "Métricas",
        },
        HTTPStatus.UNAUTHORIZED: {
            "description": "No autenticado",
            "content": {"application/problem+json": {}},
        },
    },
    dependencies=[Depends(require_metrics_token)],
)
async def metrics(
    session_factory: Annotated[SessionFactory, Depends(_session_factory)],
    redis: Annotated["Redis", Depends(_redis)],
) -> Response:
    collected = await MetricsService(session_factory, redis).collect()
    return Response(content=render(collected), media_type=CONTENT_TYPE)
