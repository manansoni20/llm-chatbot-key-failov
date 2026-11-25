"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db
from app.routers.chat import router as chat_router
from app.routers.health import router as health_router
from app.services.llm_service import init_llm_cache


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
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(health_router)
    application.include_router(chat_router)

    return application


app = create_app()
