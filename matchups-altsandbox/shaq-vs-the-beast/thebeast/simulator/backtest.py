"""Walk-forward backtest — the MVP acceptance gate (F-002/F-004).

Runs the full pipeline over a holdout slate, then compares the model's win
probabilities to the Vegas closing line. Definition of MVP done (SPEC.md):

    model log-loss  <  closing-line log-loss   on the 2024 holdout.

The market benchmark is the *de-vigged* two-way closing line, not the raw
implied probabilities. De-vigging is the rigorous comparison: raw implied
probabilities sum to >1 and are systematically over-confident, which would
inflate the market's log-loss and make it artificially easy to "beat".

Real GameOutcomes (actual result + closing odds) are supplied by the data
layer; this module owns only the run + scoring logic, so it is fully testable
against the synthetic-fallback pipeline with no network or database.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..betting.edge import log_loss
from ..betting.odds import devig_pair
from ..data.repository import GameRepository
from ..pipeline import simulate_matchup
from .config import BacktestKnobs


@dataclass
class GameOutcome:
    """An actual holdout game result paired with its closing line."""
    game_id: str
    home_won: bool
    home_closing_ml: int
    away_closing_ml: int
    home_team: Optional[str] = None
    away_team: Optional[str] = None


@dataclass
class BacktestReport:
    """Scorecard for one walk-forward backtest run."""
    n_games: int
    model_log_loss: float
    market_log_loss: float
    model_beats_market: bool
    model_brier: float
    market_brier: float

    def format(self) -> str:
        verdict = "PASS ✅" if self.model_beats_market else "FAIL ❌"
        return (
            f"Backtest over {self.n_games} games\n"
            f"  model  log-loss : {self.model_log_loss:.5f}  brier {self.model_brier:.5f}\n"
            f"  market log-loss : {self.market_log_loss:.5f}  brier {self.market_brier:.5f}\n"
            f"  MVP gate (model < market): {verdict}"
        )


def market_probabilities(home_ml: int, away_ml: int) -> tuple[float, float]:
    """De-vigged (true) closing-line probabilities for a two-way market."""
    return devig_pair(home_ml, away_ml)


def _brier(probs: list[float], actuals: list[int]) -> float:
    return sum((p - y) ** 2 for p, y in zip(probs, actuals)) / len(probs)


def backtest_holdout(
    outcomes: list[GameOutcome],
    repo: Optional[GameRepository] = None,
    n: int = 200,
    seed: Optional[int] = None,
    season: int = 2024,
    knobs: Optional[BacktestKnobs] = None,
    calibrate: bool = False,
) -> BacktestReport:
    """Simulate every holdout game and score the model against the closing line.

    `calibrate=False` (default) measures the *raw* simulator — the research
    baseline. Pass True to score the shipped, Platt-calibrated win probability.
    """
    if not outcomes:
        raise ValueError("cannot backtest an empty outcome set")

    pipeline_knobs = knobs.pipeline if knobs is not None else None
    model_probs: list[float] = []
    market_probs: list[float] = []
    actuals: list[int] = []

    for game in outcomes:
        result, _ = simulate_matchup(
            game.game_id, repo,
            home_team=game.home_team, away_team=game.away_team,
            n=n, seed=seed, season=season, knobs=pipeline_knobs,
            calibrate=calibrate,
        )
        model_probs.append(result.home_win_probability)
        market_probs.append(market_probabilities(game.home_closing_ml, game.away_closing_ml)[0])
        actuals.append(1 if game.home_won else 0)

    model_ll = log_loss(model_probs, actuals)
    market_ll = log_loss(market_probs, actuals)
    return BacktestReport(
        n_games=len(outcomes),
        model_log_loss=model_ll,
        market_log_loss=market_ll,
        model_beats_market=model_ll < market_ll,
        model_brier=_brier(model_probs, actuals),
        market_brier=_brier(market_probs, actuals),
    )
