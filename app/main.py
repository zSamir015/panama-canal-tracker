"""Punto de entrada de la API FastAPI."""

import uvicorn
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import BodySizeLimitMiddleware, RequestIdMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    """Crea y configura la aplicación HTTP."""
    settings = get_settings() if settings is None else settings
    configure_logging(settings.log_level)

    app = FastAPI(title="Panama Canal Tracker")
    register_exception_handlers(app)

    # El último middleware añadido es el más externo: RequestId → CORS → límite de body.
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.add_middleware(RequestIdMiddleware)

    api_router = APIRouter(prefix="/api/v1")
    app.include_router(api_router)

    @app.get("/health", tags=["infrastructure"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("app.main:app", log_config=None)
