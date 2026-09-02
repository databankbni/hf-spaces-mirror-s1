"""Provider-agnostic LLM transport for evaluation judges.

Uses Structured Outputs with shared Pydantic schemas:

* OpenAI — ``chat.completions.parse`` + Pydantic ``response_format``
* Gemini — Interactions / generateContent structured output + same schemas

Provider selection (``EVALUATION_PROVIDER``):

* ``auto`` (default) — Gemini when the resolved model name starts with
  ``gemini``, otherwise OpenAI
* ``openai`` / ``gemini`` — force that provider
"""

from __future__ import annotations

import logging
from typing import Literal, TypeVar

from pydantic import BaseModel

from backend.config import settings
from backend.llm import gemini_client, openai_client

logger = logging.getLogger(__name__)

M = TypeVar("M", bound=BaseModel)
ProviderName = Literal["openai", "gemini"]

# Only Gemini judge we use ($0.25 / $1.50). 3.5/3.6 flash variants are excluded
# as too expensive; 2.5-flash-lite is unavailable on new API keys.
_DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"


def resolved_provider() -> ProviderName:
    configured = (settings.evaluation_provider or "auto").strip().lower()
    if configured in {"openai", "gemini"}:
        return configured  # type: ignore[return-value]

    model = (settings.evaluation_model or "").strip().lower()
    if model.startswith("gemini"):
        return "gemini"
    # Empty model falls back to grounding_model for OpenAI path; if that is
    # somehow a gemini id, honour it.
    if not model:
        grounding = (settings.grounding_model or "").strip().lower()
        if grounding.startswith("gemini"):
            return "gemini"
    return "openai"


def resolved_model() -> str:
    explicit = (settings.evaluation_model or "").strip()
    if explicit:
        return explicit
    if resolved_provider() == "gemini":
        return _DEFAULT_GEMINI_MODEL
    return settings.grounding_model


def resolved_reasoning_effort() -> str:
    return (settings.evaluation_reasoning_effort or "").strip().lower() or "none"


def resolved_temperature() -> float:
    return float(settings.evaluation_temperature)


def _uses_openai_reasoning_budget(model: str) -> bool:
    name = (model or "").strip().lower()
    return (
        name.startswith("gpt-5")
        or name.startswith("o1")
        or name.startswith("o3")
        or name.startswith("o4")
    )


def resolved_max_tokens(effort: str | None = None) -> int | None:
    """Optional length cap for the active provider/model."""
    del effort
    provider = resolved_provider()
    model = resolved_model()
    if provider == "openai" and _uses_openai_reasoning_budget(model):
        return None
    return settings.evaluation_max_tokens


def is_available() -> bool:
    """True when the resolved provider has credentials + SDK available."""
    if resolved_provider() == "gemini":
        return gemini_client.is_available()
    return openai_client.is_available()


def unavailable_reason() -> str:
    provider = resolved_provider()
    if provider == "gemini":
        if not (settings.gemini_api_key or "").strip():
            return "gemini_unavailable"
        if not gemini_client.is_available():
            return "gemini_sdk_unavailable"
        return "gemini_unavailable"
    if not openai_client.is_available():
        return "openai_unavailable"
    return "llm_unavailable"


async def call_judge_parse(
    messages: list[dict[str, str]],
    *,
    response_format: type[M],
    call_label: str,
    section_id: str = "",
) -> M | None:
    """Return a Pydantic-parsed judge response, or ``None`` on refusal/empty."""
    effort = resolved_reasoning_effort()
    temperature = resolved_temperature()
    model = resolved_model()
    provider = resolved_provider()
    max_tokens = resolved_max_tokens(effort)

    if provider == "gemini":
        if not gemini_client.is_available():
            logger.warning(
                "%s skipped section=%s — Gemini unavailable "
                "(set GEMINI_API_KEY and install google-genai).",
                call_label,
                section_id,
            )
            return None
        parsed = await gemini_client.chat_parse_async(
            messages,
            response_format=response_format,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=settings.evaluation_call_timeout_seconds,
            reasoning_effort=effort,
            call_label=call_label,
        )
    else:
        if not openai_client.is_available():
            logger.warning(
                "%s skipped section=%s — OpenAI unavailable.",
                call_label,
                section_id,
            )
            return None
        parsed = await openai_client.chat_parse_async(
            messages,
            response_format=response_format,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=settings.evaluation_call_timeout_seconds,
            reasoning_effort=effort,
            call_label=call_label,
        )

    if parsed is None:
        logger.warning(
            "%s returned no structured object for section=%s "
            "(provider=%s effort=%s model=%s).",
            call_label,
            section_id,
            provider,
            effort,
            model,
        )
    return parsed
