"""
src/rag/llm_client.py

Unified LiteLLM client wrapper for CustomerCore.

Provides a single interface for calling both:
  - LOCAL models via Ollama (gemma3:4b, gemma2:2b) — $0, sub-200ms on GPU
  - CLOUD models via OpenRouter (Claude 3.5 Sonnet, GPT-4o, Gemini 1.5 Pro)

== Why LiteLLM? ==
LiteLLM gives us a unified OpenAI-compatible interface for 100+ model providers.
We can swap Ollama for vLLM, or swap OpenRouter for direct Anthropic, without
changing any calling code — only the model string and API key change.

== Production Config ==
All API keys and endpoints are injected via Doppler at runtime.
NEVER hardcode keys. The client reads from environment variables only.

Environment variables:
  OPENROUTER_API_KEY  — for cloud model routing
  OLLAMA_BASE_URL     — defaults to http://localhost:11434
  LLM_DEFAULT_LOCAL   — which local model to use (default: ollama/gemma3:4b)
  LLM_DEFAULT_CLOUD   — which cloud model to use (default: openrouter/anthropic/claude-3.5-sonnet)
"""

import os
import time
import logging
from dataclasses import dataclass
from typing import Optional, Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

# ── Model Identifiers ──────────────────────────────────────────────────────────
# LiteLLM uses provider/model_name format
LOCAL_MODEL = os.environ.get("LLM_DEFAULT_LOCAL", "ollama/gemma3:4b")
FAST_CLOUD_MODEL = os.environ.get("LLM_FAST_CLOUD", "openrouter/google/gemini-2.5-flash")
FRONTIER_CLOUD_MODEL = os.environ.get("LLM_FRONTIER_CLOUD", "openrouter/anthropic/claude-3.5-sonnet")

CLOUD_MODEL = os.environ.get("LLM_DEFAULT_CLOUD", FRONTIER_CLOUD_MODEL)
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")


@dataclass
class LLMResponse:
    """Structured response from any LLM call."""
    content: str
    model_used: str
    provider: str                 # "local" | "cloud"
    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    success: bool = True
    error: Optional[str] = None
    raw: Optional[Any] = None


# ── Cost table (approximate, USD per 1k tokens) ────────────────────────────────
# Source: OpenRouter pricing — free models marked $0.000
_COST_PER_1K_INPUT = {
    "ollama/gemma3:4b": 0.0,
    "ollama/gemma2:2b": 0.0,
    "ollama/gemma4:e4b": 0.0,
    # OpenRouter FREE models (free tier — no cost)
    "openrouter/meta-llama/llama-3.1-8b-instruct:free": 0.0,
    "openrouter/google/gemma-2-9b-it:free": 0.0,
    "openrouter/mistralai/mistral-7b-instruct:free": 0.0,
    "openrouter/microsoft/phi-3-mini-128k-instruct:free": 0.0,
    # OpenRouter PAID models (for when budget allows)
    "openrouter/google/gemini-2.5-flash": 0.000075,
    "openrouter/anthropic/claude-3.5-sonnet": 0.003,
    "openrouter/openai/gpt-4o": 0.005,
    "openrouter/google/gemini-1.5-pro": 0.00125,
}
_COST_PER_1K_OUTPUT = {
    "ollama/gemma3:4b": 0.0,
    "ollama/gemma2:2b": 0.0,
    "ollama/gemma4:e4b": 0.0,
    # OpenRouter FREE models
    "openrouter/meta-llama/llama-3.1-8b-instruct:free": 0.0,
    "openrouter/google/gemma-2-9b-it:free": 0.0,
    "openrouter/mistralai/mistral-7b-instruct:free": 0.0,
    "openrouter/microsoft/phi-3-mini-128k-instruct:free": 0.0,
    # OpenRouter PAID models
    "openrouter/google/gemini-2.5-flash": 0.0003,
    "openrouter/anthropic/claude-3.5-sonnet": 0.015,
    "openrouter/openai/gpt-4o": 0.015,
    "openrouter/google/gemini-1.5-pro": 0.005,
}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    cost_in = _COST_PER_1K_INPUT.get(model, 0.0) * input_tokens / 1000
    cost_out = _COST_PER_1K_OUTPUT.get(model, 0.0) * output_tokens / 1000
    return round(cost_in + cost_out, 6)


