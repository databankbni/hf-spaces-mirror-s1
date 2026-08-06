"""thebeast.betting — edge detection + Kelly staking (F-004)."""
from __future__ import annotations

from .edge import (
    BettingEdge,
    analyze_moneyline,
    analyze_totals,
    evaluate_market,
    expected_value,
    kelly_stake,
    log_loss,
)
from .odds import (
    MarketOdds,
    american_to_decimal_b,
    american_to_implied,
    devig_pair,
)

__all__ = [
    "MarketOdds",
    "BettingEdge",
    "american_to_implied",
    "american_to_decimal_b",
    "devig_pair",
    "kelly_stake",
    "expected_value",
    "evaluate_market",
    "analyze_moneyline",
    "analyze_totals",
    "log_loss",
]
