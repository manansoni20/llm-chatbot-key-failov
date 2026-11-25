"""LiteLLM gateway integration with Gemini, key-pool failover, caching, and failure simulation."""

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Literal, Optional

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import litellm
from litellm.caching.caching import Cache
from litellm.types.caching import LiteLLMCacheType

from app.config import Settings

litellm.suppress_debug_info = True

logger = logging.getLogger(__name__)

InferenceSource = Literal["LIVE_INFERENCE", "LLM_CACHE"]
DEFAULT_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class AllProvidersUnavailableError(Exception):
    """Raised when every configured API key fails with retryable/provider errors."""


class ProviderRequestError(Exception):
    """Raised on non-retryable upstream provider errors."""


class SimulatedProviderFailure(Exception):
    """Raised internally when X-Simulate-Failure matches a key or wildcard."""

    def __init__(self, key_id: str, status_code: int) -> None:
        self.key_id = key_id
        self.status_code = status_code
        super().__init__(f"Simulated failure {status_code} for {key_id}")


@dataclass(frozen=True)
class LLMCompletionResult:
    """Normalized result returned by the LLM gateway service."""

    content: str
    model: str
    source: InferenceSource
    cached: bool
    input_tokens: int
    output_tokens: int
    latency_ms: int
    key_id: Optional[str]
    fallback_attempts: int


def init_llm_cache(settings: Settings, force_reset: bool = False) -> None:
    """Initialize LiteLLM's local in-memory cache when caching is enabled."""
    if not settings.cache_enabled:
        if force_reset:
            litellm.cache = None
        return

    if force_reset or litellm.cache is None:
        litellm.cache = Cache(
            type=LiteLLMCacheType.LOCAL,
            ttl=settings.cache_ttl_seconds,
            max_messages=None,
        )


def parse_simulate_failure_header(header_value: Optional[str]) -> dict[str, int]:
    """
    Parse X-Simulate-Failure header into a target -> HTTP status code mapping.

    Supported formats:
      - key_1=429
      - key_1=500,key_2=429
      - *=429
    """
    if not header_value:
        return {}

    rules: dict[str, int] = {}
    for raw_part in header_value.split(","):
        part = raw_part.strip()
        if "=" not in part:
            continue
        target, raw_code = part.split("=", 1)
        target = target.strip()
        raw_code = raw_code.strip()
        if not target or not raw_code.isdigit():
            continue
        rules[target] = int(raw_code)
    return rules


def is_retryable_provider_error(exc: Exception) -> bool:
    """Return True for HTTP 429, quota errors, 5xx errors, or transient transport errors."""
    if isinstance(exc, SimulatedProviderFailure):
        return exc.status_code == 429 or 500 <= exc.status_code < 600

    retryable_types = (
        litellm.exceptions.RateLimitError,
        litellm.exceptions.ServiceUnavailableError,
        litellm.exceptions.InternalServerError,
        litellm.exceptions.APIConnectionError,
        litellm.exceptions.Timeout,
    )
    if isinstance(exc, retryable_types):
        return True

    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int) and (status_code == 429 or 500 <= status_code < 600):
        return True

    message = str(exc).lower()
    retryable_markers = (
        "429",
        "rate limit",
        "rate_limit",
        "too many requests",
        "quota",
        "resource_exhausted",
        "service unavailable",
        "internal server error",
        "bad gateway",
        "gateway timeout",
        "500",
        "502",
        "503",
        "504",
    )
    return any(marker in message for marker in retryable_markers)


def _resolve_gemini_api_base(model: str, settings: Settings) -> Optional[str]:
    """
    Return the v1beta base URL for Google AI Studio Gemini models.

    LiteLLM's default `get_gemini_url()` routes models classified as Gemini 3+
    (including `-latest` aliases such as `gemini-flash-latest`) to `/v1alpha`,
    which Google AI Studio rejects with HTTP 404. Passing `api_base` with the
    `/v1beta` prefix routes requests through `_check_custom_proxy` directly to
    `/v1beta/models/{model}:generateContent`.
    """
    try:
        provider = litellm.get_llm_provider(model)[1]
    except Exception:
        provider = "gemini" if model.startswith("gemini/") else None

    if provider != "gemini":
        return None

    configured_base = (settings.gemini_api_base or DEFAULT_GEMINI_API_BASE).strip()
    return (configured_base or DEFAULT_GEMINI_API_BASE).rstrip("/")


