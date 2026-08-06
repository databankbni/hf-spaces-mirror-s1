"""Edge detection + Kelly staking (F-004).

Compares a model probability to market odds, sizes wagers with fractional
Kelly, and produces a BettingEdge. The Kelly form specified in SPEC.md,

    f* = edge / (1 - implied)

is algebraically identical to textbook full Kelly f* = p - (1-p)/b for net
decimal odds b (since implied = 1/(1+b)); `kelly_fraction` then scales it down
(Quarter-/Half-Kelly) and a hard cap prevents overbetting.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Optional

import numpy as np

from ..simulator.aggregate import GameSimulationRaw, GameSimulationResult
from .odds import MarketOdds, american_to_decimal_b, american_to_implied

# The four game markets analysed here, plus the run-line and player-prop
# markets the best-bets ranker prices through `evaluate_market`.
Market = Literal["home_ml", "away_ml", "over", "under",
                 "home_rl", "away_rl", "prop_over", "prop_under"]


@dataclass
class BettingEdge:
    game_id: str
    market: Market
    model_probability: float
    implied_probability: float
    edge: float
    kelly_fraction: float
    recommended_stake_pct: float
    expected_value: float
    confidence_interval_95: tuple[float, float] = (0.0, 0.0)


def kelly_stake(model_p: float, implied: float, kelly_fraction: float) -> float:
    """Fractional-Kelly stake as a fraction of bankroll.

    Returns 0.0 when there is no positive edge, and never exceeds
    `kelly_fraction` (hard cap against overbetting).
    """
    edge = model_p - implied
    if edge <= 0.0 or implied >= 1.0:
        return 0.0
    full_kelly = edge / (1.0 - implied)
    stake = kelly_fraction * full_kelly
    return float(min(stake, kelly_fraction))


def expected_value(model_p: float, american_ml: int) -> float:
    """Expected profit per unit staked: p·b - (1-p) for net decimal odds b."""
    b = american_to_decimal_b(american_ml)
    return model_p * b - (1.0 - model_p)


def _ci95(p: float, n: int) -> tuple[float, float]:
    """Normal-approximation 95% CI on a Monte Carlo win probability."""
    if n <= 0:
        return (p, p)
    se = math.sqrt(max(p * (1.0 - p), 0.0) / n)
    return (max(0.0, p - 1.96 * se), min(1.0, p + 1.96 * se))


def evaluate_market(
    game_id: str,
    market: Market,
    model_probability: float,
    n_sims: int,
    american_ml: int,
    kelly_fraction: float,
) -> BettingEdge:
    """Build a BettingEdge for one market given a model probability and odds."""
    implied = american_to_implied(american_ml)
    return BettingEdge(
        game_id=game_id,
        market=market,
        model_probability=model_probability,
        implied_probability=implied,
        edge=model_probability - implied,
        kelly_fraction=kelly_fraction,
        recommended_stake_pct=kelly_stake(model_probability, implied, kelly_fraction),
        expected_value=expected_value(model_probability, american_ml),
        confidence_interval_95=_ci95(model_probability, n_sims),
    )


def analyze_moneyline(
    result: GameSimulationResult,
    odds: MarketOdds,
    kelly_fraction: float = 0.25,
) -> list[BettingEdge]:
    """Edges for the home and away moneyline markets."""
    p_home = result.home_win_probability
    return [
        evaluate_market(result.game_id, "home_ml", p_home, result.n,
                        odds.home_ml, kelly_fraction),
        evaluate_market(result.game_id, "away_ml", 1.0 - p_home, result.n,
                        odds.away_ml, kelly_fraction),
    ]


def analyze_totals(
    raw: GameSimulationRaw,
    odds: MarketOdds,
    kelly_fraction: float = 0.25,
) -> list[BettingEdge]:
    """Edges for the over and under markets at `odds.total_line`.

    Pushes (total exactly equal to the line) are excluded from both counts, so
    over and under probabilities are computed over decided games only.
    """
    totals = np.asarray(raw.totals)
    decided = int(np.sum(totals != odds.total_line))
    n = decided if decided > 0 else len(totals)
    p_over = float(np.sum(totals > odds.total_line)) / n if n else 0.0
    p_under = float(np.sum(totals < odds.total_line)) / n if n else 0.0
    game_id = odds.game_id
    return [
        evaluate_market(game_id, "over", p_over, n, odds.over_ml, kelly_fraction),
        evaluate_market(game_id, "under", p_under, n, odds.under_ml, kelly_fraction),
    ]


def log_loss(probabilities: list[float], outcomes: list[int], eps: float = 1e-15) -> float:
    """Mean binary log-loss; the primary MVP gate metric vs the Vegas closing line."""
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must be the same length")
    if not probabilities:
        raise ValueError("cannot compute log-loss over an empty sequence")
    total = 0.0
    for p, y in zip(probabilities, outcomes):
        p = min(max(p, eps), 1.0 - eps)
        total += -(y * math.log(p) + (1 - y) * math.log(1.0 - p))
    return total / len(probabilities)
