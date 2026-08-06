"""American moneyline conversions and the MarketOdds container (F-004).

American moneyline → break-even (implied) probability and net decimal odds `b`:

    ml < 0:  implied = |ml| / (|ml| + 100)     b = 100 / |ml|
    ml > 0:  implied = 100 / (ml + 100)         b = ml / 100

`implied` includes the bookmaker's vig, so a home/away pair sums to > 1.0;
`devig_pair` normalizes a two-way market back to true probabilities.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MarketOdds:
    """Sportsbook odds for one game (American moneylines + total)."""
    game_id: str
    home_ml: int
    away_ml: int
    total_line: float
    over_ml: int
    under_ml: int


def american_to_implied(ml: int) -> float:
    """Break-even win probability implied by an American moneyline (with vig)."""
    if ml < 0:
        return abs(ml) / (abs(ml) + 100.0)
    return 100.0 / (ml + 100.0)


def american_to_decimal_b(ml: int) -> float:
    """Net decimal odds `b`: profit per unit staked on a win."""
    if ml < 0:
        return 100.0 / abs(ml)
    return ml / 100.0


def devig_pair(ml_a: int, ml_b: int) -> tuple[float, float]:
    """Remove the vig from a two-way market; returns (p_a, p_b) summing to 1.0."""
    ia = american_to_implied(ml_a)
    ib = american_to_implied(ml_b)
    total = ia + ib
    return ia / total, ib / total
