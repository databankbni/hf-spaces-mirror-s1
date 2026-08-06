"""Tests for thebeast.matchup — DNA fingerprints + Log5 matchup model.

Test-first (Constitution Article III). No network, no database: synthetic
fingerprints and small in-memory DataFrames only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from thebeast.matchup.dna import (
    BatterDNA,
    PitcherDNA,
    LeagueAverages,
    build_batter_dna,
    build_pitcher_dna,
    shrink_batter_dna,
    shrink_pitcher_dna,
    synthetic_batter,
    synthetic_pitcher,
)
from thebeast.matchup.context import GameContext
from thebeast.matchup.log5 import pa_distribution, league_averages_default


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _league() -> LeagueAverages:
    return league_averages_default(season=2024)


def _make_pa_df(n: int, hr_share: float = 0.04, k_share: float = 0.22) -> pd.DataFrame:
    """Synthetic PA-level frame with an `event` bucket and pitcher/batter hand."""
    rng = np.random.default_rng(0)
    events = []
    rates = {
        "single": 0.15,
        "double": 0.047,
        "triple": 0.005,
        "hr": hr_share,
        "bb": 0.085,
        "hbp": 0.01,
        "k": k_share,
    }
    rates["ipo"] = 1.0 - sum(rates.values())
    buckets = list(rates.keys())
    probs = list(rates.values())
    for _ in range(n):
        events.append(rng.choice(buckets, p=probs))
    hands = rng.choice(["L", "R"], size=n, p=[0.3, 0.7])
    return pd.DataFrame({"event": events, "opp_hand": hands})


# ─── LeagueAverages ───────────────────────────────────────────────────────────

class TestLeagueAverages:
    def test_rates_sum_to_one(self) -> None:
        lg = _league()
        total = (lg.single_rate + lg.double_rate + lg.triple_rate + lg.hr_rate
                 + lg.bb_rate + lg.hbp_rate + lg.k_rate + lg.ipo_rate)
        assert abs(total - 1.0) < 1e-6


# ─── Synthetic DNA ────────────────────────────────────────────────────────────

class TestSyntheticDNA:
    def test_synthetic_batter_valid(self) -> None:
        b = synthetic_batter("R")
        total = (b.single_rate + b.double_rate + b.triple_rate + b.hr_rate
                 + b.bb_rate + b.hbp_rate + b.k_rate + b.ipo_rate)
        assert abs(total - 1.0) < 1e-6
        assert b.platoon_mult["vL"] > 0 and b.platoon_mult["vR"] > 0

    def test_synthetic_pitcher_valid(self) -> None:
        p = synthetic_pitcher("starter")
        total = (p.single_allowed + p.double_allowed + p.triple_allowed
                 + p.hr_allowed + p.bb_allowed + p.hbp_allowed
                 + p.k_rate + p.ipo_rate)
        assert abs(total - 1.0) < 1e-6
        assert p.role == "starter"

    def test_synthetic_pitcher_reliever_role(self) -> None:
        p = synthetic_pitcher("reliever")
        assert p.role == "reliever"


# ─── Builders ─────────────────────────────────────────────────────────────────

class TestBuilders:
    def test_build_batter_dna_rates_sum_to_one(self) -> None:
        df = _make_pa_df(600)
        b = build_batter_dna(player_id=1, season=2024, statcast=df, league=_league())
        total = (b.single_rate + b.double_rate + b.triple_rate + b.hr_rate
                 + b.bb_rate + b.hbp_rate + b.k_rate + b.ipo_rate)
        assert abs(total - 1.0) < 1e-6
        assert b.pa == 600

    def test_low_pa_shrinks_toward_league(self) -> None:
        """A high-HR batter with very few PA should shrink toward league HR rate."""
        league = _league()
        small = _make_pa_df(20, hr_share=0.30)
        large = _make_pa_df(2000, hr_share=0.30)
        b_small = build_batter_dna(1, 2024, small, league, shrink_pa=200)
        b_large = build_batter_dna(2, 2024, large, league, shrink_pa=200)
        # The small-sample HR rate should sit closer to league average than the
        # large-sample HR rate (both drawn from a 0.30 HR generator).
        assert abs(b_small.hr_rate - league.hr_rate) < abs(b_large.hr_rate - league.hr_rate)

    def test_build_pitcher_dna_rates_sum_to_one(self) -> None:
        df = _make_pa_df(700)
        p = build_pitcher_dna(player_id=5, season=2024, statcast=df, league=_league())
        total = (p.single_allowed + p.double_allowed + p.triple_allowed
                 + p.hr_allowed + p.bb_allowed + p.hbp_allowed
                 + p.k_rate + p.ipo_rate)
        assert abs(total - 1.0) < 1e-6
        assert p.bf == 700


# ─── Log5 matchup ─────────────────────────────────────────────────────────────

class TestLog5:
    def test_distribution_sums_to_one(self) -> None:
        b = synthetic_batter("R")
        p = synthetic_pitcher("starter")
        dist = pa_distribution(b, p, _league())
        total = (dist.single + dist.double + dist.triple + dist.home_run
                 + dist.walk + dist.hit_by_pitch + dist.strikeout + dist.in_play_out)
        assert abs(total - 1.0) < 1e-6

    def test_average_vs_average_returns_league(self) -> None:
        """League-average batter vs league-average pitcher → league rates."""
        league = _league()
        b = synthetic_batter("R")
        p = synthetic_pitcher("starter")
        # Force DNA to exactly league rates so Log5 is an identity at the league point.
        b.single_rate = league.single_rate
        b.double_rate = league.double_rate
        b.triple_rate = league.triple_rate
        b.hr_rate = league.hr_rate
        b.bb_rate = league.bb_rate
        b.hbp_rate = league.hbp_rate
        b.k_rate = league.k_rate
        b.ipo_rate = league.ipo_rate
        b.platoon_mult = {"vL": 1.0, "vR": 1.0}
        p.single_allowed = league.single_rate
        p.double_allowed = league.double_rate
        p.triple_allowed = league.triple_rate
        p.hr_allowed = league.hr_rate
        p.bb_allowed = league.bb_rate
        p.hbp_allowed = league.hbp_rate
        p.k_rate = league.k_rate
        p.ipo_rate = league.ipo_rate
        p.platoon_mult = {"vL": 1.0, "vR": 1.0}
        dist = pa_distribution(b, p, league, context=None)
        assert abs(dist.home_run - league.hr_rate) < 1e-6
        assert abs(dist.strikeout - league.k_rate) < 1e-6

    def test_better_pitcher_lowers_hits(self) -> None:
        """A high-K, low-HR pitcher should reduce hits vs the league-average pitcher."""
        league = _league()
        b = synthetic_batter("R")
        avg_p = synthetic_pitcher("starter")
        ace = synthetic_pitcher("starter")
        ace.k_rate = avg_p.k_rate * 1.5
        ace.hr_allowed = avg_p.hr_allowed * 0.5
        # renormalize ace
        _renorm_pitcher(ace)
        d_avg = pa_distribution(b, avg_p, league)
        d_ace = pa_distribution(b, ace, league)
        assert d_ace.strikeout > d_avg.strikeout
        assert d_ace.home_run < d_avg.home_run

    def test_park_factor_boosts_hr(self) -> None:
        league = _league()
        b = synthetic_batter("R")
        p = synthetic_pitcher("starter")
        neutral = pa_distribution(b, p, league, context=GameContext(game_id="g", venue_id="v", hr_factor=1.0))
        coors = pa_distribution(b, p, league, context=GameContext(game_id="g", venue_id="v", hr_factor=1.4))
        assert coors.home_run > neutral.home_run

    def test_platoon_split_changes_distribution(self) -> None:
        """A batter with a strong reverse-platoon vL multiplier faces an L pitcher."""
        league = _league()
        b = synthetic_batter("R")
        b.platoon_mult = {"vL": 1.3, "vR": 1.0}
        p_lhp = synthetic_pitcher("starter")
        p_lhp.hand = "L"
        p_rhp = synthetic_pitcher("starter")
        p_rhp.hand = "R"
        d_vl = pa_distribution(b, p_lhp, league)
        d_vr = pa_distribution(b, p_rhp, league)
        # vL multiplier boosts the batter's hit rates against the LHP
        assert d_vl.home_run > d_vr.home_run


class TestShrinkage:
    def test_low_sample_moves_toward_league(self) -> None:
        league = _league()
        # An extreme 40% HR hitter with only 30 PA should shrink hard to league.
        dna = synthetic_batter("R")
        dna.hr_rate = 0.40
        dna.pa = 30
        # Renormalize ipo so the eight rates sum to 1.0 before shrinking.
        dna.ipo_rate = 1.0 - (dna.single_rate + dna.double_rate + dna.triple_rate
                              + dna.hr_rate + dna.bb_rate + dna.hbp_rate + dna.k_rate)
        shrunk = shrink_batter_dna(dna, league, k=200)
        assert abs(shrunk.hr_rate - league.hr_rate) < abs(dna.hr_rate - league.hr_rate)

    def test_high_sample_barely_moves(self) -> None:
        league = _league()
        dna = synthetic_batter("R")
        dna.hr_rate = 0.10
        dna.ipo_rate = 1.0 - (dna.single_rate + dna.double_rate + dna.triple_rate
                              + dna.hr_rate + dna.bb_rate + dna.hbp_rate + dna.k_rate)
        dna.pa = 5000
        shrunk = shrink_batter_dna(dna, league, k=200)
        assert abs(shrunk.hr_rate - dna.hr_rate) < 0.01

    def test_shrunk_rates_sum_to_one(self) -> None:
        league = _league()
        b = shrink_batter_dna(synthetic_batter("R"), league, k=200)
        p = shrink_pitcher_dna(synthetic_pitcher("starter"), league, k=300)
        for dna in (b, p):
            assert abs(sum(dna.as_tuple()) - 1.0) < 1e-9

    def test_pitcher_shrinks_toward_league(self) -> None:
        league = _league()
        p = synthetic_pitcher("starter")
        p.hr_allowed = 0.12
        p.ipo_rate = 1.0 - (p.single_allowed + p.double_allowed + p.triple_allowed
                            + p.hr_allowed + p.bb_allowed + p.hbp_allowed + p.k_rate)
        p.bf = 40
        shrunk = shrink_pitcher_dna(p, league, k=300)
        assert abs(shrunk.hr_allowed - league.hr_rate) < abs(p.hr_allowed - league.hr_rate)


def _renorm_pitcher(p: PitcherDNA) -> None:
    total = (p.single_allowed + p.double_allowed + p.triple_allowed
             + p.hr_allowed + p.bb_allowed + p.hbp_allowed + p.k_rate + p.ipo_rate)
    p.single_allowed /= total
    p.double_allowed /= total
    p.triple_allowed /= total
    p.hr_allowed /= total
    p.bb_allowed /= total
    p.hbp_allowed /= total
    p.k_rate /= total
    p.ipo_rate /= total
