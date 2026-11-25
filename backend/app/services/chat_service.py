"""Chat orchestration service combining SQLite history and LiteLLM gateway calls."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Message
from app.schemas import ChatMetadata, ChatRequest, ChatResponse
from app.services.llm_service import generate_completion


def get_session_messages(db: Session, session_id: str) -> list[Message]:
    """Retrieve all persisted messages for a session in chronological order."""
    stmt = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    )
    return list(db.scalars(stmt).all())


def build_llm_messages(
    history: list[Message],
    new_user_message: str,
    system_prompt: str,
) -> list[dict[str, str]]:
    """Construct the full ordered message list (system prompt + history + new prompt)."""
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    for entry in history:
        messages.append({"role": entry.role, "content": entry.content})

    messages.append({"role": "user", "content": new_user_message})
    return messages


async def process_chat(
    db: Session,
    request: ChatRequest,
    settings: Settings,
    simulate_failure_header: Optional[str] = None,
) -> ChatResponse:
    """
    Process a chat turn: load history, invoke LiteLLM, and persist both turns on success.

    Failed requests are never persisted to SQLite.
    """
    history = get_session_messages(db, request.session_id)
    llm_messages = build_llm_messages(
        history=history,
        new_user_message=request.message,
        system_prompt=settings.system_prompt,
    )

    result = await generate_completion(
        messages=llm_messages,
        settings=settings,
        model=request.model,
        simulate_failure_header=simulate_failure_header,
    )

    metadata = ChatMetadata(
        resolution_source=result.source,
        model=result.model,
        latency_ms=result.latency_ms,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        key_id=result.key_id,
        fallback_attempts=result.fallback_attempts,
    )

    now = datetime.now(timezone.utc)
    user_record = Message(
        session_id=request.session_id,
        role="user",
        content=request.message,
        message_metadata=None,
        created_at=now,
    )
    assistant_record = Message(
        session_id=request.session_id,
        role="assistant",
        content=result.content,
        message_metadata=metadata.model_dump(),
        created_at=now,
    )

    db.add(user_record)
    db.add(assistant_record)
    db.commit()

    return ChatResponse(
        session_id=request.session_id,
        reply=result.content,
        metadata=metadata,
    )
