"""Tests for thebeast.simulator.backtest — walk-forward holdout harness.

Test-first (Constitution Article III). Uses the synthetic-fallback pipeline
(no repo) so games run deterministically by seed; the market benchmark and
log-loss arithmetic are checked against hand computations.
"""
from __future__ import annotations

import math

import pytest

from thebeast.betting.odds import devig_pair
from thebeast.simulator.backtest import (
    BacktestReport,
    GameOutcome,
    backtest_holdout,
    market_probabilities,
)
from thebeast.betting.edge import log_loss


# ─── Market benchmark ─────────────────────────────────────────────────────────

class TestMarketProbabilities:
    def test_devigged_pair_sums_to_one(self) -> None:
        p_home, p_away = market_probabilities(-150, +130)
        assert abs(p_home + p_away - 1.0) < 1e-9

    def test_matches_devig_pair(self) -> None:
        assert market_probabilities(-150, +130) == devig_pair(-150, +130)


# ─── Backtest mechanics ───────────────────────────────────────────────────────

def _outcomes() -> list[GameOutcome]:
    return [
        GameOutcome(game_id="g1", home_won=True, home_closing_ml=-150, away_closing_ml=+130),
        GameOutcome(game_id="g2", home_won=False, home_closing_ml=+120, away_closing_ml=-140),
        GameOutcome(game_id="g3", home_won=True, home_closing_ml=-110, away_closing_ml=-110),
        GameOutcome(game_id="g4", home_won=False, home_closing_ml=+200, away_closing_ml=-240),
    ]


class TestBacktestHoldout:
    def test_report_fields(self) -> None:
        report = backtest_holdout(_outcomes(), repo=None, n=100, seed=1)
        assert isinstance(report, BacktestReport)
        assert report.n_games == 4
        assert math.isfinite(report.model_log_loss)
        assert math.isfinite(report.market_log_loss)
        assert report.model_beats_market == (report.model_log_loss < report.market_log_loss)

    def test_market_log_loss_matches_hand_computation(self) -> None:
        outcomes = _outcomes()
        report = backtest_holdout(outcomes, repo=None, n=50, seed=1)
        probs = [market_probabilities(o.home_closing_ml, o.away_closing_ml)[0]
                 for o in outcomes]
        actuals = [1 if o.home_won else 0 for o in outcomes]
        assert abs(report.market_log_loss - log_loss(probs, actuals)) < 1e-9

    def test_deterministic_with_seed(self) -> None:
        r1 = backtest_holdout(_outcomes(), repo=None, n=100, seed=7)
        r2 = backtest_holdout(_outcomes(), repo=None, n=100, seed=7)
        assert r1.model_log_loss == r2.model_log_loss

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            backtest_holdout([], repo=None, n=10, seed=1)

    def test_brier_scores_in_range(self) -> None:
        report = backtest_holdout(_outcomes(), repo=None, n=100, seed=1)
        assert 0.0 <= report.model_brier <= 1.0
        assert 0.0 <= report.market_brier <= 1.0
