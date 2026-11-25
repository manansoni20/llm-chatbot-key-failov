"""Pydantic request and response schemas for the API."""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class HealthResponse(BaseModel):
    """Response schema for GET /health."""

    status: str = Field(default="ok", description="Service health status")
    keys_configured: int = Field(
        ...,
        ge=0,
        description="Number of configured LLM API keys",
    )
    cache_enabled: bool = Field(
        ...,
        description="Whether LiteLLM response caching is enabled",
    )


class MessageSchema(BaseModel):
    """Serialized representation of a stored chat message."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int = Field(..., description="Unique message ID")
    session_id: str = Field(..., description="Chat session identifier")
    role: Literal["user", "assistant", "system"] = Field(
        ...,
        description="Message author role",
    )
    content: str = Field(..., description="Message text content")
    metadata: Optional[dict[str, Any]] = Field(
        default=None,
        validation_alias=AliasChoices("message_metadata", "metadata"),
        description="Optional metadata such as model, source, token usage, latency, and failover info",
    )
    created_at: datetime = Field(..., description="UTC timestamp when the message was created")


class ChatRequest(BaseModel):
    """Request payload for POST /chat."""

    session_id: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Session identifier used to group conversation history",
    )
    message: str = Field(
        ...,
        min_length=1,
        description="User prompt text",
    )
    model: Optional[str] = Field(
        default=None,
        description="Optional model override",
    )

    @field_validator("session_id", "message")
    @classmethod
    def _reject_blank_strings(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty or whitespace-only")
        return stripped


class ChatMetadata(BaseModel):
    """Execution metadata returned by POST /chat and persisted on assistant messages."""

    resolution_source: Literal["LIVE_INFERENCE", "LLM_CACHE"] = Field(
        ...,
        description="Whether response came from LIVE_INFERENCE or LLM_CACHE",
    )
    model: str = Field(..., description="LLM model used for the response")
    latency_ms: int = Field(..., ge=0, description="End-to-end inference/cache latency in ms")
    input_tokens: int = Field(..., ge=0, description="Prompt/input token count")
    output_tokens: int = Field(..., ge=0, description="Completion/output token count")
    key_id: Optional[str] = Field(
        default=None,
        description="Internal identifier of the key used (e.g., key_1), or null on cache hit",
    )
    fallback_attempts: int = Field(
        default=0,
        ge=0,
        description="Number of failed key attempts before succeeding (0 on first-key success or cache hit)",
    )


class ChatResponse(BaseModel):
    """Response payload for POST /chat."""

    session_id: str = Field(..., description="Chat session identifier")
    reply: str = Field(..., description="Assistant reply text")
    metadata: ChatMetadata = Field(
        ...,
        description="Structured execution metadata for the reply",
    )


class SessionMessagesResponse(BaseModel):
    """Response payload for GET /sessions/{session_id}/messages."""

    session_id: str = Field(..., description="Chat session identifier")
    messages: list[MessageSchema] = Field(
        default_factory=list,
        description="Chronologically ordered messages belonging to the session",
    )
