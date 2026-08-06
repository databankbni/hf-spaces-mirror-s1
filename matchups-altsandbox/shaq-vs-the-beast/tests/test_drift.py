"""Telling a real drift from a fortnight of baseball.

The monitor's whole job is to not cry wolf. Two graded windows disagreed
wildly on winner accuracy (40.5% then 53.5%) and the totals bias flipped
sign — neither was a model change. These pin the arithmetic and the
judgement that separate those from the errors that are actually there.
"""
from __future__ import annotations

import pytest

from thebeast.drift import assess, build_drift_report, leading_indicators, series


def _game(date, gid, *, batters=None, pitchers=None, outcome=None, winner="home"):
    return {
        "game_id": gid, "date": date, "home": "BOS", "away": "NYY",
        "actual": {"home_runs": 5, "away_runs": 3, "winner": winner},
        "outcome": outcome or {},
        "batters": batters or [], "pitchers": pitchers or [],
    }


def _bat(pa_p, pa_a, **stats):
    s = {"pa": {"projected": pa_p, "actual": pa_a}}
    for k, (p, a) in stats.items():
        s[k] = {"projected": p, "actual": a}
    return {"player_id": 1, "name": "X", "team": "BOS", "side": "batter",
            "position": "SS", "lineup_slot": 1, "projected": True,
            "played": True, "stats": s}


class TestAggregation:
    def test_a_low_count_game_cannot_dominate_the_ratio(self):
        """The first draft averaged per-game ratios. A game projecting two
        walks where one happened contributes a ratio of 2.0, and averaging
        those made walks look 62% high when they are 13% high. The ratio of
        means is the correct aggregate and this pins it."""
        games = []
        # Nine ordinary games, dead-on. One low-count game, off by one walk.
        for i in range(9):
            games.append(_game("2026-07-0%d" % (i + 1), f"g{i}",
                               batters=[_bat(40, 40, bb=(4.0, 4.0))]))
        games.append(_game("2026-07-10", "g9",
                           batters=[_bat(40, 40, bb=(2.0, 1.0))]))
        rep = build_drift_report(games)
        bb = next(m for m in rep["metrics"] if m["metric"] == "bat_bb_rate")
        # 38 projected against 37 actual across the record → ~2.7%, not 100%.
        assert bb["ratio"] == pytest.approx(1.027, abs=0.01)

    def test_volume_error_does_not_masquerade_as_a_rate_error(self):
        """Hits and strikeouts both read 'too high' only because too many
        plate appearances were projected. Rescaling to the real volume is what
        stops the report raising seven alarms for two problems."""
        games = [
            _game(f"2026-07-{d:02d}", f"g{d}",
                  # 10% too many PA, but the per-PA hit rate is exactly right.
                  # a little game-to-game noise, as real data has
                  batters=[_bat(44.0 + (d % 3), 40.0 + (d % 3),
                                hits=(11.0 + 0.1 * (d % 4),
                                      10.0 + 0.1 * (d % 4)))])
            for d in range(1, 21)
        ]
        rep = build_drift_report(games)
        pa = next(m for m in rep["metrics"] if m["metric"] == "bat_pa")
        hits = next(m for m in rep["metrics"] if m["metric"] == "bat_hits_rate")
        assert pa["verdict"] == "act"
        assert pa["ratio"] == pytest.approx(1.10, abs=0.01)
        assert hits["ratio"] == pytest.approx(1.00, abs=0.01)
        assert hits["verdict"] == "immaterial"
        assert "bat_hits_rate" not in rep["actionable"]


