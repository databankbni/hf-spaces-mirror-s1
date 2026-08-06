"""
llm_client.py — Shared LLM provider chain for all modules.

Single source of truth for OpenRouter → Ollama → Groq → Cerebras → HuggingFace provider
routing, dynamic reordering based on availability, cooldown tracking, and retry logic.
Imported by:
  - ai_forecast.py  (via `from llm_client import make_chat_call`)
  - news_sentiment.py
  - self_learning.py

Public API
----------
  make_chat_call(messages, max_tokens, temperature, fast_fail_on_rate_limit,
                 task_offset, max_retries) -> (content, provider, model)

  Raises RuntimeError if all providers are unavailable after max_retries passes.

Dynamic provider ordering
-------------------------
  Providers are sorted at each call by current availability:
    1. Available (not daily-exhausted, cooldown expired) — fewest recent failures first
    2. Rate-limited (cooldown active) — soonest recovery first
    3. Daily exhausted — lowest priority

  When ALL cloud providers are daily-exhausted → Ollama is promoted to Phase 1
  (before any cloud provider). This avoids wasting time on guaranteed 429s.

  Daily status resets automatically at midnight IST.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import re

import requests

# Load .env before reading API keys
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

# ── Unified provider status (replaces individual _*_DISABLED_UNTIL globals) ──
# avail_at: Unix timestamp — provider is usable again after this point (0 = now)
# daily_exhausted: True when daily quota is fully consumed (402/daily-quota 429)
# fail_streak: consecutive failure count — used for secondary sort
_PROVIDER_STATUS: dict = {
    "openrouter":  {"avail_at": 0.0, "daily_exhausted": False, "fail_streak": 0},
    "groq":        {"avail_at": 0.0, "daily_exhausted": False, "fail_streak": 0},
    "cerebras":    {"avail_at": 0.0, "daily_exhausted": False, "fail_streak": 0},
    "huggingface": {"avail_at": 0.0, "daily_exhausted": False, "fail_streak": 0},
    # Extra free tiers — large independent daily capacity (Gemini ~1,500 req/day, SambaNova
    # persistent free 70B, NVIDIA NIM free 70B/Nemotron). Appended LAST so the happy path is
    # unchanged, but the dynamic availability sort auto-promotes them to the front the moment the
    # first four degrade — which is exactly when the exhaustion→single-Ollama funnel used to bite.
    # No-op without keys.
    "gemini":      {"avail_at": 0.0, "daily_exhausted": False, "fail_streak": 0},
    "sambanova":   {"avail_at": 0.0, "daily_exhausted": False, "fail_streak": 0},
    "nvidia":      {"avail_at": 0.0, "daily_exhausted": False, "fail_streak": 0},
}
_PROVIDER_DAILY_RESET: str = ""   # "YYYY-MM-DD" IST string; reset daily flags on date change

_LLM_COOLDOWN_SECS: int = 600
_OPENROUTER_COOLDOWN_SECS: int = 60
_ALL_PROVIDERS_RETRY_WAIT_SECS: int = 2

_LLM_LOCK = threading.Lock()
_LLM_DISABLED_UNTIL: float = 0.0  # global kill-switch (all providers failed simultaneously)

# Limits concurrent cloud LLM calls. Ollama is handled separately via _OLLAMA_SEMAPHORE.
# 16 concurrent: enough for all watchlist stocks × 4 TFs without artificial throttling.
_LLM_SEMAPHORE = threading.Semaphore(16)

# Limit Ollama to 1 concurrent call: the HF Space serializes internally anyway,
# so multiple concurrent requests just queue inside Ollama and each waits N×40s.
_OLLAMA_SEMAPHORE = threading.Semaphore(1)

# Cache Ollama health check result to avoid hammering /api/tags on every call.
_OLLAMA_HEALTH_LAST_CHECK: float = 0.0
_OLLAMA_HEALTH_RESULT: bool = False
_OLLAMA_HEALTH_TTL: int = 60
# BUGFIX: a NEGATIVE (unhealthy) probe result must expire fast. A cold-starting HF Space
# returns False for ~20-40s and then becomes healthy; caching that False for the full 60s TTL
# locked every subsequent call out of Ollama (never re-probed, never warmed) — this is what
# SKIPped 47/72 predictions in the last batch run. Positive results keep the 60s TTL (which is
# all we need to avoid a /api/tags storm on a Space that is already up).
_OLLAMA_HEALTH_NEG_TTL: int = 10

# After a chat timeout or inference failure, back off for this many seconds before retrying.
# Prevents cascading 45s timeouts when the HF Space is unresponsive.
_OLLAMA_INFER_BACKOFF_UNTIL: float = 0.0
_OLLAMA_INFER_BACKOFF_SECS: int = 120  # 2 min — shorter than 300s so Ollama is re-tried mid-batch
# A warmup failure just means the model is still loading (cold start); it recovers in seconds,
# so back off only briefly. The old 300s backoff after a single cold-start warmup miss took
# Ollama offline for half of a ~10-min batch run, cascading into AI-unavailable SKIPs.
_OLLAMA_WARMUP_BACKOFF_SECS: int = 45
_OLLAMA_CHAT_TIMEOUT: int = 70          # 70s: warmup confirms model is loaded, so 70s is enough for 512 tokens

# Canonical cloud provider order (original preference before runtime reordering)
_CLOUD_PROVIDERS = ["openrouter", "groq", "cerebras", "huggingface", "gemini", "sambanova", "nvidia"]
_PROVIDER_ORDER = _CLOUD_PROVIDERS


# ── Provider status helpers ───────────────────────────────────────────────────

def _maybe_daily_reset() -> None:
    """Reset daily_exhausted flags at midnight IST. No-op if already reset today."""
    global _PROVIDER_DAILY_RESET
    today = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d")
    with _LLM_LOCK:
        if _PROVIDER_DAILY_RESET != today:
            _PROVIDER_DAILY_RESET = today
            for s in _PROVIDER_STATUS.values():
                s["daily_exhausted"] = False
                # Keep fail_streak — it decays naturally on success, not on reset
            logger.info("LLM: Daily provider status reset (IST midnight)")


def _get_cloud_order() -> list[str]:
    """
    Return cloud providers sorted by current availability.
    Scores: (0=available, 1=rate-limited, 2=daily-exhausted) then secondary sub-sort.
    Available providers with fewer failures come first; daily-exhausted come last.
    """
    _maybe_daily_reset()
    now = time.time()

    def _score(name: str):
        s = _PROVIDER_STATUS[name]
        if s["daily_exhausted"]:
            return (2, s["fail_streak"])
        if s["avail_at"] > now:
            return (1, s["avail_at"] - now)   # sooner recovery = higher priority
        return (0, s["fail_streak"])           # available; fewest failures first

    return sorted(_CLOUD_PROVIDERS, key=_score)


def _all_cloud_daily_exhausted() -> bool:
    """True when every cloud provider has consumed its daily quota."""
    _maybe_daily_reset()
    return all(_PROVIDER_STATUS[n]["daily_exhausted"] for n in _CLOUD_PROVIDERS)


def unavailability_is_recoverable() -> bool:
    """After make_chat_call raised, classify the outage as TEMPORARY vs HARD.

    TEMPORARY (returns True): at least one keyed cloud provider is only cooling down /
    burst-rate-limited (NOT daily-exhausted) and will recover once its short per-minute
    window lapses, OR Ollama is configured and not in a hard backoff. In this case the
    caller should mark the failure as a retryable 'timeout' — the frontend keeps refetching
    and the forecast fills in a moment later when a provider resets.

    HARD (returns False): every keyed cloud provider is daily-exhausted (real quota gone
    until midnight IST) AND Ollama is unconfigured / in backoff — nothing will work soon,
    so 'ai_unavailable' is the honest reason.

    Note: a provider with no API key can never recover on its own, so it doesn't count as
    a recoverable source (this is checked via provider_key_status()).
    """
    _maybe_daily_reset()
    keys = provider_key_status()
    # A keyed cloud provider that hit only a transient (per-minute) limit will reset soon.
    for name in _CLOUD_PROVIDERS:
        if keys.get(name) and not _PROVIDER_STATUS[name]["daily_exhausted"]:
            return True
    # Ollama has no rate limits — recoverable if configured and not in a hard backoff window.
    if keys.get("ollama") and time.time() >= _OLLAMA_INFER_BACKOFF_UNTIL:
        return True
    return False


def _mark_ok(name: str) -> None:
    with _LLM_LOCK:
        s = _PROVIDER_STATUS[name]
        s["avail_at"] = 0.0
        s["fail_streak"] = max(0, s["fail_streak"] - 1)


def _mark_rate_limited(name: str, cooldown: float = 60.0) -> None:
    with _LLM_LOCK:
        s = _PROVIDER_STATUS[name]
        s["avail_at"] = max(s["avail_at"], time.time() + cooldown)
        s["fail_streak"] += 1


def _mark_daily_exhausted(name: str) -> None:
    with _LLM_LOCK:
        s = _PROVIDER_STATUS[name]
        s["daily_exhausted"] = True
        s["fail_streak"] += 1
    logger.warning("LLM: %s marked daily-exhausted — will skip until midnight IST reset", name)


def _is_daily_quota_429(body: str) -> bool:
    """Classify a 429 response body as a daily quota exhaustion (bench until reset) rather than a
    transient per-minute RPM limit (short cooldown). Gemini/Google free-tier daily caps say
    'exceeded your current quota, please check your plan and billing' and reference *PerDay quota
    metrics; per-minute limits reference *PerMinute and a short retryDelay. Returns False when
    ambiguous so a recoverable RPM 429 is never sidelined for the whole day. Without this, a
    daily-dead provider that sits first in cloud_order gets retried (and 429s) on every call of a
    150-stock scan, deepening the funnel to slow Ollama."""
    if not body:
        return False
    b = body.lower()
    if "per minute" in b or "perminute" in b or "requests per minute" in b:
        return False
    return (
        "per day" in b or "perday" in b or "requests per day" in b
        or "check your plan and billing" in b
        or "exceeded your current quota" in b
        or "insufficient_quota" in b
        or "depleted" in b
    )


def _is_provider_available(name: str, fast_fail: bool = False) -> bool:
    """True if this provider should be tried right now."""
    _maybe_daily_reset()
    s = _PROVIDER_STATUS[name]
    if s["daily_exhausted"]:
        return False
    if fast_fail:
        return True  # fast_fail ignores temporary cooldowns
    return s["avail_at"] <= time.time()


def reset_ollama_state() -> None:
    """Clear Ollama's transient backoff + health cache so the next call gets a fresh probe.

    Called between deferred-retry rounds (backtest anti-skip loop, and the production
    background-fill pass) so a stock deferred because Ollama was mid-backoff gets a genuine
    fresh Ollama attempt in the next round — instead of being skipped again for the whole
    remaining backoff window. Does NOT touch cloud `daily_exhausted` flags (those are real
    quota state and reset only at midnight IST)."""
    global _OLLAMA_INFER_BACKOFF_UNTIL, _OLLAMA_HEALTH_RESULT, _OLLAMA_HEALTH_LAST_CHECK
    with _LLM_LOCK:
        _OLLAMA_INFER_BACKOFF_UNTIL = 0.0
        _OLLAMA_HEALTH_RESULT = False
        _OLLAMA_HEALTH_LAST_CHECK = 0.0  # force a re-probe (neg-TTL already expired)


# ── Diagnostic: provider key presence + isolated live probe ──────────────────
# Powers /api/provider-status?probe=1 so the ACTUAL provider state on a deployed HF
# Space (env comes from Secrets, not local .env) is observable. A provider can look
# healthy locally yet be unconfigured or rate-limited on the Space — this is the #1
# cause of "AI unavailable" that can't be reproduced by testing on the terminal.
# (env_key, chat_completions_url, model_env_var, default_model) — all OpenAI-compatible.
_PROBE_CONFIG: dict = {
    "openrouter":  ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_BEST_FREE_MODEL", "openai/gpt-oss-120b:free"),
    "groq":        ("GROQ_API_KEY", "https://api.groq.com/openai/v1/chat/completions", "GROQ_MODEL", "llama-3.3-70b-versatile"),
    "cerebras":    ("CEREBRAS_API_KEY", "https://api.cerebras.ai/v1/chat/completions", "CEREBRAS_MODEL", "llama-3.3-70b"),
    "huggingface": ("HF_TOKEN", "https://router.huggingface.co/novita/v3/openai/chat/completions", "HF_INFERENCE_MODEL", "meta-llama/Llama-3.1-8B-Instruct"),
    "gemini":      ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "GEMINI_MODEL", "gemini-flash-latest"),
    "sambanova":   ("SAMBANOVA_API_KEY", "https://api.sambanova.ai/v1/chat/completions", "SAMBANOVA_MODEL", "Meta-Llama-3.3-70B-Instruct"),
    "nvidia":      ("NVIDIA_API_KEY", "https://integrate.api.nvidia.com/v1/chat/completions", "NVIDIA_MODEL", "nvidia/llama-3.3-nemotron-super-49b-v1"),
}


def provider_key_status() -> dict:
    """Which provider API keys are present in the current environment.

    Reads env vars directly, so on a deployed HF Space it reveals which Secrets are
    actually configured there — the difference that makes AI work locally (.env) but
    fail on the Space when a key was never synced via export_env_secrets.py."""
    st = {name: bool(os.environ.get(cfg[0], "").strip()) for name, cfg in _PROBE_CONFIG.items()}
    st["ollama"] = bool(os.environ.get("OLLAMA_ENDPOINT", "").strip())
    return st


def probe_provider(name: str, timeout: int = 12) -> dict:
    """Make a single isolated 1-token call to one provider and report the result.

    Diagnostic only — does NOT mutate the shared _PROVIDER_STATUS routing flags, so
    probing never perturbs live prediction routing. Returns
    {configured, ok, status, model, latency_ms, error}."""
    if name == "ollama":
        ep = os.environ.get("OLLAMA_ENDPOINT", "").strip()
        if not ep:
            return {"configured": False, "ok": False, "error": "OLLAMA_ENDPOINT not set"}
        try:
            from ollama_client import check_ollama_health, get_ollama_model
            t0 = time.time()
            ok = check_ollama_health(ep, timeout=timeout)
            return {"configured": True, "ok": bool(ok),
                    "model": get_ollama_model(ep) if ok else None,
                    "latency_ms": round((time.time() - t0) * 1000)}
        except Exception as e:
            return {"configured": True, "ok": False, "error": str(e)[:200]}

    cfg = _PROBE_CONFIG.get(name)
    if not cfg:
        return {"configured": False, "ok": False, "error": f"unknown provider {name}"}
    env_key, url, model_env, default_model = cfg
    api_key = os.environ.get(env_key, "").strip()
    if not api_key:
        return {"configured": False, "ok": False, "error": f"{env_key} not set"}
    model = (os.environ.get(model_env) or default_model).strip()
    t0 = time.time()
    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": "Reply with OK"}],
                  "temperature": 0.0, "max_tokens": 5},
            timeout=timeout,
        )
        latency = round((time.time() - t0) * 1000)
        ok = resp.status_code == 200
        out = {"configured": True, "ok": ok, "status": resp.status_code,
               "model": model, "latency_ms": latency}
        if not ok:
            out["error"] = resp.text[:200]
        return out
    except Exception as e:
        return {"configured": True, "ok": False, "model": model,
                "latency_ms": round((time.time() - t0) * 1000), "error": str(e)[:200]}


def make_chat_call(
    messages: List[Dict],
    max_tokens: int,
    temperature: float = 0.3,
    fast_fail_on_rate_limit: bool = False,
    task_offset: int = 0,
    max_retries: int = 0,
    call_timeout: int = 20,
    preferred_provider: str | None = None,
) -> tuple[str, str, str]:
    """
    Call an LLM with the given messages.
    Provider order is dynamic: best available cloud provider(s) → Ollama → remaining cloud.
    When all cloud providers are daily-exhausted, Ollama is promoted to Phase 1.

    task_offset rotates the starting provider among the ones currently available, so concurrent
    calls for different stocks/tasks spread across providers instead of all piling onto the same
    "best" one. preferred_provider, if given and available, is forced to the front instead
    (used to pin a specific provider when a caller wants to avoid the automatic rotation).

    Retries up to max_retries passes (default: AI_MAX_RETRIES env var, fallback 3).
    fast_fail_on_rate_limit=True: single pass, no Ollama, no sleep (backtest / low-latency).

    Returns (content, provider, model).
    Raises RuntimeError when all retries are exhausted.
    """
    _call_start = time.time()

    with _LLM_LOCK:
        if time.time() < _LLM_DISABLED_UNTIL:
            raise RuntimeError("LLM providers on cooldown — rate limit hit recently")

    # ── Retry helper: transient network errors only (not 429) ─────────────────
    def _retry_post(fn, retries: int = 2, backoff: float = 1.5):
        # fast_fail: fail immediately on first timeout — don't burn 40s retrying a slow provider
        if fast_fail_on_rate_limit:
            retries = 0
        last_exc = None
        for attempt in range(retries + 1):
            try:
                return fn()
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                last_exc = exc
                if attempt < retries:
                    time.sleep(backoff * (attempt + 1))
        raise last_exc  # type: ignore[misc]

    # ── Provider 1: OpenRouter ────────────────────────────────────────────────
    def _try_openrouter():
        if not _is_provider_available("openrouter", fast_fail_on_rate_limit):
            return None
        api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            logger.debug("OpenRouter skipped — OPENROUTER_API_KEY not set")
            return None
        model = (os.environ.get("OPENROUTER_BEST_FREE_MODEL") or "openai/gpt-oss-120b:free").strip()
        fallback_chain_raw = os.environ.get("OPENROUTER_FREE_MODELS", "")
        fallback_models = [m.strip() for m in fallback_chain_raw.split(",") if m.strip() and m.strip() != model]
        models_to_try = [model] + fallback_models[:9]

        for try_model in models_to_try:
            try:
                resp = _retry_post(lambda m=try_model: requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": m, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
                    timeout=12,
                ))
                if resp.status_code == 429:
                    _body = resp.text
                    if "free-models-per-day" in _body or "free_models_per_day" in _body:
                        _mark_daily_exhausted("openrouter")
                        return None
                    logger.warning("OpenRouter rate-limited on %s (429) — trying next model", try_model)
                    continue
                if resp.status_code == 401:
                    logger.error("OpenRouter auth failed (401) — check OPENROUTER_API_KEY")
                    return None
                if resp.status_code in (400, 404, 422):
                    logger.debug("OpenRouter model %s unavailable (%s) — trying next", try_model, resp.status_code)
                    continue
                if resp.status_code == 200:
                    content = (((resp.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
                    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                    if content and not content.lstrip().startswith("<"):
                        _mark_ok("openrouter")
                        return content, "openrouter", try_model
                    if content:
                        logger.debug("OpenRouter %s — content starts with '<', skipping", try_model)
                    else:
                        logger.debug("OpenRouter %s returned empty content", try_model)
                else:
                    logger.warning("OpenRouter %s status %s — body: %s", try_model, resp.status_code, resp.text[:200])
            except Exception as exc:
                logger.debug("OpenRouter call failed for %s: %s", try_model, exc)

        cooldown = 5 if fast_fail_on_rate_limit else _OPENROUTER_COOLDOWN_SECS
        _mark_rate_limited("openrouter", cooldown)
        logger.warning("OpenRouter exhausted (no model produced content) — cooldown %.0fs", cooldown)
        return None

    # ── Provider 2: Groq ──────────────────────────────────────────────────────
    def _try_groq():
        if not _is_provider_available("groq", fast_fail_on_rate_limit):
            return None
        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        if not api_key:
            logger.debug("Groq skipped — GROQ_API_KEY not set")
            return None
        primary = "llama-3.3-70b-versatile"
        fallback_chain_raw = os.environ.get("GROQ_FREE_MODELS", "")
        fallbacks = [m.strip() for m in fallback_chain_raw.split(",") if m.strip() and m.strip() != primary]
        models_to_try = [primary] + fallbacks[:3]

        for try_model in models_to_try:
            try:
                resp = _retry_post(lambda m=try_model: requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": m, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
                    timeout=15,
                ))
                if resp.status_code == 429:
                    logger.warning("Groq rate-limited on %s (429) — trying next model", try_model)
                    if not fast_fail_on_rate_limit:
                        time.sleep(1)
                    continue
                if resp.status_code == 401:
                    logger.error("Groq auth failed (401) — check GROQ_API_KEY")
                    return None
                if resp.status_code in (404, 422):
                    logger.debug("Groq model %s unavailable (%s) — trying next", try_model, resp.status_code)
                    continue
                if resp.status_code == 200:
                    content = (((resp.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
                    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                    if content and not content.lstrip().startswith("<"):
                        _mark_ok("groq")
                        return content, "groq", try_model
                    if content:
                        logger.debug("Groq %s — content starts with '<', skipping", try_model)
                    else:
                        logger.debug("Groq %s returned empty content", try_model)
                else:
                    logger.warning("Groq %s status %s — body: %s", try_model, resp.status_code, resp.text[:200])
            except Exception as exc:
                logger.debug("Groq call failed for %s: %s", try_model, exc)

        _mark_rate_limited("groq", 5 if fast_fail_on_rate_limit else 60)
        return None

    # ── Provider 3: Cerebras ──────────────────────────────────────────────────
    def _try_cerebras():
        if not _is_provider_available("cerebras", fast_fail_on_rate_limit):
            return None
        api_key = os.environ.get("CEREBRAS_API_KEY", "").strip()
        if not api_key:
            logger.debug("Cerebras skipped — CEREBRAS_API_KEY not set")
            return None
        primary = os.environ.get("CEREBRAS_MODEL", "llama-3.3-70b").strip()
        fallback_chain_raw = os.environ.get("CEREBRAS_FALLBACK_MODELS", "llama-3.1-8b")
        fallbacks = [m.strip() for m in fallback_chain_raw.split(",") if m.strip() and m.strip() != primary]
        models_to_try = [primary] + fallbacks[:2]

        for try_model in models_to_try:
            try:
                resp = _retry_post(lambda m=try_model: requests.post(
                    "https://api.cerebras.ai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": m, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
                    timeout=20,
                ))
                if resp.status_code == 429:
                    logger.warning("Cerebras rate-limited on %s (429) — trying next model", try_model)
                    continue
                if resp.status_code == 401:
                    logger.error("Cerebras auth failed (401) — check CEREBRAS_API_KEY")
                    return None
                if resp.status_code in (400, 404, 422):
                    logger.debug("Cerebras model %s unavailable (%s) — trying next", try_model, resp.status_code)
                    continue
                if resp.status_code == 200:
                    content = (((resp.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
                    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                    if content and not content.lstrip().startswith("<"):
                        _mark_ok("cerebras")
                        return content, "cerebras", try_model
                    if content:
                        logger.debug("Cerebras %s — content starts with '<', skipping", try_model)
                    else:
                        logger.debug("Cerebras %s returned empty content", try_model)
                else:
                    logger.warning("Cerebras %s status %s — body: %s", try_model, resp.status_code, resp.text[:200])
            except Exception as exc:
                logger.debug("Cerebras call failed for %s: %s", try_model, exc)

        _mark_rate_limited("cerebras", 5 if fast_fail_on_rate_limit else 60)
        return None

    # ── Provider 4: HuggingFace ───────────────────────────────────────────────
    def _try_huggingface():
        if not _is_provider_available("huggingface", fast_fail_on_rate_limit):
            return None
        api_key = os.environ.get("HF_TOKEN", "").strip()
        if not api_key:
            logger.debug("HF Inference API skipped — HF_TOKEN not set")
            return None
        primary = (os.environ.get("HF_INFERENCE_MODEL") or "meta-llama/Llama-3.1-8B-Instruct").strip()
        fallback_chain_raw = os.environ.get("HF_INFERENCE_FALLBACK_MODELS", "")
        fallbacks = [m.strip() for m in fallback_chain_raw.split(",") if m.strip() and m.strip() != primary]
        models_to_try = [primary] + fallbacks[:3]

        _HF_ENDPOINTS = [
            "https://router.huggingface.co/novita/v3/openai/chat/completions",
            "https://api-inference.huggingface.co/v1/chat/completions",
        ]
        for try_model in models_to_try:
            try:
                endpoint = _HF_ENDPOINTS[0]
                try:
                    resp = _retry_post(lambda ep=endpoint, m=try_model: requests.post(
                        ep,
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={"model": m, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
                        timeout=30,
                    ))
                except Exception:
                    endpoint = _HF_ENDPOINTS[1]
                    resp = _retry_post(lambda ep=endpoint, m=try_model: requests.post(
                        ep,
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={"model": m, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
                        timeout=30,
                    ))
                if resp.status_code == 429:
                    logger.warning("HF Inference rate-limited on %s (429) — trying next model", try_model)
                    if not fast_fail_on_rate_limit:
                        time.sleep(1)
                    continue
                if resp.status_code == 401:
                    logger.error("HF Inference auth failed (401) — check HF_TOKEN")
                    return None
                if resp.status_code == 402:
                    _mark_daily_exhausted("huggingface")
                    return None
                if resp.status_code in (400, 404, 422, 503):
                    logger.debug("HF Inference model %s unavailable (%s) — trying next", try_model, resp.status_code)
                    continue
                if resp.status_code == 200:
                    content = (((resp.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
                    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                    if content and not content.lstrip().startswith("<"):
                        _mark_ok("huggingface")
                        return content, "huggingface", try_model
                    if content:
                        logger.debug("HF Inference %s — content starts with '<', skipping", try_model)
                    else:
                        logger.debug("HF Inference %s returned empty content", try_model)
                else:
                    logger.warning("HF Inference %s status %s — body: %s", try_model, resp.status_code, resp.text[:200])
            except Exception as exc:
                logger.debug("HF Inference call failed for %s: %s", try_model, exc)

        _mark_rate_limited("huggingface", 5 if fast_fail_on_rate_limit else 30)
        return None

    # ── Extra free tiers: Gemini + SambaNova (OpenAI-compatible) ──────────────
    # Ported from research/providers_ext.py per PRODUCTION_DELTA.md. Large independent daily
    # capacity so `_all_cloud_daily_exhausted()` rarely becomes true → the exhaustion→Ollama
    # funnel stops firing. Both no-op (return None) when their key is unset.
    def _try_openai_compatible(name: str, base_url: str, api_key: str, models_to_try: list[str],
                               daily_on_429: bool):
        """Shared driver for OpenAI-compatible /chat/completions providers.

        Tries EVERY model in models_to_try before giving up on the provider — a 429/503/404 on
        one model (e.g. gemini-flash-latest under high demand) falls through to a sibling model
        (e.g. gemini-flash-lite-latest, which has separate capacity) instead of abandoning the
        whole provider. Only after ALL models fail is the provider marked down. If every failure
        was a quota 429 and daily_on_429 is set, the provider is marked daily-exhausted; otherwise
        a short cooldown is applied so a transient per-minute 429 doesn't sideline it for the day.
        """
        saw_daily_429 = False
        for try_model in models_to_try:
            try:
                resp = _retry_post(lambda m=try_model: requests.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": m, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
                    timeout=20,
                ))
                if resp.status_code == 429:
                    # Try the next model first — sibling models often have independent quota. Only
                    # after all models 429 do we mark the provider down (daily vs short cooldown).
                    # A 429 whose body signals a DAILY quota/billing exhaustion is benched till the
                    # reset even when daily_on_429 is False (per-minute default), so a daily-dead
                    # provider stops being retried first on every call of a batch scan.
                    logger.warning("%s rate-limited on %s (429) — trying next model", name, try_model)
                    if daily_on_429 or _is_daily_quota_429(resp.text or ""):
                        saw_daily_429 = True
                    if not fast_fail_on_rate_limit:
                        time.sleep(1)
                    continue
                if resp.status_code == 401:
                    logger.error("%s auth failed (401) — check API key", name)
                    return None
                if resp.status_code in (400, 404, 410, 422, 503):
                    # 410 = model retired ("no longer available"); 404 = unknown model;
                    # 503 = transient high demand. All: roll over to the next sibling model.
                    logger.debug("%s model %s unavailable (%s) — trying next", name, try_model, resp.status_code)
                    continue
                if resp.status_code == 200:
                    content = (((resp.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
                    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                    if content and not content.lstrip().startswith("<"):
                        _mark_ok(name)
                        return content, name, try_model
                    logger.debug("%s %s returned empty/invalid content", name, try_model)
                else:
                    logger.warning("%s %s status %s — body: %s", name, try_model, resp.status_code, resp.text[:200])
            except Exception as exc:
                logger.debug("%s call failed for %s: %s", name, try_model, exc)
        # All models failed. If we only ever saw quota 429s, mark daily-exhausted so the provider
        # drops to the back until midnight IST; otherwise a short cooldown keeps it in rotation.
        if saw_daily_429:
            _mark_daily_exhausted(name)
        else:
            _mark_rate_limited(name, 5 if fast_fail_on_rate_limit else 60)
        return None

    def _try_gemini():
        if not _is_provider_available("gemini", fast_fail_on_rate_limit):
            return None
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            logger.debug("Gemini skipped — GEMINI_API_KEY not set")
            return None
        # NOTE: the older `gemini-2.5-flash` / `gemini-2.5-flash-lite` names now return HTTP 404
        # ("no longer available to new users") on the OpenAI-compat endpoint — they silently killed
        # this whole provider. Use the alias names that stay valid across model generations, with a
        # multi-model fallback so a 503 (high demand) or 429 (per-model quota) on the primary falls
        # through to a sibling with independent capacity. daily_on_429=False: Gemini free-tier 429s
        # are usually per-minute RPM limits that recover in seconds, so a short cooldown keeps it in
        # rotation instead of benching it until midnight.
        primary = (os.environ.get("GEMINI_MODEL") or "gemini-flash-latest").strip()
        fallback_raw = os.environ.get(
            "GEMINI_FALLBACK_MODELS", "gemini-flash-lite-latest,gemini-2.0-flash"
        )
        fallbacks = [m.strip() for m in fallback_raw.split(",") if m.strip() and m.strip() != primary]
        models_to_try = [primary] + fallbacks[:3]
        return _try_openai_compatible(
            "gemini", "https://generativelanguage.googleapis.com/v1beta/openai",
            api_key, models_to_try, daily_on_429=False,
        )

    def _try_sambanova():
        if not _is_provider_available("sambanova", fast_fail_on_rate_limit):
            return None
        api_key = os.environ.get("SAMBANOVA_API_KEY", "").strip()
        if not api_key:
            logger.debug("SambaNova skipped — SAMBANOVA_API_KEY not set")
            return None
        primary = (os.environ.get("SAMBANOVA_MODEL") or "Meta-Llama-3.3-70B-Instruct").strip()
        fallback_raw = os.environ.get("SAMBANOVA_FALLBACK_MODELS", "Meta-Llama-3.1-8B-Instruct")
        fallbacks = [m.strip() for m in fallback_raw.split(",") if m.strip() and m.strip() != primary]
        models_to_try = [primary] + fallbacks[:2]
        return _try_openai_compatible(
            "sambanova", "https://api.sambanova.ai/v1",
            api_key, models_to_try, daily_on_429=False,
        )

    def _try_nvidia():
        # NVIDIA NIM (build.nvidia.com) — free API key, OpenAI-compatible, large independent
        # daily capacity across many models (Llama-3.3-70B, Nemotron, DeepSeek, Qwen). Zero cost.
        # daily_on_429=False: NIM free-tier 429s are per-minute RPM limits that recover in seconds,
        # so a short cooldown keeps it in rotation instead of benching it until midnight.
        if not _is_provider_available("nvidia", fast_fail_on_rate_limit):
            return None
        api_key = os.environ.get("NVIDIA_API_KEY", "").strip()
        if not api_key:
            logger.debug("NVIDIA NIM skipped — NVIDIA_API_KEY not set")
            return None
        primary = (os.environ.get("NVIDIA_MODEL") or "nvidia/llama-3.3-nemotron-super-49b-v1").strip()
        fallback_raw = os.environ.get(
            "NVIDIA_FALLBACK_MODELS",
            "meta/llama-3.1-8b-instruct",
        )
        fallbacks = [m.strip() for m in fallback_raw.split(",") if m.strip() and m.strip() != primary]
        models_to_try = [primary] + fallbacks[:3]
        return _try_openai_compatible(
            "nvidia", "https://integrate.api.nvidia.com/v1",
            api_key, models_to_try, daily_on_429=False,
        )

    # ── Provider name → function map ─────────────────────────────────────────
    _PROVIDER_FNS = {
        "openrouter":  _try_openrouter,
        "groq":        _try_groq,
        "cerebras":    _try_cerebras,
        "huggingface": _try_huggingface,
        "gemini":      _try_gemini,
        "sambanova":   _try_sambanova,
        "nvidia":      _try_nvidia,
    }

    # ── Ollama (own server, no rate limits — handled outside cloud semaphore) ─
    def _try_ollama_fn():
        try:
            from ollama_client import ollama_chat, get_ollama_model, check_ollama_health
            _ep = os.environ.get("OLLAMA_ENDPOINT", "").strip()
            if not _ep:
                return None
            global _OLLAMA_HEALTH_LAST_CHECK, _OLLAMA_HEALTH_RESULT, _OLLAMA_INFER_BACKOFF_UNTIL
            _now_h = time.time()
            # Skip entirely if a recent inference timed out — don't burn another 45s
            with _LLM_LOCK:
                if _now_h < _OLLAMA_INFER_BACKOFF_UNTIL:
                    logger.debug("Ollama skipped — inference backoff active for %.0fs", _OLLAMA_INFER_BACKOFF_UNTIL - _now_h)
                    return None
                # A cached False expires fast (NEG_TTL) so a waking Space is re-probed; a cached
                # True is trusted for the full TTL to avoid probing a healthy Space repeatedly.
                _ttl = _OLLAMA_HEALTH_TTL if _OLLAMA_HEALTH_RESULT else _OLLAMA_HEALTH_NEG_TTL
                _cv = (_now_h - _OLLAMA_HEALTH_LAST_CHECK) < _ttl
                _ch = _OLLAMA_HEALTH_RESULT if _cv else None
            _fresh_check = _ch is None
            if _ch is None:
                _ch = check_ollama_health(_ep, timeout=35)  # tolerate HF Space cold-start (was 8s, then 20s; 2026-07-31: measured real cold-start ~25.8s, 20s was failing this check almost every time)
                with _LLM_LOCK:
                    _OLLAMA_HEALTH_LAST_CHECK = time.time()
                    _OLLAMA_HEALTH_RESULT = _ch
            if not _ch:
                return None
            _m = get_ollama_model(_ep)
            # Fresh health check means Space just woke from sleep — warmup before real call
            # so the model is loaded and the real inference doesn't hang.
            if _fresh_check:
                from ollama_client import warmup_ollama
                _warm = warmup_ollama(_ep, model=_m, timeout=30)
                if not _warm:
                    with _LLM_LOCK:
                        _OLLAMA_INFER_BACKOFF_UNTIL = time.time() + _OLLAMA_WARMUP_BACKOFF_SECS
                        _OLLAMA_HEALTH_RESULT = False
                    logger.warning("Ollama warmup failed — model still loading, backing off %ds", _OLLAMA_WARMUP_BACKOFF_SECS)
                    return None
                logger.info("Ollama warmup succeeded — model warm, proceeding with inference")
            with _OLLAMA_SEMAPHORE:
                _r = ollama_chat(messages, endpoint=_ep, model=_m, timeout=_OLLAMA_CHAT_TIMEOUT)
            if _r:
                logger.info("LLM: Ollama succeeded")
                return _r, "ollama", _m
            # Inference returned None (timeout or empty) — set backoff so we don't retry immediately
            with _LLM_LOCK:
                _OLLAMA_INFER_BACKOFF_UNTIL = time.time() + _OLLAMA_INFER_BACKOFF_SECS
                _OLLAMA_HEALTH_RESULT = False  # also invalidate health so fast path re-checks later
            logger.warning("Ollama inference failed — backing off for %ds", _OLLAMA_INFER_BACKOFF_SECS)
        except Exception as _e:
            logger.debug("Ollama call failed: %s", _e)
        return None

    # ── Dynamic dispatch ──────────────────────────────────────────────────────
    # Order is re-evaluated on every call:
    #   - Available cloud providers (not exhausted, cooldown expired) come first
    #   - When ALL cloud providers are daily-exhausted, Ollama is promoted to Phase 1
    #   - Otherwise Ollama is the LAST resort — tried only after every cloud provider
    #     (each exhausting its own model list) has failed
    #   - fast_fail runs Ollama once OUTSIDE this pass (see below), so a retry storm doesn't
    #     re-probe the slow Space every pass
    #
    # task_offset rotation (2026-07-17 fix): previously `best = cloud_order[0]` picked the SAME
    # provider for every concurrent call regardless of task_offset — so a whole batch (e.g. 54
    # backtest predictions) all tried the identical "best" provider first, exhausted its rate
    # limit together, then ALL cascaded to the next provider together, repeating the storm down
    # the chain. task_offset (assigned round-robin per stock/task in ai_forecast.py) now rotates
    # the starting pick among the providers that are CURRENTLY AVAILABLE — spreading concurrent
    # calls across providers instead of piling them onto one, while still respecting the
    # cooldown/exhaustion sort (an unavailable provider is never promoted ahead of an available one).
    def _one_pass():
        cloud_order = _get_cloud_order()
        available = [p for p in cloud_order if _is_provider_available(p, fast_fail_on_rate_limit)]
        if preferred_provider and preferred_provider in cloud_order and _is_provider_available(preferred_provider, fast_fail_on_rate_limit):
            ordered = [preferred_provider] + [p for p in cloud_order if p != preferred_provider]
        elif len(available) > 1:
            start = available[task_offset % len(available)]
            ordered = [start] + [p for p in cloud_order if p != start]
        else:
            ordered = cloud_order
        best = ordered[0]
        rest = ordered[1:]
        all_cloud_exhausted = _all_cloud_daily_exhausted()

        # Phase 1: best available cloud OR Ollama if all cloud are daily-exhausted
        if all_cloud_exhausted:
            logger.info("LLM: All cloud providers daily-exhausted — trying Ollama first")
            r = _try_ollama_fn()
            if r is not None:
                return r
        else:
            _LLM_SEMAPHORE.acquire()
            try:
                r = _PROVIDER_FNS[best]()
                if r is not None:
                    return r
            finally:
                _LLM_SEMAPHORE.release()

        # Phase 2: Remaining cloud providers in dynamic order.
        # Try EVERY remaining fast cloud provider (each exhausting its own model list) BEFORE
        # falling to slow local Ollama — the providers have independent quotas, so a rate-limited
        # "best" provider says nothing about the others. (Previously Ollama was tried here, in the
        # middle, which funnelled to a ~34s local call after only the first provider failed while
        # 5 healthy fast providers went untried.)
        if rest:
            _LLM_SEMAPHORE.acquire()
            try:
                for name in rest:
                    r = _PROVIDER_FNS[name]()
                    if r is not None:
                        return r
            finally:
                _LLM_SEMAPHORE.release()

        # Phase 3: Ollama last resort — only when ALL cloud is genuinely down.
        # Skipped under fast_fail (that path runs Ollama once as a last-resort OUTSIDE _one_pass,
        # so a retry storm doesn't re-probe the slow Space every pass). Skipped when all cloud was
        # daily-exhausted because Phase 1 already tried Ollama first.
        if not fast_fail_on_rate_limit and not all_cloud_exhausted:
            r = _try_ollama_fn()
            if r is not None:
                return r

        return None

    result = _one_pass()
    if result is not None:
        return result

    if fast_fail_on_rate_limit:
        # Cloud providers all failed. Ollama has no rate limits — always try it last.
        # Use the shared health cache so a 150-stock scan doesn't burn _OLLAMA_CHAT_TIMEOUT per stock.
        global _OLLAMA_HEALTH_LAST_CHECK, _OLLAMA_HEALTH_RESULT, _OLLAMA_INFER_BACKOFF_UNTIL
        _ep_check = os.environ.get("OLLAMA_ENDPOINT", "").strip()
        if _ep_check:
            from ollama_client import ollama_chat, get_ollama_model, check_ollama_health
            with _LLM_LOCK:
                _now_lr = time.time()
                # Skip if a recent inference timed out
                if _now_lr < _OLLAMA_INFER_BACKOFF_UNTIL:
                    logger.debug("Ollama last-resort skipped — backoff active for %.0fs", _OLLAMA_INFER_BACKOFF_UNTIL - _now_lr)
                else:
                    # Negative results expire fast (NEG_TTL) so a fast-path 20s probe that missed a
                    # cold-starting Space does NOT block this longer cold-start probe.
                    _ttl = _OLLAMA_HEALTH_TTL if _OLLAMA_HEALTH_RESULT else _OLLAMA_HEALTH_NEG_TTL
                    _cached_valid = (_now_lr - _OLLAMA_HEALTH_LAST_CHECK) < _ttl
                    _ch = _OLLAMA_HEALTH_RESULT if _cached_valid else None
                    _now_lr = None  # signal: proceed
            if _now_lr is None:  # not in backoff
                _fresh_lr = _ch is None
                if _ch is None:
                    # No recent result — do the longer probe (HF Space may be cold-starting).
                    # 2026-07-31: raised 25s->35s — a direct curl measurement of the live Space
                    # showed a real cold-start response time of ~25.8s, i.e. the old 25s timeout
                    # was failing this health check almost every time by a hair, right before the
                    # Space finished waking up — so Ollama was silently never reached as a fallback
                    # (every rate-limited batch fell through to "all providers unavailable" instead
                    # of the no-rate-limit Ollama fallback this path exists for).
                    _ch = check_ollama_health(_ep_check, timeout=35)
                    with _LLM_LOCK:
                        _OLLAMA_HEALTH_LAST_CHECK = time.time()
                        _OLLAMA_HEALTH_RESULT = _ch
                if _ch:
                    _m = get_ollama_model(_ep_check)
                    # Warmup on fresh health check — prevents 45s hang on cold-start model loading
                    if _fresh_lr:
                        from ollama_client import warmup_ollama
                        if not warmup_ollama(_ep_check, model=_m, timeout=30):
                            with _LLM_LOCK:
                                _OLLAMA_INFER_BACKOFF_UNTIL = time.time() + _OLLAMA_WARMUP_BACKOFF_SECS
                                _OLLAMA_HEALTH_RESULT = False
                            logger.warning("Ollama last-resort warmup failed — backing off %ds", _OLLAMA_WARMUP_BACKOFF_SECS)
                            raise RuntimeError("All LLM providers unavailable — Ollama cold-start backoff")
                        logger.info("Ollama last-resort warmup succeeded")
                    with _OLLAMA_SEMAPHORE:
                        _r = ollama_chat(messages, endpoint=_ep_check, model=_m, timeout=_OLLAMA_CHAT_TIMEOUT)
                    if _r:
                        logger.info("LLM: Ollama (last-resort fast_fail path) succeeded")
                        return _r, "ollama", _m
                    # Inference failed — backoff so next call doesn't wait again
                    with _LLM_LOCK:
                        _OLLAMA_INFER_BACKOFF_UNTIL = time.time() + _OLLAMA_INFER_BACKOFF_SECS
                        _OLLAMA_HEALTH_RESULT = False
                    logger.warning("Ollama last-resort inference failed — backing off %ds", _OLLAMA_INFER_BACKOFF_SECS)
                else:
                    logger.debug("LLM: Ollama last-resort skipped (cached unhealthy)")
        raise RuntimeError("All LLM providers unavailable — all rate-limited or unconfigured")

    # ── Retry loop ────────────────────────────────────────────────────────────
    if max_retries <= 0:
        max_retries = int(os.getenv("AI_MAX_RETRIES", "3"))

    for _retry_attempt in range(max_retries - 1):
        _wait = float(_ALL_PROVIDERS_RETRY_WAIT_SECS)
        logger.warning(
            "All LLM providers unavailable (attempt %d/%d) — waiting %.1fs before retry",
            _retry_attempt + 2, max_retries, _wait,
        )
        time.sleep(_wait)
        result = _one_pass()
        if result is not None:
            return result

    raise RuntimeError(
        f"All LLM providers unavailable after {max_retries} attempts — all rate-limited or unconfigured"
    )


if __name__ == "__main__":
    print("Testing LLM provider chain...")
    order = _get_cloud_order()
    print(f"Current provider order: {order}")
    for name in _CLOUD_PROVIDERS:
        s = _PROVIDER_STATUS[name]
        print(f"  {name}: daily_exhausted={s['daily_exhausted']}, avail_at={s['avail_at']:.0f}, fail_streak={s['fail_streak']}")
    try:
        content, provider, model = make_chat_call(
            [{"role": "user", "content": "Say 'OK' and nothing else."}],
            max_tokens=5,
            temperature=0.0,
            fast_fail_on_rate_limit=True,
            max_retries=1,
        )
        print(f"Provider: {provider}  Model: {model}")
        print(f"Response: {content}")
    except RuntimeError as e:
        print(f"No provider available: {e}")
