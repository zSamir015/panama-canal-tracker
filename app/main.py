"""Punto de entrada de la API FastAPI."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import APIRouter, Depends, FastAPI

from app.core.auth import get_current_user
from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_session_factory
from app.core.errors import register_exception_handlers
from app.core.headers import REQUEST_ID_HEADER
from app.core.logging import configure_logging
from app.core.middleware import (
    BodySizeLimitMiddleware,
    HardenedCORSMiddleware,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.rate_limit import AppRateLimiter, create_storage, limit_api_by_user
from app.core.redis import create_redis
from app.routers import admin, auth, live, vessels
from app.routers.live import MAX_CLIENT_MESSAGE_BYTES
from app.services.live import ConnectionLimiter, LiveHub


def create_app(settings: Settings | None = None) -> FastAPI:
    """Crea y configura la aplicación HTTP."""
    settings = get_settings() if settings is None else settings
    configure_logging(settings.log_level)

    engine = create_engine(settings)
    # Lectura del estado del worker (3.9) y posiciones en vivo (4.2). No conecta hasta usarse.
    redis = create_redis(settings)
    live_hub = LiveHub(redis)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            # Devuelve las conexiones abiertas a PostgreSQL y Redis antes de terminar.
            await live_hub.close()
            await engine.dispose()
            await redis.aclose()

    app = FastAPI(title="Panama Canal Tracker", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.redis = redis
    app.state.session_factory = create_session_factory(engine)
    app.state.rate_limiter = AppRateLimiter(create_storage(settings))
    app.state.live_hub = live_hub
    app.state.ws_limiter = ConnectionLimiter(redis)
    register_exception_handlers(app)

    # El último middleware añadido es el más externo:
    # RequestId → cabeceras de seguridad → CORS → límite de body.
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(
        HardenedCORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        # Para que el frontend pueda leer el id y mostrarlo en un error.
        expose_headers=[REQUEST_ID_HEADER],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)

    # Denegar por defecto (AGENTS.md §8.9): todo lo que cuelga de este router exige un access token
    # válido. Las rutas públicas de la lista blanca van en `public_api_router`, para que abrir
    # una ruta sea siempre una decisión explícita.
    api_router = APIRouter(
        prefix="/api/v1",
        dependencies=[Depends(get_current_user), Depends(limit_api_by_user)],
    )
    api_router.include_router(auth.router)
    api_router.include_router(vessels.router)
    api_router.include_router(admin.router)
    app.include_router(api_router)

    # `/ws/live` autentica con su primer mensaje (el navegador no puede mandar `Authorization`
    # en un WebSocket): no cuelga de `api_router`. Lo cubren sus propios tests de auth.
    app.include_router(live.router)

    public_api_router = APIRouter(prefix="/api/v1")
    public_api_router.include_router(auth.public_router)
    app.include_router(public_api_router)

    @app.get("/health", tags=["infrastructure"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

# uvicorn corta antes los frames enormes (el router además rechaza los de más de 4 KB). Margen
# para la cabecera del frame y la compresión.
WS_MAX_SIZE_BYTES = 2 * MAX_CLIENT_MESSAGE_BYTES


if __name__ == "__main__":
    uvicorn.run("app.main:app", log_config=None, ws_max_size=WS_MAX_SIZE_BYTES)
