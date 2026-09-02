"""Thin OpenAI client wrapper used across the v2 backend.

Exposes chat helpers over ``client.chat.completions.create`` / ``.parse`` with:

* Configurable concurrency gate (``MAX_CONCURRENT_LLM_CALLS``)
* Exponential backoff retries on HTTP 429 rate limits
* Async wrappers (``*_async``) that acquire an ``asyncio.Semaphore`` before
  delegating to the sync implementation in a worker thread
* gpt-5 / o-series compatibility (``max_completion_tokens``, no custom
  temperature, optional ``reasoning_effort``)
* Structured Outputs via ``chat_parse`` / ``chat_parse_async`` (Pydantic schema)

When no API key is configured, ``is_available`` is False and callers fall back to
deterministic behaviour so the system runs (and tests pass) offline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import threading
import time
from collections.abc import Callable
from contextlib import asynccontextmanager, contextmanager
from typing import Any, TypeVar

from pydantic import BaseModel

from backend.config import settings
from backend.observability import tracing as observability

logger = logging.getLogger(__name__)

T = TypeVar("T")
M = TypeVar("M", bound=BaseModel)

_client = None
_thread_llm_semaphore: threading.Semaphore | None = None
_async_llm_semaphore: asyncio.Semaphore | None = None
_semaphore_limit: int | None = None
_semaphore_lock = threading.Lock()


def is_available() -> bool:
    """Whether an OpenAI API key is configured."""
    return bool((settings.openai_api_key or "").strip())


def _default_timeout() -> float:
    return float(settings.openai_request_timeout_seconds)


def pipeline_timeout() -> float:
    """Strict timeout for generation-pipeline LLM / embedding calls."""
    return float(settings.openai_pipeline_timeout_seconds)


def max_concurrent_llm_calls() -> int:
    return max(1, int(settings.max_concurrent_llm_calls))


def _resolve_timeout(timeout: float | None) -> float:
    return float(timeout if timeout is not None else pipeline_timeout())


def _reset_rate_limit_state() -> None:
    global _thread_llm_semaphore, _async_llm_semaphore, _semaphore_limit
    with _semaphore_lock:
        _thread_llm_semaphore = None
        _async_llm_semaphore = None
        _semaphore_limit = None


def _ensure_semaphores() -> None:
    global _thread_llm_semaphore, _async_llm_semaphore, _semaphore_limit
    limit = max_concurrent_llm_calls()
    with _semaphore_lock:
        if _thread_llm_semaphore is None or _semaphore_limit != limit:
            _thread_llm_semaphore = threading.Semaphore(limit)
            _async_llm_semaphore = None
            _semaphore_limit = limit


def _get_thread_semaphore() -> threading.Semaphore:
    _ensure_semaphores()
    assert _thread_llm_semaphore is not None
    return _thread_llm_semaphore


def _get_async_semaphore() -> asyncio.Semaphore:
    global _async_llm_semaphore
    _ensure_semaphores()
    if _async_llm_semaphore is None:
        _async_llm_semaphore = asyncio.Semaphore(max_concurrent_llm_calls())
    return _async_llm_semaphore


@contextmanager
def _sync_llm_slot():
    sem = _get_thread_semaphore()
    sem.acquire()
    try:
        yield
    finally:
        sem.release()


@asynccontextmanager
async def _async_llm_slot():
    async with _get_async_semaphore():
        yield


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(
            api_key=settings.openai_api_key,
            timeout=_default_timeout(),
        )
    return _client


def reset_client() -> None:
    """Reset the cached client and concurrency gates (tests / config reloads)."""
    global _client
    _client = None
    _reset_rate_limit_state()


def _is_rate_limit_error(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True
    try:
        from openai import APIStatusError, RateLimitError
    except ImportError:
        return False
    return isinstance(exc, (RateLimitError,)) or (
        isinstance(exc, APIStatusError) and exc.status_code == 429
    )


def _retry_after_seconds(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) if response is not None else None
    if not headers:
        return None
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _run_with_rate_limit_retry(
    operation: Callable[[], T],
    *,
    gate_held: bool = False,
) -> T:
    """Execute *operation* under the concurrency gate with 429 backoff retries."""
    max_retries = max(0, int(settings.openai_rate_limit_max_retries))
    base_delay = float(settings.openai_rate_limit_backoff_base_seconds)
    max_delay = float(settings.openai_rate_limit_backoff_max_seconds)

    attempt = 0
    while True:
        try:
            if gate_held:
                return operation()
            with _sync_llm_slot():
                return operation()
        except Exception as exc:  # noqa: BLE001 — classify provider rate limits
            if not _is_rate_limit_error(exc) or attempt >= max_retries:
                raise
            attempt += 1
            retry_after = _retry_after_seconds(exc)
            if retry_after is not None:
                delay = min(retry_after, max_delay)
            else:
                delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                delay *= 0.5 + random.random() * 0.5
            logger.warning(
                "OpenAI rate limit (429); retry %s/%s in %.2fs",
                attempt,
                max_retries,
                delay,
            )
            time.sleep(delay)


async def _run_async_llm(
    sync_fn: Callable[..., T],
    /,
    *args: Any,
    **kwargs: Any,
) -> T:
    """Acquire the async concurrency gate, then run *sync_fn* in a worker thread."""
    async with _async_llm_slot():
        kwargs["_gate_held"] = True
        return await asyncio.to_thread(sync_fn, *args, **kwargs)


def _parse_llm_json(content: str) -> dict:
    """Parse an LLM JSON payload, stripping optional markdown code fences."""
    text = (content or "").strip()
    if not text:
        logger.warning(
            "LLM JSON response was empty (often gpt-5 reasoning used the token budget)."
        )
        return {}
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                parsed = None
        else:
            parsed = None
        if not isinstance(parsed, dict):
            logger.warning(
                "LLM response is not valid JSON after fence stripping. preview=%r",
                text[:240],
            )
            return {}
        return parsed
    return parsed if isinstance(parsed, dict) else {}


def _uses_max_completion_tokens(model: str) -> bool:
    """Newer chat models reject ``max_tokens``; they want ``max_completion_tokens``."""
    name = (model or "").strip().lower()
    if not name:
        return False
    return (
        name.startswith("gpt-5")
        or name.startswith("o1")
        or name.startswith("o3")
        or name.startswith("o4")
        or "codex" in name
    )


def _completion_length_kwargs(
    model: str,
    max_tokens: int | None,
    *,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    """Build the correct output-length kwarg for the target model family.

    For gpt-5 / o-series, ``max_completion_tokens`` shares a budget with hidden
    reasoning. Pairing ``reasoning_effort=none|minimal`` with a hard cap can
    still yield empty content (``finish_reason=length``). When effort is
    none/minimal we omit the length cap so visible JSON can be emitted.
    """
    if max_tokens is None:
        return {}
    if _uses_max_completion_tokens(model):
        effort = (reasoning_effort or "").strip().lower()
        if effort in {"none", "minimal"}:
            return {}
        return {"max_completion_tokens": max_tokens}
    return {"max_tokens": max_tokens}


def _chat_create_kwargs(
    *,
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int | None,
    timeout: float | None,
    response_format: dict | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    """Build chat.completions.create kwargs; omit unsupported params for gpt-5/o-series."""
    effort = (reasoning_effort or "").strip() or None
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "timeout": _resolve_timeout(timeout),
        **_completion_length_kwargs(
            model, max_tokens, reasoning_effort=effort
        ),
    }
    if response_format is not None:
        kwargs["response_format"] = response_format
    # Reasoning / temperature policy (operator rule):
    # - reasoning_effort none (or omitted) → pass temperature
    # - reasoning_effort set to any other value → do NOT pass temperature
    #   (gpt-5 / o-series reject custom temp when reasoning is on)
    # Some gpt-5.4 / gpt-5.6 ids require explicit reasoning_effort=none to
    # accept a custom temperature; older gpt-5-nano rejects "none" entirely.
    effort_l = (effort or "").strip().lower()
    if effort_l in {"", "none"}:
        kwargs["temperature"] = temperature
        if _supports_reasoning_effort_none(model):
            kwargs["reasoning_effort"] = "none"
    elif _uses_max_completion_tokens(model):
        kwargs["reasoning_effort"] = effort
    return kwargs


def _supports_reasoning_effort_none(model: str) -> bool:
    """Whether the model accepts reasoning_effort='none' (for custom temperature)."""
    name = (model or "").strip().lower()
    if not name:
        return False
    if name.startswith("gpt-5.4") or name.startswith("gpt-5.6"):
        return True
    if "luna" in name or "terra" in name or "sol" in name:
        return True
    return False


def usage_from_response(usage: Any | None) -> dict[str, Any] | None:
    """Normalize OpenAI ``response.usage`` into a plain dict for manifests/logs.

    Uses billed/provider token counts from the API payload (``prompt_tokens``,
    ``completion_tokens``, ``total_tokens``), not a local tiktoken estimate.
    Returns ``None`` when usage is missing or not coercible (e.g. incomplete mocks).
    """
    if usage is None:
        return None

    def _as_int(value: Any) -> int:
        if value is None:
            return 0
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value.strip())
        raise TypeError(f"non-integer usage field: {type(value)!r}")

    try:
        raw: dict[str, Any]
        if isinstance(usage, dict):
            raw = dict(usage)
        else:
            dumped = None
            model_dump = getattr(usage, "model_dump", None)
            if callable(model_dump):
                dumped = model_dump()
            if isinstance(dumped, dict):
                raw = dict(dumped)
            else:
                raw = {
                    "prompt_tokens": getattr(usage, "prompt_tokens", None),
                    "completion_tokens": getattr(usage, "completion_tokens", None),
                    "total_tokens": getattr(usage, "total_tokens", None),
                }
                for key in ("prompt_tokens_details", "completion_tokens_details"):
                    detail = getattr(usage, key, None)
                    if detail is None:
                        continue
                    if hasattr(detail, "model_dump") and callable(detail.model_dump):
                        detail = detail.model_dump()
                    raw[key] = detail

        pt = _as_int(raw.get("prompt_tokens"))
        ct = _as_int(raw.get("completion_tokens"))
        tt = _as_int(raw.get("total_tokens")) or (pt + ct)
        out: dict[str, Any] = {
            "source": "openai_api",
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_tokens": tt,
        }
        for key in ("prompt_tokens_details", "completion_tokens_details"):
            if raw.get(key) is not None:
                out[key] = raw[key]
        return out
    except (TypeError, ValueError):
        return None


def chat_text_with_usage(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    timeout: float | None = None,
    call_label: str = "",
    reasoning_effort: str | None = None,
    _gate_held: bool = False,
) -> tuple[str, dict[str, Any] | None]:
    """Return ``(assistant_text, usage_dict)`` from a chat completion.

    ``usage_dict`` is normalized from the OpenAI response ``usage`` field
    (input/output/total tokens). ``None`` when the provider omits usage.
    """
    resolved_model = model or settings.mapping_model

    def _call() -> tuple[str, dict[str, Any] | None]:
        t0 = time.perf_counter()
        resp = _get_client().chat.completions.create(
            **_chat_create_kwargs(
                model=resolved_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                reasoning_effort=reasoning_effort,
            )
        )
        raw_usage = getattr(resp, "usage", None)
        observability.record_llm_call(
            label=call_label or "chat_text",
            model=resolved_model,
            latency_s=time.perf_counter() - t0,
            usage=raw_usage,
        )
        text = (resp.choices[0].message.content or "").strip()
        return text, usage_from_response(raw_usage)

    return _run_with_rate_limit_retry(_call, gate_held=_gate_held)


def chat_text(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    timeout: float | None = None,
    call_label: str = "",
    reasoning_effort: str | None = None,
    _gate_held: bool = False,
) -> str:
    """Return the assistant text for a chat completion."""
    text, _usage = chat_text_with_usage(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        call_label=call_label,
        reasoning_effort=reasoning_effort,
        _gate_held=_gate_held,
    )
    return text


async def chat_text_async(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    timeout: float | None = None,
    call_label: str = "",
    reasoning_effort: str | None = None,
) -> str:
    """Async chat completion with concurrency gate + 429 retry."""
    return await _run_async_llm(
        chat_text,
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        call_label=call_label,
        reasoning_effort=reasoning_effort,
    )


def chat_vision_json(
    messages: list[dict],
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
    call_label: str = "",
    _gate_held: bool = False,
) -> dict:
    """Vision-capable chat completion returning parsed JSON."""
    resolved_model = model or settings.vision_model

    def _call() -> dict:
        t0 = time.perf_counter()
        resp = _get_client().chat.completions.create(
            **_chat_create_kwargs(
                model=resolved_model,
                messages=messages,
                temperature=0.0,
                max_tokens=max_tokens or settings.vision_max_tokens,
                timeout=timeout,
                response_format={"type": "json_object"},
            )
        )
        observability.record_llm_call(
            label=call_label or "chat_vision_json",
            model=resolved_model,
            latency_s=time.perf_counter() - t0,
            usage=getattr(resp, "usage", None),
        )
        content = (resp.choices[0].message.content or "").strip()
        return _parse_llm_json(content)

    return _run_with_rate_limit_retry(_call, gate_held=_gate_held)


async def chat_vision_json_async(
    messages: list[dict],
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
    call_label: str = "",
) -> dict:
    return await _run_async_llm(
        chat_vision_json,
        messages,
        model=model,
        max_tokens=max_tokens,
        timeout=timeout,
        call_label=call_label,
    )


def chat_json(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    timeout: float | None = None,
    call_label: str = "",
    reasoning_effort: str | None = None,
    _gate_held: bool = False,
) -> dict:
    """Return the parsed JSON object for a chat completion in JSON mode."""
    resolved_model = model or settings.mapping_model

    def _call() -> dict:
        t0 = time.perf_counter()
        resp = _get_client().chat.completions.create(
            **_chat_create_kwargs(
                model=resolved_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                response_format={"type": "json_object"},
                reasoning_effort=reasoning_effort,
            )
        )
        observability.record_llm_call(
            label=call_label or "chat_json",
            model=resolved_model,
            latency_s=time.perf_counter() - t0,
            usage=getattr(resp, "usage", None),
        )
        choice = resp.choices[0]
        message = choice.message
        content = (message.content or "").strip()
        if not content:
            logger.warning(
                "LLM JSON call %s returned empty content (finish_reason=%s, refusal=%r).",
                call_label or "chat_json",
                getattr(choice, "finish_reason", None),
                getattr(message, "refusal", None),
            )
        return _parse_llm_json(content)

    return _run_with_rate_limit_retry(_call, gate_held=_gate_held)


async def chat_json_async(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    timeout: float | None = None,
    call_label: str = "",
    reasoning_effort: str | None = None,
) -> dict:
    """Async JSON chat completion with concurrency gate + 429 retry."""
    return await _run_async_llm(
        chat_json,
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        call_label=call_label,
        reasoning_effort=reasoning_effort,
    )


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
    """Structured Outputs via ``chat.completions.parse`` + Pydantic schema.

    Returns the parsed Pydantic instance, or ``None`` on refusal / incomplete /
    empty content. Prefer this over ``chat_json`` when the response shape is
    known (schema adherence, not just valid JSON).
    """
    resolved_model = model or settings.mapping_model

    def _call() -> M | None:
        t0 = time.perf_counter()
        # parse() injects response_format from the Pydantic model; do not pass
        # json_object here or it overrides the strict json_schema.
        kwargs = _chat_create_kwargs(
            model=resolved_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            reasoning_effort=reasoning_effort,
        )
        resp = _get_client().chat.completions.parse(
            **kwargs,
            response_format=response_format,
        )
        observability.record_llm_call(
            label=call_label or "chat_parse",
            model=resolved_model,
            latency_s=time.perf_counter() - t0,
            usage=getattr(resp, "usage", None),
        )
        choice = resp.choices[0]
        message = choice.message
        refusal = getattr(message, "refusal", None)
        if refusal:
            logger.warning(
                "LLM structured call %s refused (finish_reason=%s): %s",
                call_label or "chat_parse",
                getattr(choice, "finish_reason", None),
                refusal,
            )
            return None
        parsed = getattr(message, "parsed", None)
        if parsed is None:
            logger.warning(
                "LLM structured call %s returned no parsed object "
                "(finish_reason=%s, content_empty=%s).",
                call_label or "chat_parse",
                getattr(choice, "finish_reason", None),
                not bool((getattr(message, "content", None) or "").strip()),
            )
            return None
        return parsed

    return _run_with_rate_limit_retry(_call, gate_held=_gate_held)


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
    """Async Structured Outputs parse with concurrency gate + 429 retry."""
    return await _run_async_llm(
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
