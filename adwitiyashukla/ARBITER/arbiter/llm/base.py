from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..models import Usage

RETRY_STATUSES = (429, 500, 502, 503, 504)
MAX_ATTEMPTS = 6
BASE_BACKOFF_S = 5.0
MAX_BACKOFF_S = 65.0

_MIN_INTERVAL_S = 0.0
_last_call_at = 0.0


def set_rate_limit(requests_per_minute: float) -> None:
    global _MIN_INTERVAL_S
    _MIN_INTERVAL_S = (60.0 / requests_per_minute) if requests_per_minute > 0 else 0.0


def _throttle() -> None:
    global _last_call_at
    if _MIN_INTERVAL_S <= 0:
        return
    wait = _last_call_at + _MIN_INTERVAL_S - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_call_at = time.monotonic()


def request_with_retry(send: Callable[[], Any], label: str = "") -> Any:
    last = None
    for attempt in range(MAX_ATTEMPTS):
        _throttle()
        response = send()
        if response.status_code not in RETRY_STATUSES:
            global _consecutive_exhaustions
            _consecutive_exhaustions = 0
            return response
        last = response
        if attempt == MAX_ATTEMPTS - 1:
            break
        wait = min(BASE_BACKOFF_S * (2 ** attempt), MAX_BACKOFF_S) + random.uniform(0, 1.0)
        header = response.headers.get("Retry-After") if hasattr(response, "headers") else None
        if header:
            try:
                wait = max(wait, float(header))
            except ValueError:
                pass
        print("    [{0}] http {1}, waiting {2:.1f}s (attempt {3}/{4})".format(
            label or "llm", response.status_code, wait, attempt + 1, MAX_ATTEMPTS))
        time.sleep(wait)

    globals()["_consecutive_exhaustions"] = _consecutive_exhaustions + 1
    if _consecutive_exhaustions >= CONSECUTIVE_FAILURE_LIMIT:
        raise QuotaExhausted(
            "{0} calls in a row exhausted their retries against {1}, most recently http {2}. "
            "This looks like a daily quota rather than a burst limit, so stopping here. "
            "Try a different model with --judge-model or --actor-model, or come back "
            "tomorrow.".format(_consecutive_exhaustions, label or "the provider",
                               getattr(last, "status_code", "?")))
    return last


class LLMError(RuntimeError):
    pass


class QuotaExhausted(LLMError):
    pass


CONSECUTIVE_FAILURE_LIMIT = 3
_consecutive_exhaustions = 0


@dataclass
class Reply:
    text: str
    usage: Usage = field(default_factory=Usage)
    raw: Dict[str, Any] = field(default_factory=dict)


class LLMProvider:

    name = "base"

    def __init__(self, model: str, api_key: str = "", timeout: int = 120, temperature: float = 0.2):
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.temperature = temperature

    def complete(self, system: str, user: str, images: Optional[List[bytes]] = None) -> Reply:
        raise NotImplementedError

    def start_scope(self, scope: str) -> None:
        pass


def build_provider(provider: str, model: str, api_key: str = "", **kwargs: Any) -> LLMProvider:
    provider = (provider or "").lower().strip()
    if provider == "gemini":
        from .gemini import GeminiProvider
        return GeminiProvider(model, api_key, **kwargs)
    if provider == "openai":
        from .openai import OpenAIProvider
        return OpenAIProvider(model, api_key, **kwargs)
    if provider == "anthropic":
        from .anthropic import AnthropicProvider
        return AnthropicProvider(model, api_key, **kwargs)
    if provider == "mock":
        from .mock import MockProvider
        return MockProvider(model, api_key, **kwargs)
    raise LLMError("unknown provider {0!r}, expected one of: gemini, openai, anthropic, mock".format(provider))


def env_key(*names: str) -> str:
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return ""
