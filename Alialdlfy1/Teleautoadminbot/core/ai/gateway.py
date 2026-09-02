"""
P29 AI Gateway — one entry point for all AI calls.

Goals:
- Route every request through AIProviderPool.
- Keep legacy secret names unchanged.
- Fail over across keys/providers on rate limits/transient errors.
- Support one structured "article package" request instead of many calls.
- Track approximate usage when providers return token metadata.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional
import json
import time

from core.providers.pool import AIProviderPool, KeyState


@dataclass
class AIResponse:
    data: Any
    provider: str
    key_name: str
    attempts: int
    input_tokens: int = 0
    output_tokens: int = 0


class AIGateway:
    def __init__(self, pool: AIProviderPool, adapters: Optional[Dict[str, Callable]] = None):
        self.pool = pool
        self.adapters = adapters or {}

    def register(self, provider: str, adapter: Callable) -> None:
        self.adapters[provider.lower()] = adapter

    def _invoke(self, key: KeyState, payload: Any) -> Any:
        adapter = self.adapters.get(key.provider)
        if adapter is None:
            raise RuntimeError(f"No adapter registered for provider: {key.provider}")
        return adapter(key.value, payload)

    @staticmethod
    def _usage(result: Any) -> tuple[int, int]:
        if isinstance(result, dict):
            usage = result.get("usage") or result.get("token_usage") or {}
            return int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0), int(
                usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
            )
        return 0, 0

    def request(
        self,
        payload: Any,
        providers: Optional[Iterable[str]] = None,
        max_attempts: int = 6,
    ) -> AIResponse:
        attempts = 0
        last_error = None
        for _ in range(max(1, max_attempts)):
            key = self.pool.choose(providers)
            if key is None:
                break
            attempts += 1
            try:
                result = self._invoke(key, payload)
                inp, out = self._usage(result)
                self.pool.report_success(key, inp + out)
                return AIResponse(result, key.provider, key.name, attempts, inp, out)
            except Exception as exc:
                last_error = exc
                # Provider adapters may classify 429/5xx/timeout failures.
                rate_limited = bool(getattr(exc, "rate_limited", False))
                transient = bool(getattr(exc, "transient", False))
                cooldown = int(getattr(exc, "cooldown_seconds", 30))
                self.pool.report_failure(key, cooldown_seconds=cooldown, rate_limited=rate_limited)
                # Backoff is bounded so one broken key cannot stall the whole worker.
                retry_after = float(getattr(exc, "retry_after_seconds", 0) or 0)
                if retry_after <= 0:
                    retry_after = min(5.0, 0.25 * (2 ** max(0, attempts - 1)))
                if transient or rate_limited:
                    time.sleep(max(0.0, min(retry_after, 5.0)))
        if last_error:
            raise RuntimeError(f"All AI attempts failed: {last_error}") from last_error
        raise RuntimeError("No available AI provider keys")

    def article_package(
        self,
        article: str,
        *,
        task: str = "process_article",
        fields: Optional[list[str]] = None,
        providers: Optional[Iterable[str]] = None,
        max_attempts: int = 6,
    ) -> AIResponse:
        """Build one compact structured request for all article outputs."""
        fields = fields or [
            "title", "article", "summary", "keywords",
            "hashtags", "seo_title", "seo_description", "category", "slug"
        ]
        payload = {
            "task": task,
            "output_format": "json",
            "fields": fields,
            "article": article,
            "instruction": "Return only the requested JSON object. Do not repeat the input outside the required fields.",
        }
        return self.request(payload, providers=providers, max_attempts=max_attempts)
