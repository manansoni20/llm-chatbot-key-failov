"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import init_db
from app.routers.chat import router as chat_router
from app.routers.health import router as health_router
from app.services.llm_service import init_llm_cache

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Initialize SQLite tables and LiteLLM response cache on startup."""
    init_db()
    init_llm_cache(get_settings())
    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @application.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # Starlette's ServerErrorMiddleware sits outside CORSMiddleware, so attach
        # explicit CORS headers for allowed origins if an unhandled error occurs.
        logger.error("Unhandled exception in request (%s)", type(exc).__name__)
        headers: dict[str, str] = {"Vary": "Origin"}
        origin = request.headers.get("origin")
        if origin and origin in settings.allowed_origins_list:
            headers["Access-Control-Allow-Origin"] = origin
            headers["Access-Control-Allow-Credentials"] = "true"
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
            headers=headers,
        )

    application.include_router(health_router)
    application.include_router(chat_router)

    return application


app = create_app()
