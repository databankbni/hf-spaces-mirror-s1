"""League trends read off real box scores, and forecasts that regress properly.

The load-bearing claim in this module is the shrinkage: a week of baseball is a
small sample, and a forecast that extends the current line is wrong nearly
every time. These pin that behaviour, plus the wording rules that stop a page
of numbers from over-claiming.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from thebeast.baseball import (
    _signal_variance, grade_league, league_series, outlook, recent_trends)


def _game(d, gid, *, total=9, hr=1, k=8, bb=3, hits=8, sp_outs=15,
          sp_pitches=85, rp_outs=9, winner="home", spread=3):
    def bat(i):
        return {"player_id": i, "name": f"B{i}", "team": "BOS",
                "side": "batter", "position": "SS", "lineup_slot": i,
                "projected": True, "played": True,
                "stats": {"home_runs": {"actual": hr, "projected": 1.0},
                          "k": {"actual": k, "projected": 8.0},
                          "bb": {"actual": bb, "projected": 3.0},
                          "hits": {"actual": hits, "projected": 8.0}}}

    def pit(role, outs, pitches):
        return {"name": role, "team": "BOS", "side": "pitcher", "role": role,
                "projected": True, "played": True,
                "stats": {"outs": {"actual": outs, "projected": 16.0},
                          "pitches": {"actual": pitches, "projected": 88.0}}}

    return {
        "game_id": gid, "date": d, "home": "BOS", "away": "NYY",
        "actual": {"total": total, "spread": spread, "winner": winner,
                   "home_runs": 5, "away_runs": total - 5},
        "outcome": {"home_win_probability": 0.54,
                    "home_runs": {"mean": 4.5}, "away_runs": {"mean": 4.0}},
        "batters": [bat(1)],
        "pitchers": [pit("SP", sp_outs, sp_pitches), pit("RP", rp_outs, 40)],
    }


def _record(days, start=date(2026, 7, 1), per_day=15, noise=1.0, seed=7,
            total=9, **kw):
    """`days` days of `per_day` games around a true level of `total`.

    `noise` is game-to-game spread within a night, and it is the whole point of
    the fixture: shrinkage works by comparing that against how much the nightly
    level itself moves, so a record with no noise makes every wobble look real.
    """
    rng = random.Random(seed)
    out = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        for j in range(per_day):
            # Workload jitters too. A fixture where every starter goes exactly
            # five innings has zero variance, and zero variance quietly drops
            # the metric out of the outlook rather than testing it.
            spec = {"sp_outs": round(15 + rng.gauss(0, 3)),
                    "sp_pitches": round(85 + rng.gauss(0, 10)),
                    "rp_outs": round(9 + rng.gauss(0, 2))}
            spec.update(kw)
            out.append(_game(d, f"{d}-{j}",
                             total=total + rng.gauss(0.0, noise), **spec))
    return out


class TestReadingTheRecord:
    def test_every_appearance_counts_toward_the_league_total(self):
        """Players who were not projected still played, and league scoring is
        what happened on the field, not what was on the lineup card."""
        g = _game("2026-07-01", "a", hr=1)
        g["batters"].append({
            "player_id": 99, "name": "sub", "team": "BOS", "side": "batter",
            "position": "PH", "lineup_slot": None, "projected": False,
            "played": True,
            "stats": {"home_runs": {"actual": 2, "projected": None},
                      "k": {"actual": 0, "projected": None},
                      "bb": {"actual": 0, "projected": None},
                      "hits": {"actual": 1, "projected": None}}})
        ser = league_series([g])
        assert ser["home_runs_per_game"][0]["actual"] == 3

    def test_starter_workload_is_per_start_not_per_game(self):
        ser = league_series([_game("2026-07-01", "a", sp_outs=15)])
        assert ser["starter_innings"][0]["actual"] == 5.0

    def test_close_and_lopsided_games_are_counted(self):
        ser = league_series([_game("2026-07-01", "a", spread=1),
                             _game("2026-07-02", "b", spread=7)])
        assert [r["actual"] for r in ser["one_run_rate"]] == [1.0, 0.0]
        assert [r["actual"] for r in ser["blowout_rate"]] == [0.0, 1.0]


class TestThisWeek:
    def test_a_real_jump_is_reported_against_the_earlier_games(self):
        games = (_record(7, start=date(2026, 7, 18), total=8)
                 + _record(7, start=date(2026, 7, 26), total=13))
        trends = recent_trends(games, asof=date(2026, 8, 1))
        runs = next(t for t in trends if t["metric"] == "runs_per_game")
        assert runs["basis"] == "prior_games"
        assert runs["direction"] == "up" and runs["firm"]
        assert "Scoring up" in runs["headline"]

    def test_a_flat_week_is_not_dressed_up_as_a_trend(self):
        # Seeds are pinned throughout this class: the tiers are decided by
        # a z-score, so which side of a boundary a random draw lands on is the
        # thing being tested and must not move between runs.
        trends = recent_trends(_record(14, start=date(2026, 7, 19), seed=3),
                               asof=date(2026, 8, 1))
        runs = next(t for t in trends if t["metric"] == "runs_per_game")
        assert not runs["moving"] and "steady" in runs["headline"]

    def test_a_weak_signal_is_hedged_rather_than_claimed(self):
        """Somewhere between "nothing happened" and "this is a trend" there is
        a week that leans one way. Calling it either extreme is wrong."""
        games = (_record(7, start=date(2026, 7, 18), total=9, noise=3.0)
                 + _record(7, start=date(2026, 7, 26), total=9.4, noise=3.0,
                           seed=5))
        runs = next(t for t in recent_trends(games, asof=date(2026, 8, 1))
                    if t["metric"] == "runs_per_game")
        assert runs["moving"] and not runs["firm"]
        assert "maybe" in runs["headline"]

    def test_season_form_is_the_fallback_and_says_so(self):
        trends = recent_trends(_record(7, start=date(2026, 7, 26), total=13),
                               asof=date(2026, 8, 1))
        runs = next(t for t in trends if t["metric"] == "runs_per_game")
        assert runs["basis"] == "season_form"
        assert "season form" in runs["detail"]
        assert "Weaker reading" in runs["detail"]

    def test_a_thin_week_is_left_out(self):
        assert recent_trends(_record(1, per_day=3), asof=date(2026, 7, 1)) == []


class TestNextWeek:
    def test_a_noisy_swing_is_given_back(self):
        """A week that ran hot on nothing but game-to-game scatter should not
        move the forecast. This is the case the feature exists to get right —
        extending the line here would be wrong nearly every time."""
        games = (_record(14, start=date(2026, 7, 12), total=8, noise=4.0)
                 + _record(7, start=date(2026, 7, 26), total=10, noise=4.0,
                           seed=3))
        o = next(t for t in outlook(games, asof=date(2026, 8, 1))
                 if t["metric"] == "runs_per_game")
        assert o["carry_pct"] < 40
        assert o["predicted"] < 9.5
        assert o["lo"] < o["predicted"] < o["hi"]

    def test_a_genuine_shift_keeps_most_of_itself(self):
        """The mirror of the case above: when the nightly level really moved
        and the games agree with each other, giving it all back would be just
        as wrong as keeping all of the noise."""
        games = (_record(14, start=date(2026, 7, 12), total=8, noise=0.4)
                 + _record(7, start=date(2026, 7, 26), total=12, noise=0.4,
                           seed=3))
        o = next(t for t in outlook(games, asof=date(2026, 8, 1))
                 if t["metric"] == "runs_per_game")
        assert o["carry_pct"] > 60
        assert o["predicted"] > 11.0

    def test_the_forecast_never_overshoots_the_current_level(self):
        games = (_record(14, start=date(2026, 7, 12), total=8, noise=2.0)
                 + _record(7, start=date(2026, 7, 26), total=12, noise=2.0,
                           seed=3))
        o = next(t for t in outlook(games, asof=date(2026, 8, 1))
                 if t["metric"] == "runs_per_game")
        assert o["null"] <= o["predicted"] <= 12.5

    def test_a_short_record_does_not_get_to_claim_a_carry(self):
        """Day-to-day variance measured from a handful of days is barely
        measured at all; charging it its own error stops noise reading as a
        trend before the record is long enough to tell."""
        rows = [{"date": (date(2026, 7, 1) + timedelta(days=i)).isoformat(),
                 "actual": 8.0 + (2.0 if i % 2 else -2.0), "expected": 8.0}
                for i in range(4) for _ in range(15)]
        assert _signal_variance(rows[:45]) <= _signal_variance(rows) + 1e-9

    def test_the_window_is_the_week_that_starts_tomorrow(self):
        """Adjacent to the window just described, not a week further out. The
        persistence slope is fitted on consecutive weeks, so it only answers
        the one-step question."""
        for t in outlook(_record(14, start=date(2026, 7, 19)),
                         asof=date(2026, 8, 1)):
            assert t["window_start"] == "2026-08-02"
            assert t["window_end"] == "2026-08-08"
            assert t["horizon"] == "week_ahead"
            assert t["kind"] == "league" and t["graded"] is False

    def test_headlines_lead_with_the_move(self):
        games = (_record(14, start=date(2026, 7, 12), total=9, noise=5.0)
                 + _record(7, start=date(2026, 7, 26), total=11, noise=5.0,
                           seed=3))
        o = next(t for t in outlook(games, asof=date(2026, 8, 1))
                 if t["metric"] == "runs_per_game")
        assert "ease back to" in o["headline"]
        assert "lately" in o["headline"]
        assert o["detail"]

    def test_a_thin_record_forecasts_nothing(self):
        assert outlook(_record(1, per_day=15), asof=date(2026, 7, 1)) == []


class TestGrading:
    def _trend(self, lo, hi, metric="runs_per_game"):
        return {"metric": metric, "lo": lo, "hi": hi,
                "predicted": (lo + hi) / 2, "null": 8.0,
                "window_start": "2026-08-08", "window_end": "2026-08-14"}

    def test_a_level_inside_the_band_is_a_hit(self):
        played = _record(7, start=date(2026, 8, 8), total=9)
        out = grade_league(self._trend(8.5, 9.5), played)
        assert out["hit"] is True and out["n_window"] == 105

    def test_only_games_inside_the_window_count(self):
        played = (_record(7, start=date(2026, 8, 8), total=9)
                  + _record(7, start=date(2026, 8, 20), total=20))
        out = grade_league(self._trend(8.5, 9.5), played)
        assert out["n_window"] == 105 and out["hit"] is True

    def test_a_missed_band_can_still_have_called_the_direction(self):
        played = _record(7, start=date(2026, 8, 8), total=12)
        out = grade_league(self._trend(9.0, 10.0), played)
        assert out["hit"] is False and out["direction_right"] is True

    def test_an_unplayed_window_is_left_open(self):
        assert grade_league(self._trend(8.5, 9.5), []) is None


def _league(seasons, *, weeks=20, level=lambda s, w: 9.0, per_day=15,
            wobble=0.25, seed=13):
    """League scoring history: `weeks` weeks a season at `level(season, week)`.

    `wobble` is week-to-week jitter. It defaults on because a perfectly flat
    league has no variance for a lag-1 fit to work with, and a fixture that
    quietly disables the estimator is a fixture that tests nothing.
    """
    from thebeast.league_history import LeagueHistory
    rng = random.Random(seed)
    days = []
    for season in seasons:
        anchor = date(season, 3, 20)
        for w in range(weeks):
            runs = level(season, w) + rng.gauss(0.0, wobble)
            for d in range(7):
                day = anchor + timedelta(days=w * 7 + d)
                days.append({"date": day.isoformat(), "games": per_day,
                             "runs": round(runs * per_day),
                             "home_wins": per_day // 2, "one_run": 2,
                             "blowouts": 3})
    return LeagueHistory(days, [])


class TestUsingSeasonsOfHistory:
    def test_this_week_is_measured_against_the_season_not_our_sample(self):
        """Our record is a few dozen games we happened to grade. The league
        played thousands, and that is what "normal" should mean."""
        def level(season, w):
            return 12.0 if w >= 18 else 8.5
        hist = _league([2026], weeks=20, level=level)
        asof = date(2026, 3, 20) + timedelta(days=19 * 7 + 6)
        t = next(x for x in recent_trends(_record(7, start=asof - timedelta(days=6)),
                                          asof=asof, history=hist, season=2026)
                 if x["metric"] == "runs_per_game")
        assert t["basis"] == "season_to_date"
        assert t["level"] > 11.0                 # the league's week, not ours
        assert t["comparison"] < 9.5             # against the season, not it
        assert t["games"] > 100                  # the league, not our 28
        assert "league-wide" in t["detail"]

    def test_a_calendar_pattern_moves_next_week_before_it_happens(self):
        """A stretch that runs hot in every prior season should be called ahead
        of time rather than noticed afterwards."""
        def level(season, w):
            return 11.5 if 20 <= w <= 22 else 9.0
        hist = _league([2023, 2024, 2025, 2026], weeks=24, level=level)
        # Stand at the end of week 20, so week 21 is the window being forecast.
        asof = date(2026, 3, 20) + timedelta(days=20 * 7 + 6)
        o = next(x for x in outlook(_record(7, start=asof - timedelta(days=6)),
                                    asof=asof, history=hist, season=2026)
                 if x["metric"] == "runs_per_game")
        assert o["source"] == "league_history"
        assert o["calendar_pct"] > 10
        assert o["predicted"] > 10.0
        assert "prior years" in o["detail"]

    def test_a_calendar_pattern_the_seasons_disagree_on_is_ignored(self):
        def level(season, w):
            if not 20 <= w <= 22:
                return 9.0
            return 12.0 if season % 2 else 6.0
        hist = _league([2022, 2023, 2024, 2025, 2026], weeks=24, level=level)
        asof = date(2026, 3, 20) + timedelta(days=20 * 7 + 6)
        o = next(x for x in outlook(_record(7, start=asof - timedelta(days=6)),
                                    asof=asof, history=hist, season=2026)
                 if x["metric"] == "runs_per_game")
        assert o["calendar_pct"] == 0

    def test_carry_is_measured_from_real_weeks(self):
        """A league that wanders slowly should keep a swing; one that bounces
        around a fixed level should give it back. Same code, opposite answers,
        decided by the data rather than by a constant."""
        drifting = _league([2025, 2026], weeks=20,
                           level=lambda s, w: 9.0 + 0.15 * w)
        bouncing = _league([2025, 2026], weeks=20,
                           level=lambda s, w: 9.0 + (1.2 if w % 2 else -1.2))
        asof = date(2026, 3, 20) + timedelta(days=19 * 7 + 6)
        games = _record(7, start=asof - timedelta(days=6))
        a = next(x for x in outlook(games, asof=asof, history=drifting,
                                    season=2026) if x["metric"] == "runs_per_game")
        b = next(x for x in outlook(games, asof=asof, history=bouncing,
                                    season=2026) if x["metric"] == "runs_per_game")
        assert a["carry_pct"] > b["carry_pct"]

    def test_metrics_the_history_cannot_reach_fall_back_and_say_so(self):
        """No league endpoint splits innings by starter or reliever, so those
        cards run on our own record — and must not wear the same confidence as
        one built on seasons."""
        hist = _league([2025, 2026], weeks=20)
        asof = date(2026, 3, 20) + timedelta(days=19 * 7 + 6)
        rows = outlook(_record(21, start=asof - timedelta(days=20)),
                       asof=asof, history=hist, season=2026)
        by = {r["metric"]: r for r in rows}
        assert by["runs_per_game"]["source"] == "league_history"
        assert by["starter_innings"]["source"] == "graded_record"
        assert by["starter_innings"]["confidence"] == "low"

    def test_league_forecasts_are_graded_against_the_league(self):
        """The claim was about all of baseball, so the subset of games we
        graded must not be what decides it."""
        hist = _league([2026], weeks=30, level=lambda s, w: 9.0)
        anchor = date(2026, 3, 20)
        trend = {"metric": "runs_per_game", "lo": 8.5, "hi": 9.5,
                 "predicted": 9.0, "null": 9.0,
                 "window_start": (anchor + timedelta(days=20 * 7)).isoformat(),
                 "window_end": (anchor + timedelta(days=20 * 7 + 6)).isoformat()}
        out = grade_league(trend, [], history=hist)
        assert out["graded_against"] == "league_history"
        assert out["hit"] is True and out["n_window"] > 100
