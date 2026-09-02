"""Gemini client for Structured Outputs (Pydantic schemas).

Implements the Google GenAI structured-output contract documented at
https://ai.google.dev/gemini-api/docs/structured-output :

* Preferred: ``client.interactions.create`` + ``response_format`` schema
* Fallback: ``client.models.generate_content`` with
  ``response_format`` / ``response_mime_type`` + ``response_schema``

Same call shape as ``openai_client.chat_parse`` so evaluation can swap providers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, TypeVar

from pydantic import BaseModel

from backend.config import settings
from backend.observability import tracing as observability

logger = logging.getLogger(__name__)

M = TypeVar("M", bound=BaseModel)

_client = None

# Map EVALUATION_REASONING_EFFORT → Gemini thinking_budget (tokens).
# 0 disables thinking on models that honor the budget.
_THINKING_BUDGET: dict[str, int] = {
    "none": 0,
    "minimal": 0,
    "low": 1024,
    "medium": 4096,
    "high": 8192,
}


def is_available() -> bool:
    """Whether a Gemini API key is configured and the SDK imports."""
    if not (settings.gemini_api_key or "").strip():
        return False
    try:
        import google.genai  # noqa: F401
    except ImportError:
        return False
    return True


def reset_client() -> None:
    global _client
    _client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai

        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def _split_messages(
    messages: list[dict[str, str]],
) -> tuple[str, list[dict[str, Any]], str]:
    """Return (system_instruction, contents, flattened_input)."""
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    flat_parts: list[str] = []
    for msg in messages:
        role = (msg.get("role") or "user").strip().lower()
        text = msg.get("content") or ""
        if not text:
            continue
        if role == "system":
            system_parts.append(text)
            flat_parts.append(f"[SYSTEM]\n{text}")
            continue
        gemini_role = "model" if role in {"assistant", "model"} else "user"
        contents.append({"role": gemini_role, "parts": [{"text": text}]})
        flat_parts.append(f"[{gemini_role.upper()}]\n{text}")
    system = "\n\n".join(system_parts).strip()
    flattened = "\n\n".join(flat_parts).strip()
    return system, contents, flattened


def _schema_dict(response_format: type[BaseModel]) -> dict:
    # mode='serialization' keeps JSON-schema-friendly shapes for providers.
    return response_format.model_json_schema()


def _thinking_config(reasoning_effort: str | None) -> dict | None:
    effort = (reasoning_effort or "").strip().lower() or "low"
    budget = _THINKING_BUDGET.get(effort)
    if budget is None:
        return None
    return {"thinking_budget": budget}


def _parse_text(response_format: type[M], text: str | None) -> M | None:
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        import re

        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        return response_format.model_validate_json(raw)
    except Exception:  # noqa: BLE001
        logger.warning(
            "Gemini structured response failed Pydantic validation. preview=%r",
            raw[:240],
        )
        return None


def _from_generate_response(response: Any, response_format: type[M]) -> M | None:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, response_format):
        return parsed
    if isinstance(parsed, BaseModel):
        try:
            return response_format.model_validate(parsed.model_dump())
        except Exception:  # noqa: BLE001
            pass
    text = getattr(response, "text", None)
    return _parse_text(response_format, text)


def _call_interactions(
    *,
    model: str,
    system: str,
    flattened: str,
    response_format: type[M],
    max_tokens: int | None,
    reasoning_effort: str | None,
) -> M | None:
    client = _get_client()
    interactions = getattr(client, "interactions", None)
    if interactions is None or not hasattr(interactions, "create"):
        return None

    schema = _schema_dict(response_format)
    # Docs: response_format={type, mime_type, schema}
    kwargs: dict[str, Any] = {
        "model": model,
        "input": flattened,
        "response_format": {
            "type": "text",
            "mime_type": "application/json",
            "schema": schema,
        },
    }
    if system:
        # Some SDK builds accept system_instruction on interactions.
        kwargs["system_instruction"] = system
    if max_tokens is not None:
        kwargs["max_output_tokens"] = max_tokens
    thinking = _thinking_config(reasoning_effort)
    if thinking is not None:
        kwargs["thinking_config"] = thinking

    try:
        interaction = interactions.create(**kwargs)
    except TypeError:
        # Retry with the minimal documented surface. If that SDK/API variant is
        # also unavailable, let generateContent handle the request.
        try:
            interaction = interactions.create(
                model=model,
                input=flattened,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": schema,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("Gemini interactions.create unavailable/failed: %s", exc)
            return None
    except Exception as exc:  # noqa: BLE001
        logger.info("Gemini interactions.create unavailable/failed: %s", exc)
        return None

    text = getattr(interaction, "output_text", None) or getattr(
        interaction, "text", None
    )
    return _parse_text(response_format, text)


def _call_generate_content(
    *,
    model: str,
    system: str,
    contents: list[dict[str, Any]],
    flattened: str,
    response_format: type[M],
    max_tokens: int | None,
    temperature: float,
    reasoning_effort: str | None,
) -> M | None:
    client = _get_client()
    schema = _schema_dict(response_format)
    content_payload: Any = contents if contents else flattened
    thinking = _thinking_config(reasoning_effort)

    config_candidates: list[dict[str, Any]] = [
        # Current generateContent docs (response_format.text.schema)
        {
            "response_format": {
                "text": {
                    "mime_type": "application/json",
                    "schema": schema,
                }
            },
        },
        # Classic python-genai Pydantic schema path
        {
            "response_mime_type": "application/json",
            "response_schema": response_format,
        },
        # JSON-schema dict path
        {
            "response_mime_type": "application/json",
            "response_json_schema": schema,
        },
    ]

    last_exc: Exception | None = None
    for base_cfg in config_candidates:
        cfg = dict(base_cfg)
        if system:
            cfg["system_instruction"] = system
        if max_tokens is not None:
            cfg["max_output_tokens"] = max_tokens
        if temperature is not None:
            cfg["temperature"] = temperature
        if thinking is not None:
            cfg["thinking_config"] = thinking
        try:
            response = client.models.generate_content(
                model=model,
                contents=content_payload,
                config=cfg,
            )
            parsed = _from_generate_response(response, response_format)
            if parsed is not None:
                return parsed
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.info(
                "Gemini generate_content config variant failed (%s): %s",
                sorted(base_cfg),
                exc,
            )
            continue
    if last_exc is not None:
        logger.warning("All Gemini generate_content structured variants failed.")
    return None


def chat_parse(
    messages: list[dict[str, str]],
    *,
    response_format: type[M],
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    timeout: float | None = None,
    call_label: str = "",
    reasoning_effort: str | None = None,
    _gate_held: bool = False,
) -> M | None:
    """Structured Outputs via Gemini + Pydantic schema. Returns None on failure."""
    del timeout, _gate_held  # SDK timeout is client-level; gate unused (async wrapper)
    if not is_available():
        return None

    resolved_model = (model or "").strip() or "gemini-2.5-flash"
    system, contents, flattened = _split_messages(messages)
    t0 = time.perf_counter()

    parsed = _call_interactions(
        model=resolved_model,
        system=system,
        flattened=flattened,
        response_format=response_format,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
    )
    if parsed is None:
        parsed = _call_generate_content(
            model=resolved_model,
            system=system,
            contents=contents,
            flattened=flattened,
            response_format=response_format,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
        )

    observability.record_llm_call(
        label=call_label or "gemini_chat_parse",
        model=resolved_model,
        latency_s=time.perf_counter() - t0,
        usage=None,
    )
    if parsed is None:
        logger.warning(
            "Gemini structured call %s returned no parsed object.",
            call_label or "gemini_chat_parse",
        )
    return parsed


async def chat_parse_async(
    messages: list[dict[str, str]],
    *,
    response_format: type[M],
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    timeout: float | None = None,
    call_label: str = "",
    reasoning_effort: str | None = None,
) -> M | None:
    """Async Gemini structured parse (runs sync SDK call in a worker thread)."""
    call = asyncio.to_thread(
        chat_parse,
        messages,
        response_format=response_format,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        call_label=call_label,
        reasoning_effort=reasoning_effort,
    )
    if timeout is None:
        return await call
    try:
        return await asyncio.wait_for(call, timeout=timeout)
    except TimeoutError:
        logger.warning(
            "Gemini structured call %s timed out after %.1fs.",
            call_label or "gemini_chat_parse",
            timeout,
        )
        return None
