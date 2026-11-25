"""Chat and session history endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.schemas import (
    ChatRequest,
    ChatResponse,
    MessageSchema,
    SessionMessagesResponse,
)
from app.services.chat_service import get_session_messages, process_chat
from app.services.llm_service import AllProvidersUnavailableError, ProviderRequestError

router = APIRouter(tags=["Chat"])


@router.post("/chat", response_model=ChatResponse, summary="Send a chat message")
async def chat_endpoint(
    payload: ChatRequest,
    x_simulate_failure: Optional[str] = Header(default=None, alias="X-Simulate-Failure"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ChatResponse:
    """Process a user message with LiteLLM, caching, key failover, and SQLite persistence."""
    try:
        return await process_chat(
            db=db,
            request=payload,
            settings=settings,
            simulate_failure_header=x_simulate_failure,
        )
    except AllProvidersUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="all providers unavailable",
        ) from exc
    except ProviderRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.get(
    "/sessions/{session_id}/messages",
    response_model=SessionMessagesResponse,
    summary="Retrieve conversation history for a session",
)
def get_session_messages_endpoint(
    session_id: str,
    db: Session = Depends(get_db),
) -> SessionMessagesResponse:
    """Return all stored messages for the given session in chronological order."""
    records = get_session_messages(db=db, session_id=session_id)
    return SessionMessagesResponse(
        session_id=session_id,
        messages=[MessageSchema.model_validate(record) for record in records],
    )
