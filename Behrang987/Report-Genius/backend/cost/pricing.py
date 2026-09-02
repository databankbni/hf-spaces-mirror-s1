"""USD pricing helpers for tokens and LlamaParse pages."""

from __future__ import annotations

from backend.config import settings
from backend.observability.tracing import estimate_cost


def _pricing_key_for_model(model: str) -> str | None:
    """Return the ``model_pricing`` key that would price ``model``, or None."""
    pricing = settings.model_pricing or {}
    if not model:
        return None
    if model in pricing:
        return model
    best_key = ""
    for key in pricing:
        if model.startswith(key) and len(key) > len(best_key):
            best_key = key
    return best_key or None


def model_is_priced(model: str) -> bool:
    """True when ``model`` matches an entry in ``settings.model_pricing``."""
    return _pricing_key_for_model(model) is not None


def price_tokens(
    model: str, prompt_tokens: int, completion_tokens: int = 0
) -> tuple[float, bool]:
    """Estimate USD for a chat/embedding token usage.

    Returns ``(cost_usd, priced)``. Unknown models return ``(0.0, False)`` so
    the ledger can flag unpriced calls instead of pretending they are free.
    """
    priced = model_is_priced(model)
    if not priced:
        return 0.0, False
    return estimate_cost(model, int(prompt_tokens or 0), int(completion_tokens or 0)), True


def credits_per_page(tier: str) -> float | None:
    """Credits charged per page for a LlamaParse tier, or None if unknown."""
    table = settings.llamaparse_credits_per_page or {}
    key = (tier or "").strip().lower()
    if not key:
        return None
    if key in table:
        return float(table[key])
    # tolerate hyphen/underscore variants
    alt = key.replace("-", "_")
    if alt in table:
        return float(table[alt])
    return None


def price_pages(tier: str, pages: int) -> tuple[float, float, bool]:
    """Price a LlamaParse (or similar) page job.

    Returns ``(cost_usd, credits, priced)``.
    ``cost_usd = pages × credits_per_page[tier] × usd_per_credit``.
    """
    n = max(0, int(pages or 0))
    cpp = credits_per_page(tier)
    if cpp is None:
        return 0.0, 0.0, False
    credits = float(n) * float(cpp)
    usd_per = float(settings.llamaparse_usd_per_credit or 0.0)
    cost = round(credits * usd_per, 6)
    return cost, credits, True