class LLMClient:
    """
    Unified LiteLLM wrapper for local and cloud model calls.

    Usage:
        client = LLMClient()

        # Local (free, fast, private)
        response = client.call_local(
            messages=[{"role": "user", "content": "Classify this ticket: API 500 error"}],
            temperature=0.1,
        )

        # Cloud (frontier reasoning, higher cost)
        response = client.call_cloud(
            messages=[{"role": "user", "content": "Should we issue this $200 refund? Reason carefully."}],
            temperature=0.2,
        )
    """

    def __init__(
        self,
        local_model: str = LOCAL_MODEL,
        cloud_model: str = CLOUD_MODEL,
        fast_cloud_model: str = FAST_CLOUD_MODEL,
    ):
        self.local_model = local_model
        self.cloud_model = cloud_model
        self.fast_cloud_model = fast_cloud_model

    def _call(
        self,
        model: str,
        messages: list[dict],
        provider: str,
        temperature: float = 0.1,
        max_tokens: int = 512,
        timeout: float = 30.0,
    ) -> LLMResponse:
        """Internal call — handles timing, error wrapping, cost estimation."""
        try:
            import litellm
        except ImportError:
            return LLMResponse(
                content="",
                model_used=model,
                provider=provider,
                latency_ms=0.0,
                success=False,
                error="litellm not installed",
            )

        # Dynamic fallback to fast cloud model in cloud/production environments
        is_cloud = os.environ.get("APP_ENV") == "production" or "SPACE_ID" in os.environ
        if provider == "local" and is_cloud and not model.startswith("huggingface/"):
            logger.info("Ollama not available in cloud environment. Dynamically falling back to fast cloud model: %s", self.fast_cloud_model)
            provider = "cloud"
            model = self.fast_cloud_model

        # Configure API base and keys based on model provider
        if model.startswith("huggingface/"):
            provider = "cloud"
            api_base = None
            api_key = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_API_KEY", "")
        else:
            api_base = OLLAMA_BASE_URL if provider == "local" else None
            api_key = OPENROUTER_API_KEY if provider == "cloud" else None

        t0 = time.perf_counter()
        try:
            kwargs = dict(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            if api_base:
                kwargs["api_base"] = api_base
            if api_key:
                kwargs["api_key"] = api_key

            # Add OpenRouter required headers
            if provider == "cloud":
                kwargs["extra_headers"] = {
                    "HTTP-Referer": "https://github.com/CustomerCore",
                    "X-Title": "CustomerCore B2B Intelligence Platform",
                }

            response = litellm.completion(**kwargs)
            latency_ms = (time.perf_counter() - t0) * 1000

            content = response.choices[0].message.content or ""
            usage = response.usage or {}
            input_tokens = getattr(usage, "prompt_tokens", 0) or 0
            output_tokens = getattr(usage, "completion_tokens", 0) or 0

            return LLMResponse(
                content=content,
                model_used=model,
                provider=provider,
                latency_ms=round(latency_ms, 1),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=_estimate_cost(model, input_tokens, output_tokens),
                success=True,
                raw=response,
            )

        except Exception as e:
            # Dynamic fallback to fast cloud model on connection/runtime failure
            if provider == "local":
                logger.warning(
                    "Local Ollama call failed. Dynamically falling back to fast cloud model: %s. Error: %s",
                    self.fast_cloud_model,
                    e
                )
                return self.call_cloud(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    model=self.fast_cloud_model,
                )

            latency_ms = (time.perf_counter() - t0) * 1000
            logger.error("LLM call failed: model=%s error=%s", model, e)
            return LLMResponse(
                content="",
                model_used=model,
                provider=provider,
                latency_ms=round(latency_ms, 1),
                success=False,
                error=str(e),
            )

    def call_local(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 512,
        timeout: float = 30.0,
        model: Optional[str] = None,
    ) -> LLMResponse:
        """Call the local Ollama model (falls back to fast cloud model dynamically if unavailable)."""
        return self._call(
            model=model or self.local_model,
            messages=messages,
            provider="local",
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

    def call_cloud(
        self,
        messages: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 1024,
        timeout: float = 60.0,
        model: Optional[str] = None,
    ) -> LLMResponse:
        """Call the cloud frontier model via OpenRouter. Higher cost, higher capability."""
        if not OPENROUTER_API_KEY:
            logger.warning(
                "OPENROUTER_API_KEY not set — falling back to local model for cloud call"
            )
            return self.call_local(messages, temperature, max_tokens, timeout, model=model)

        return self._call(
            model=model or self.cloud_model,
            messages=messages,
            provider="cloud",
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )


# ── Module-level singleton ─────────────────────────────────────────────────────
_default_client: Optional[LLMClient] = None


def get_client() -> LLMClient:
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client
