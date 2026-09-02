from __future__ import annotations

from typing import Dict, Iterable, Tuple

from .models import Usage

PRICES: Dict[str, Tuple[float, float]] = {
    "gemini-3.6-flash": (1.50, 7.50),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.1-pro": (2.00, 12.00),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.15, 1.25),
    "gemini-2.5-pro": (1.25, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "claude-haiku": (1.00, 5.00),
    "claude-sonnet": (3.00, 15.00),
    "mock": (0.0, 0.0),
}
PRICES_SOURCE = "https://ai.google.dev/gemini-api/docs/pricing, checked 2026-08-02"
UNKNOWN_MODEL_PRICE = (0.0, 0.0)


def rate_for(model: str) -> Tuple[float, float]:
    name = (model or "").lower()
    best: Tuple[int, Tuple[float, float]] = (0, UNKNOWN_MODEL_PRICE)
    for prefix, rate in PRICES.items():
        if name.startswith(prefix) and len(prefix) > best[0]:
            best = (len(prefix), rate)
    return best[1]


FREE_TIER_MODELS = ("gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite")


def is_known(model: str) -> bool:
    return rate_for(model) != UNKNOWN_MODEL_PRICE or (model or "").lower().startswith("mock")


def price(usage: Usage) -> float:
    inp, out = rate_for(usage.model)
    return (usage.prompt_tokens / 1_000_000.0) * inp + (usage.completion_tokens / 1_000_000.0) * out


def total(usages: Iterable[Usage]) -> float:
    return sum(price(u) for u in usages)


def summarise(usages: Iterable[Usage]) -> Dict[str, float]:
    usages = list(usages)
    return {
        "calls": sum(u.calls for u in usages),
        "prompt_tokens": sum(u.prompt_tokens for u in usages),
        "completion_tokens": sum(u.completion_tokens for u in usages),
        "usd": round(total(usages), 6),
    }
