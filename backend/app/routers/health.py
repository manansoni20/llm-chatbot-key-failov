"""Health check router verifying SQLite connectivity and API key pool readiness."""

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.schemas import HealthResponse

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "Database unavailable or fewer than 2 distinct API keys configured"
        }
    },
    summary="Service health and readiness check",
)
def health_check(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> HealthResponse | JSONResponse:
    """Verify SQLite connectivity and that at least 2 distinct API keys are configured."""
    try:
        db.execute(text("SELECT 1")).scalar_one()
    except SQLAlchemyError:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unavailable",
                "keys_configured": settings.keys_configured,
                "cache_enabled": settings.cache_enabled,
                "detail": "database unavailable",
            },
        )

    if not settings.is_key_pool_ready:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unavailable",
                "keys_configured": settings.keys_configured,
                "cache_enabled": settings.cache_enabled,
                "detail": "at least 2 distinct API keys must be configured",
            },
        )

    return HealthResponse(
        status="ok",
        keys_configured=settings.keys_configured,
        cache_enabled=settings.cache_enabled,
    )
