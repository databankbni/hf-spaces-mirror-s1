"""Tests for park-factor computation, the weather HR heuristic, and their
application in the matchup distribution (no network)."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from thebeast.data.park_factors import (
    compute_park_factors,
    weather_hr_multiplier,
    wind_description_to_deg,
)
from thebeast.matchup.dna import synthetic_batter, synthetic_pitcher
from thebeast.matchup.context import GameContext
from thebeast.matchup.log5 import pa_distribution, league_averages_default


@dataclass
class _Game:
    home_team: str
    away_team: str
    home_score: int
    away_score: int


def _season(hitter_park_total: int, pitcher_park_total: int, neutral_total: int) -> list[_Game]:
    """COL = hitters' park, SD = pitchers' park, others neutral. Each team plays
    both home and road so home/road ratios are well defined."""
    games: list[_Game] = []
    teams = ["COL", "SD", "LAD", "SF"]
    # Home games: total runs depend on the host park.
    park_total = {"COL": hitter_park_total, "SD": pitcher_park_total,
                  "LAD": neutral_total, "SF": neutral_total}
    for host in teams:
        for visitor in teams:
            if host == visitor:
                continue
            t = park_total[host]
            games.append(_Game(host, visitor, t // 2, t - t // 2))
    return games


class TestComputeParkFactors:
    def test_hitter_park_above_one(self) -> None:
        games = _season(hitter_park_total=14, pitcher_park_total=6, neutral_total=9)
        pf = {p.venue_id: p for p in compute_park_factors(games, 2023)}
        assert pf["COL"].runs_factor > 1.0
        assert pf["SD"].runs_factor < 1.0

    def test_clamped(self) -> None:
        games = _season(hitter_park_total=40, pitcher_park_total=1, neutral_total=9)
        pf = {p.venue_id: p for p in compute_park_factors(games, 2023)}
        assert pf["COL"].runs_factor <= 1.20
        assert pf["SD"].runs_factor >= 0.85

    def test_regression_toward_one(self) -> None:
        games = _season(hitter_park_total=12, pitcher_park_total=6, neutral_total=9)
        pf = {p.venue_id: p for p in compute_park_factors(games, 2023, regression=0.5)}
        # Half-regressed, so the factor sits between 1.0 and the raw ratio.
        assert 1.0 < pf["COL"].runs_factor < 1.5


class TestWeather:
    def test_warm_tailwind_boosts(self) -> None:
        m = weather_hr_multiplier(90.0, 15.0, 0.0)  # hot, straight out
        assert m > 1.0

    def test_cold_headwind_suppresses(self) -> None:
        m = weather_hr_multiplier(45.0, 15.0, 180.0)  # cold, straight in
        assert m < 1.0

    def test_crosswind_neutral_on_wind(self) -> None:
        # 90° crosswind contributes ~0; only the temp term moves it.
        at_baseline = weather_hr_multiplier(70.0, 20.0, 90.0)
        assert at_baseline == pytest.approx(1.0, abs=1e-6)

    def test_wind_description_mapping(self) -> None:
        assert wind_description_to_deg("Out To CF") == 0.0
        assert wind_description_to_deg("In From CF") == 180.0
        assert wind_description_to_deg("L To R") == 90.0
        assert wind_description_to_deg(None) == 90.0


class TestContextInDistribution:
    def test_runs_factor_increases_offense(self) -> None:
        league = league_averages_default(2023)
        b, p = synthetic_batter("R"), synthetic_pitcher("starter")
        neutral = pa_distribution(b, p, league, context=None)
        coors = pa_distribution(b, p, league,
                                context=GameContext("g", "COL", runs_factor=1.15))
        out_neutral = neutral.strikeout + neutral.in_play_out
        out_coors = coors.strikeout + coors.in_play_out
        # More offense → less probability mass on outs.
        assert out_coors < out_neutral

    def test_hr_factor_increases_hr_share(self) -> None:
        league = league_averages_default(2023)
        b, p = synthetic_batter("R"), synthetic_pitcher("starter")
        base = pa_distribution(b, p, league, context=None)
        windy = pa_distribution(b, p, league,
                                context=GameContext("g", "v", hr_factor=1.2))
        assert windy.home_run > base.home_run
