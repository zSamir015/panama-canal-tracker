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
from app.routers import admin, auth


def create_app(settings: Settings | None = None) -> FastAPI:
    """Crea y configura la aplicación HTTP."""
    settings = get_settings() if settings is None else settings
    configure_logging(settings.log_level)

    engine = create_engine(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            # Devuelve las conexiones abiertas a PostgreSQL antes de que el proceso termine.
            await engine.dispose()

    app = FastAPI(title="Panama Canal Tracker", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
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
    api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(get_current_user)])
    api_router.include_router(auth.router)
    api_router.include_router(admin.router)
    app.include_router(api_router)

    public_api_router = APIRouter(prefix="/api/v1")
    public_api_router.include_router(auth.public_router)
    app.include_router(public_api_router)

    @app.get("/health", tags=["infrastructure"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("app.main:app", log_config=None)
