"""Tests for thebeast.betting — edge detection + Kelly staking (F-004).

Test-first (Constitution Article III). Pure math is exercised directly; the
sim-result wrappers use small hand-built GameSimulationResult/Raw objects.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from thebeast.betting.odds import (
    MarketOdds,
    american_to_decimal_b,
    american_to_implied,
    devig_pair,
)
from thebeast.betting.edge import (
    BettingEdge,
    analyze_moneyline,
    analyze_totals,
    evaluate_market,
    expected_value,
    kelly_stake,
    log_loss,
)
from thebeast.simulator.aggregate import GameSimulationRaw, GameSimulationResult


# ─── Odds conversions ─────────────────────────────────────────────────────────

class TestOdds:
    def test_negative_ml_implied(self) -> None:
        assert abs(american_to_implied(-150) - 0.60) < 1e-9

    def test_positive_ml_implied(self) -> None:
        assert abs(american_to_implied(+130) - (100 / 230)) < 1e-9

    def test_negative_ml_decimal_b(self) -> None:
        assert abs(american_to_decimal_b(-150) - (100 / 150)) < 1e-9

    def test_positive_ml_decimal_b(self) -> None:
        assert abs(american_to_decimal_b(+130) - 1.30) < 1e-9

    def test_implied_is_inverse_of_b(self) -> None:
        for ml in (-150, +130, -110, +250, -300):
            b = american_to_decimal_b(ml)
            assert abs(american_to_implied(ml) - 1.0 / (1.0 + b)) < 1e-9

    def test_devig_sums_to_one(self) -> None:
        h, a = devig_pair(-150, +130)
        assert abs(h + a - 1.0) < 1e-9
        assert h > a  # favorite has higher no-vig probability


# ─── Kelly staking ────────────────────────────────────────────────────────────

class TestKelly:
    def test_zero_stake_when_no_edge(self) -> None:
        # model prob equals implied → no edge → zero stake
        implied = american_to_implied(-150)
        assert kelly_stake(model_p=implied, implied=implied, kelly_fraction=0.25) == 0.0

    def test_zero_stake_when_negative_edge(self) -> None:
        implied = american_to_implied(-150)
        assert kelly_stake(model_p=implied - 0.1, implied=implied, kelly_fraction=0.25) == 0.0

    def test_positive_stake_when_edge(self) -> None:
        implied = american_to_implied(+130)  # ~0.435
        stake = kelly_stake(model_p=0.55, implied=implied, kelly_fraction=0.25)
        assert stake > 0.0

    def test_stake_never_exceeds_kelly_fraction(self) -> None:
        # Even a near-certain model probability is capped at the fraction.
        implied = american_to_implied(+130)
        stake = kelly_stake(model_p=0.999, implied=implied, kelly_fraction=0.25)
        assert stake <= 0.25 + 1e-12

    def test_full_kelly_matches_textbook(self) -> None:
        # f* = p - (1-p)/b for net odds b; spec form edge/(1-implied) must agree.
        ml = +130
        implied = american_to_implied(ml)
        b = american_to_decimal_b(ml)
        p = 0.55
        textbook = p - (1 - p) / b
        spec = kelly_stake(model_p=p, implied=implied, kelly_fraction=1.0)
        assert abs(textbook - spec) < 1e-9


# ─── Expected value ───────────────────────────────────────────────────────────

class TestExpectedValue:
    def test_positive_when_model_beats_implied(self) -> None:
        assert expected_value(model_p=0.55, american_ml=+130) > 0

    def test_negative_when_model_below_implied(self) -> None:
        assert expected_value(model_p=0.30, american_ml=+130) < 0

    def test_zero_at_break_even(self) -> None:
        ml = -150
        implied = american_to_implied(ml)
        assert abs(expected_value(model_p=implied, american_ml=ml)) < 1e-9


# ─── evaluate_market ──────────────────────────────────────────────────────────

class TestEvaluateMarket:
    def test_edge_sign_and_fields(self) -> None:
        edge = evaluate_market(
            game_id="g1", market="home_ml", model_probability=0.55,
            n_sims=2000, american_ml=+130, kelly_fraction=0.25,
        )
        assert isinstance(edge, BettingEdge)
        assert edge.edge > 0
        assert edge.recommended_stake_pct > 0
        lo, hi = edge.confidence_interval_95
        assert lo < edge.model_probability < hi

    def test_no_bet_when_market_efficient(self) -> None:
        implied = american_to_implied(-150)
        edge = evaluate_market(
            game_id="g1", market="home_ml", model_probability=implied,
            n_sims=2000, american_ml=-150, kelly_fraction=0.5,
        )
        assert edge.recommended_stake_pct == 0.0


# ─── log loss (MVP gate utility) ──────────────────────────────────────────────

class TestLogLoss:
    def test_perfect_prediction_low_loss(self) -> None:
        ll = log_loss([0.99, 0.01], [1, 0])
        assert ll < 0.02

    def test_confident_wrong_high_loss(self) -> None:
        ll = log_loss([0.01, 0.99], [1, 0])
        assert ll > 3.0

    def test_clips_extremes(self) -> None:
        # 0.0 prob on a positive outcome would be infinite without clipping
        ll = log_loss([0.0], [1])
        assert math.isfinite(ll)


# ─── Wrappers over sim outputs ────────────────────────────────────────────────

def _make_result(home_win_probability: float, n: int = 2000) -> GameSimulationResult:
    return GameSimulationResult(
        game_id="2024-NYY-BOS", home="BOS", away="NYY", n=n,
        home_win_probability=home_win_probability,
        home_run_mean=4.5, home_run_median=4.0, home_run_p10=1.0, home_run_p90=8.0,
        away_run_mean=4.4, away_run_median=4.0, away_run_p10=1.0, away_run_p90=8.0,
        total_mean=8.9, total_median=9.0, total_p10=4.0, total_p90=14.0,
        extra_inning_pct=0.08, spread_mean=0.1, player_lines=[],
    )


class TestAnalyzeMoneyline:
    def test_returns_home_and_away(self) -> None:
        result = _make_result(home_win_probability=0.60)
        odds = MarketOdds(game_id=result.game_id, home_ml=+120, away_ml=-140,
                          total_line=8.5, over_ml=-110, under_ml=-110)
        edges = analyze_moneyline(result, odds, kelly_fraction=0.25)
        markets = {e.market for e in edges}
        assert markets == {"home_ml", "away_ml"}

    def test_finds_home_value(self) -> None:
        # Model says home wins 60% but market prices home as +150 (implied 40%).
        result = _make_result(home_win_probability=0.60)
        odds = MarketOdds(game_id=result.game_id, home_ml=+150, away_ml=-170,
                          total_line=8.5, over_ml=-110, under_ml=-110)
        edges = {e.market: e for e in analyze_moneyline(result, odds, kelly_fraction=0.25)}
        assert edges["home_ml"].edge > 0
        assert edges["home_ml"].recommended_stake_pct > 0


class TestAnalyzeTotals:
    def test_over_under_probabilities_complementary(self) -> None:
        totals = np.array([7, 8, 9, 10, 11, 12], dtype=np.int32)
        raw = GameSimulationRaw(
            home_runs=np.zeros(6, dtype=np.int32),
            away_runs=np.zeros(6, dtype=np.int32),
            totals=totals,
            extra_inning_flags=np.zeros(6, dtype=bool),
        )
        odds = MarketOdds(game_id="g", home_ml=-110, away_ml=-110,
                          total_line=9.5, over_ml=-110, under_ml=-110)
        edges = {e.market: e for e in analyze_totals(raw, odds, kelly_fraction=0.25)}
        # 3 of 6 sims over 9.5, 3 under → 0.5 each
        assert abs(edges["over"].model_probability - 0.5) < 1e-9
        assert abs(edges["under"].model_probability - 0.5) < 1e-9


