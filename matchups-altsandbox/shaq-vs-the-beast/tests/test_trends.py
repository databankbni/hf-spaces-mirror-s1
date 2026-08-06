"""Forecasts that can be wrong, and a record that remembers what was claimed.

The point of writing a forecast down before the window opens is that it can
then be marked honestly. These pin the parts that make that true: the interval
is a prediction interval, grading uses only games inside the window, and the
record survives a rerun without rewriting history.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from thebeast.trends import (
    ISSUE_EVERY_DAYS, forecast, grade, load, refresh, save, scorecard,
    _prediction_interval)


def _game(d, gid, *, pa=(44.0, 40.0), bb=(3.0, 2.0), jitter=0.0):
    return {
        "game_id": gid, "date": d, "home": "BOS", "away": "NYY",
        "actual": {"home_runs": 5, "away_runs": 3, "winner": "home"},
        "outcome": {"total": {"error": 0.5, "covered": True},
                    "spread": {"error": 0.2},
                    "home_win_probability": 0.55},
        "batters": [{
            "player_id": 1, "name": "X", "team": "BOS", "side": "batter",
            "position": "SS", "lineup_slot": 1, "projected": True,
            "played": True,
            "stats": {"pa": {"projected": pa[0] + jitter,
                             "actual": pa[1]},
                      "bb": {"projected": bb[0], "actual": bb[1]}},
        }],
        "pitchers": [],
    }


def _record(days, start=None, per_day=3, **kw):
    """`days` days of `per_day` games, as a real slate is several a night.

    A little game-to-game jitter, because a constant series has no variance
    and so no interval to grade.
    """
    start = start or date(2026, 7, 1)
    out = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        for j in range(per_day):
            k = i * per_day + j
            out.append(_game(d, f"g{d}-{j}",
                             jitter=(1.0 if k % 2 else -1.0), **kw))
    return out


class TestIntervals:
    def test_a_future_window_is_wider_than_the_estimate_itself(self):
        """A prediction interval carries the next sample's own error as well
        as the uncertainty in what it is sampling around. Grading against the
        narrower confidence interval would fail forecasts that were right."""
        vals = [1.0 + (0.5 if i % 2 else -0.5) for i in range(80)]
        _, lo_k, hi_k = _prediction_interval(vals, k=100)
        _, lo_big, hi_big = _prediction_interval(vals, k=10_000_000)
        assert (hi_k - lo_k) > (hi_big - lo_big)

    def test_a_constant_series_has_no_width(self):
        m, lo, hi = _prediction_interval([2.0] * 20, k=100)
        assert lo == hi == m


class TestForecasting:
    def test_an_established_bias_is_forecast_for_this_week(self):
        ts = forecast(_record(20), asof=date(2026, 8, 1))
        this = [t for t in ts if t["horizon"] == "this_week"]
        assert any(t["metric"] == "bat_pa" for t in this)
        pa = next(t for t in this if t["metric"] == "bat_pa")
        assert pa["window_start"] == "2026-08-01"
        assert pa["window_end"] == "2026-08-07"
        assert pa["lo"] < pa["predicted"] < pa["hi"]
        assert pa["graded"] is False

    def test_next_week_starts_after_this_week_ends(self):
        ts = forecast(_record(20), asof=date(2026, 8, 1))
        for t in ts:
            if t["horizon"] == "next_week":
                assert t["window_start"] == "2026-08-08"
                assert t["window_end"] == "2026-08-14"

    def test_one_claim_per_metric_per_horizon(self):
        """A metric can be both unsettled and diverging in its inputs. That is
        one forecast with two reasons, not two forecasts."""
        ts = forecast(_record(20), asof=date(2026, 8, 1))
        ids = [t["id"] for t in ts]
        assert len(ids) == len(set(ids))

    def test_a_thin_record_promises_nothing(self):
        assert forecast(_record(2), asof=date(2026, 8, 1)) == []

    def test_headlines_read_as_english(self):
        ts = forecast(_record(20), asof=date(2026, 8, 1))
        pa = next(t for t in ts if t["metric"] == "bat_pa")
        assert "over-projected" in pa["headline"]
        assert pa["basis"]


class TestGrading:
    def _issued(self, lo, hi, metric="bat_pa"):
        return [{
            "id": "x", "issued": "2026-08-01", "horizon": "this_week",
            "window_start": "2026-08-02", "window_end": "2026-08-08",
            "metric": metric, "headline": "h", "predicted": (lo + hi) / 2,
            "lo": lo, "hi": hi, "null": 0.0, "confidence": "high",
            "basis": "b", "graded": False,
        }]

    def test_a_forecast_inside_its_band_is_a_hit(self):
        played = _record(7, start=date(2026, 8, 2))          # 4.0 PA over per game
        out = grade(self._issued(3.0, 5.0), played)
        assert out[0]["graded"] and out[0]["hit"] is True
        assert out[0]["n_window"] == 21

    def test_a_forecast_outside_its_band_is_a_miss(self):
        out = grade(self._issued(0.0, 1.0), _record(7, start=date(2026, 8, 2)))
        assert out[0]["graded"] and out[0]["hit"] is False
        # It still called the direction, which is worth recording separately.
        assert out[0]["direction_right"] is True

    def test_only_games_inside_the_window_are_used(self):
        """Grading on the record that produced the forecast would be marking
        its own homework."""
        inside = _record(7, start=date(2026, 8, 2))
        outside = _record(7, start=date(2026, 9, 1), pa=(80.0, 40.0))   # wildly off
        out = grade(self._issued(3.0, 5.0), inside + outside)
        assert out[0]["n_window"] == 21
        assert out[0]["hit"] is True

    def test_an_unplayed_window_stays_open(self):
        out = grade(self._issued(3.0, 5.0), [])
        assert out[0]["graded"] is False
        assert "hit" not in out[0]

    def test_an_already_graded_forecast_is_not_regraded(self):
        done = self._issued(3.0, 5.0)[0]
        done.update({"graded": True, "hit": False, "actual": 99.0})
        out = grade([done], _record(7, start=date(2026, 8, 2)))
        assert out[0]["hit"] is False and out[0]["actual"] == 99.0


class TestScorecard:
    def test_it_splits_by_horizon_and_confidence(self):
        rows = [
            {"graded": True, "hit": True, "direction_right": True,
             "horizon": "this_week", "confidence": "high"},
            {"graded": True, "hit": False, "direction_right": True,
             "horizon": "next_week", "confidence": "low"},
            {"graded": False, "horizon": "this_week", "confidence": "high"},
        ]
        sc = scorecard(rows)
        assert sc["issued"] == 3 and sc["graded"] == 2 and sc["open"] == 1
        assert sc["overall"]["hit_rate"] == 0.5
        assert sc["by_horizon"]["this_week"]["hit_rate"] == 1.0
        assert sc["by_confidence"]["low"]["hit_rate"] == 0.0

    def test_the_target_is_the_bands_own_coverage(self):
        """An 80% band should be missed one time in five. A hit rate far above
        that means the forecasts are too timid to be useful."""
        assert scorecard([])["target_hit_rate"] == 0.80


class TestRecord:
    def test_a_round_trip_preserves_the_forecasts(self, tmp_path):
        p = tmp_path / "trends.jsonl"
        ts = forecast(_record(20), asof=date(2026, 8, 1))
        assert save(ts, p) == len(ts)
        assert [t["id"] for t in load(p)] == sorted(t["id"] for t in ts)

    def test_rerunning_the_same_day_does_not_reissue(self, tmp_path):
        """The record is a log of what was claimed and when. Re-running the
        job must not let a forecast be quietly restated."""
        p = tmp_path / "trends.jsonl"
        games = _record(20)
        first = refresh(games, asof=date(2026, 8, 1), path=p)
        second = refresh(games, asof=date(2026, 8, 1), path=p)
        assert first["issued_now"] > 0
        assert second["issued_now"] == 0
        assert second["total"] == first["total"]

    def test_the_next_day_does_not_issue_a_fresh_set(self, tmp_path):
        """Grading runs nightly; issuing does not. Every forecast covers the
        following seven days, so nightly issues would overlap six days in
        seven — a hundred restatements of one call, counted by the scorecard as
        a hundred independent ones."""
        p = tmp_path / "trends.jsonl"
        games = _record(20)
        refresh(games, asof=date(2026, 8, 1), path=p)
        next_day = refresh(games, asof=date(2026, 8, 2), path=p)
        assert next_day["issued_now"] == 0

    def test_a_fresh_set_is_issued_once_the_interval_has_passed(self, tmp_path):
        p = tmp_path / "trends.jsonl"
        games = _record(20)
        first = refresh(games, asof=date(2026, 8, 1), path=p)
        later = refresh(
            games, asof=date(2026, 8, 1) + timedelta(days=ISSUE_EVERY_DAYS), path=p)
        assert first["issued_now"] > 0
        assert later["issued_now"] > 0

    def test_grading_still_happens_on_a_night_that_issues_nothing(self, tmp_path):
        """The whole reason the job runs nightly. A window that has played out
        should be marked the moment it has, not held until the next issue."""
        p = tmp_path / "trends.jsonl"
        refresh(_record(20), asof=date(2026, 8, 1), path=p)
        before = sum(1 for t in load(p) if t.get("graded"))
        out = refresh(_record(40), asof=date(2026, 8, 2), path=p)
        after = sum(1 for t in load(p) if t.get("graded"))
        assert out["issued_now"] == 0
        assert after >= before, "grading is not gated by the issue interval"

    def test_a_corrupt_line_costs_one_forecast_not_the_file(self, tmp_path):
        p = tmp_path / "trends.jsonl"
        p.write_text('{"id":"a","graded":false}\nnot json\n{"id":"b"}\n')
        assert [t["id"] for t in load(p)] == ["a", "b"]

    def test_a_missing_record_is_empty_not_an_error(self, tmp_path):
        assert load(tmp_path / "absent.jsonl") == []