def _extract_content_and_usage(response: Any) -> tuple[str, int, int]:
    """Extract assistant text and (input_tokens, output_tokens) from ModelResponse or dict."""
    if isinstance(response, dict):
        choices = response.get("choices") or []
        first_choice = choices[0] if choices else {}
        message = first_choice.get("message") or {}
        content = message.get("content") or ""
        usage = response.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        return str(content), input_tokens, output_tokens

    choices = getattr(response, "choices", None) or []
    first_choice = choices[0] if choices else None
    message = getattr(first_choice, "message", None) if first_choice is not None else None
    content = getattr(message, "content", None) or ""
    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    return str(content), input_tokens, output_tokens


async def generate_completion(
    messages: list[dict[str, str]],
    settings: Settings,
    model: Optional[str] = None,
    simulate_failure_header: Optional[str] = None,
) -> LLMCompletionResult:
    """
    Execute chat completion via LiteLLM with response caching and API-key failover.

    Cache lookup happens before key iteration so cache hits always return
    source="LLM_CACHE", key_id=None, and fallback_attempts=0.
    """
    start_time = time.perf_counter()
    target_model = model or settings.llm_model

    if settings.cache_enabled:
        init_llm_cache(settings)
        if litellm.cache is not None:
            cached_entry = await litellm.cache.async_get_cache(
                model=target_model,
                messages=messages,
            )
            if cached_entry is not None:
                content, input_tokens, output_tokens = _extract_content_and_usage(
                    cached_entry
                )
                latency_ms = int(round((time.perf_counter() - start_time) * 1000))
                return LLMCompletionResult(
                    content=content,
                    model=target_model,
                    source="LLM_CACHE",
                    cached=True,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    key_id=None,
                    fallback_attempts=0,
                )

    key_pool = settings.api_key_pool
    if not key_pool:
        raise AllProvidersUnavailableError("all providers unavailable")

    failure_rules = (
        parse_simulate_failure_header(simulate_failure_header)
        if settings.enable_failure_simulation
        else {}
    )

    fallback_attempts = 0
    gemini_api_base = _resolve_gemini_api_base(target_model, settings)

    for key_id, api_key in key_pool:
        try:
            simulated_code = failure_rules.get(key_id)
            if simulated_code is None:
                simulated_code = failure_rules.get("*")

            if simulated_code is not None:
                raise SimulatedProviderFailure(key_id=key_id, status_code=simulated_code)

            completion_kwargs: dict[str, Any] = {
                "model": target_model,
                "messages": messages,
                "api_key": api_key,
                "caching": False,
            }
            if gemini_api_base:
                completion_kwargs["api_base"] = gemini_api_base

            response = await litellm.acompletion(**completion_kwargs)

            content, input_tokens, output_tokens = _extract_content_and_usage(response)

            if settings.cache_enabled and litellm.cache is not None:
                await litellm.cache.async_add_cache(
                    result=response,
                    model=target_model,
                    messages=messages,
                )

            latency_ms = int(round((time.perf_counter() - start_time) * 1000))
            return LLMCompletionResult(
                content=content,
                model=target_model,
                source="LIVE_INFERENCE",
                cached=False,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                key_id=key_id,
                fallback_attempts=fallback_attempts,
            )

        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            logger.warning(
                "LLM provider attempt failed for %s (error=%s, status=%s)",
                key_id,
                type(exc).__name__,
                status_code,
            )
            if is_retryable_provider_error(exc):
                fallback_attempts += 1
                continue
            raise ProviderRequestError(
                f"Non-retryable provider error on {key_id}: {type(exc).__name__}"
            ) from exc

    raise AllProvidersUnavailableError("all providers unavailable")