class TestVerdicts:
    def test_a_consistent_significant_bias_is_actionable(self):
        vals = [1.0] * 40                       # no variance is degenerate;
        vals = [1.0 + (0.1 if i % 2 else -0.1) for i in range(40)]
        out = assess(vals, tolerance=0.05, label="m")
        assert out["consistent"] and abs(out["z"]) > 2
        assert out["verdict"] == "act"

    def test_a_bias_that_flips_between_halves_is_not_actionable(self):
        """Exactly the totals bias: -0.01 in one window, +0.89 in the next."""
        vals = [-1.0] * 20 + [1.0] * 20
        out = assess(vals, tolerance=0.05, label="m")
        assert not out["consistent"]
        assert out["verdict"] != "act"

    def test_an_effect_inside_tolerance_is_immaterial_however_significant(self):
        """Significance is not importance: a 0.3% miss measured over enough
        games clears any z-test and still is not worth changing a model for."""
        vals = [0.01] * 200
        out = assess(vals, tolerance=0.05, label="m")
        assert out["verdict"] == "immaterial"

    def test_pure_noise_reads_as_noise(self):
        vals = [(-1) ** i for i in range(60)]   # mean 0
        out = assess(vals, tolerance=0.01, label="m")
        assert out["verdict"] in ("noise", "immaterial")

    def test_it_says_how_many_games_would_settle_an_open_question(self):
        """'Not significant' is a dead end; a sample size is a date."""
        vals = [0.5 + (6.0 if i % 2 else -6.0) for i in range(20)]
        out = assess(vals, tolerance=0.01, label="m")
        assert out["verdict"] != "act"
        assert out["games_for_significance"] > 20
        assert out["more_games_needed"] > 0

    def test_a_short_series_is_not_judged(self):
        assert assess([1.0, 2.0], label="m")["verdict"] == "no data"


class TestSeries:
    def test_outcome_errors_use_actual_minus_projected(self):
        g = _game("2026-07-01", "g", outcome={
            "total": {"error": 1.5, "covered": True},
            "spread": {"error": -0.5},
            "home_win_probability": 0.6})
        ser, _ = series([g])
        assert ser["total_runs"] == [1.5]
        assert ser["margin"] == [-0.5]
        assert ser["total_coverage"] == [1.0]
        # home won, called at .60 → under-called by .40
        assert ser["home_win_prob"] == [pytest.approx(0.4)]

    def test_games_are_ordered_oldest_first_so_a_trend_has_a_direction(self):
        gs = [_game("2026-07-03", "c", outcome={"spread": {"error": 3.0}}),
              _game("2026-07-01", "a", outcome={"spread": {"error": 1.0}}),
              _game("2026-07-02", "b", outcome={"spread": {"error": 2.0}})]
        ser, _ = series(gs)
        assert ser["margin"] == [1.0, 2.0, 3.0]

    def test_coverage_is_scored_against_eighty_percent_not_zero(self):
        gs = [_game(f"2026-07-{d:02d}", f"g{d}",
                    outcome={"total": {"error": 0.0, "covered": d <= 7}})
              for d in range(1, 11)]
        rep = build_drift_report(gs)
        cov = next(m for m in rep["metrics"] if m["metric"] == "total_coverage")
        assert cov["null"] == 0.80
        assert cov["mean"] == pytest.approx(0.70)


class TestLeadingIndicators:
    class _Repo:
        def __init__(self, bb_rate):
            self._bb = bb_rate

        def get_batters_for_season(self, season):
            class B:
                pa = 10_000
                bb_rate = self._bb
                hr_rate = 0.030
                k_rate = 0.220
            B.bb_rate = self._bb
            return [B()]

    def _games_at(self, bb_per_pa, n=30):
        return [_game(f"2026-07-{d:02d}", f"g{d}",
                      batters=[_bat(40, 40, bb=(3.0, 40 * bb_per_pa),
                                    hits=(9.0, 9.0), k=(9.0, 9.0),
                                    home_runs=(1.0, 1.0))])
                for d in range(1, n + 1)]

    def test_it_flags_a_statline_rate_above_what_is_being_played(self):
        """The predictive half: if the statlines say the league walks more
        than it does, every future projection is already wrong by that margin,
        before a single new game is graded."""
        out = leading_indicators(self._Repo(0.090), self._games_at(0.080), 2026)
        assert out["available"]
        bb = next(r for r in out["rates"] if r["stat"] == "bb")
        assert bb["ratio"] == pytest.approx(0.090 / 0.080, abs=0.02)
        assert bb["z"] > 0

    def test_it_declines_to_guess_on_a_thin_sample(self):
        out = leading_indicators(self._Repo(0.090), self._games_at(0.080, n=2), 2026)
        assert out["available"] is False
        assert "graded PA" in out["reason"]

    def test_no_statlines_is_reported_not_raised(self):
        class Empty:
            def get_batters_for_season(self, season):
                return []
        assert leading_indicators(Empty(), [], 2026)["available"] is False
