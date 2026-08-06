"""Seasons of league baseball: fetching it, storing it, and asking it things.

The two claims worth pinning are that a baseline built from thousands of games
beats one built from the same weeks it is measuring, and that a calendar effect
taken from prior seasons never touches the season being forecast.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from thebeast.data.sources.league import LeagueDay, MLBLeagueSource
from thebeast.league_history import LeagueHistory, load, refresh, save


def _sched(games):
    """A `/schedule` payload in the shape the Stats API returns."""
    by_date = {}
    for d, home, away, hs, as_, final in games:
        by_date.setdefault(d, []).append({
            "gamePk": abs(hash((d, home, away))) % 900000,
            "officialDate": d,
            "status": {"abstractGameState": "Final" if final else "Preview"},
            "teams": {"home": {"score": hs, "team": {"abbreviation": home}},
                      "away": {"score": as_, "team": {"abbreviation": away}}},
        })
    return {"dates": [{"date": d, "games": g} for d, g in sorted(by_date.items())]}


class TestFetchingDays:
    def test_final_scores_become_daily_league_totals(self):
        src = MLBLeagueSource()
        src._fetch_json = lambda url, params=None: _sched([
            ("2026-04-01", "BOS", "NYY", 5, 3, True),
            ("2026-04-01", "LAD", "SF", 2, 1, True),
            ("2026-04-02", "BOS", "NYY", 10, 1, True),
        ])
        days = src.fetch_days(date(2026, 4, 1), date(2026, 4, 2))
        assert [d.date for d in days] == ["2026-04-01", "2026-04-02"]
        assert days[0].games == 2 and days[0].runs == 11
        assert days[0].home_wins == 2
        assert days[0].one_run == 1          # LAD 2-1
        assert days[1].blowouts == 1         # 10-1

    def test_unfinished_games_are_not_counted(self):
        src = MLBLeagueSource()
        src._fetch_json = lambda url, params=None: _sched([
            ("2026-04-01", "BOS", "NYY", 5, 3, True),
            ("2026-04-01", "LAD", "SF", None, None, False),
        ])
        assert src.fetch_days(date(2026, 4, 1), date(2026, 4, 1))[0].games == 1

    def test_a_game_finishing_after_midnight_counts_for_its_own_day(self):
        """`officialDate` is the day the game belongs to; the calendar day it
        ended on would scatter extra-inning games into the next morning."""
        src = MLBLeagueSource()
        payload = _sched([("2026-04-01", "BOS", "NYY", 5, 3, True)])
        payload["dates"][0]["games"][0]["officialDate"] = "2026-03-31"
        src._fetch_json = lambda url, params=None: payload
        assert src.fetch_days(date(2026, 3, 31), date(2026, 4, 1))[0].date == \
            "2026-03-31"

    def test_league_windows_sum_across_every_team(self):
        src = MLBLeagueSource()
        src._fetch_json = lambda url, params=None: {"stats": [{"splits": [
            {"team": {"id": 111}, "stat": {"gamesPlayed": 6, "homeRuns": 8,
                                           "strikeOuts": 50, "baseOnBalls": 20,
                                           "hits": 55}},
            {"team": {"id": 147}, "stat": {"gamesPlayed": 6, "homeRuns": 7,
                                           "strikeOuts": 48, "baseOnBalls": 18,
                                           "hits": 50}},
        ]}]}
        win = src.fetch_window(2026, date(2026, 4, 1), date(2026, 4, 7))
        assert win.games == 12 and win.home_runs == 15 and win.hits == 105


class TestTheRecord:
    def test_a_round_trip_keeps_days_and_windows_apart(self, tmp_path):
        p = tmp_path / "h.jsonl"
        save([{"date": "2026-04-01", "games": 15, "runs": 130, "home_wins": 8,
               "one_run": 4, "blowouts": 3}],
             [{"season": 2026, "start": "2026-04-01", "end": "2026-04-07",
               "games": 210, "home_runs": 120, "strikeouts": 800,
               "walks": 300, "hits": 900}], p)
        h = load(p)
        assert len(h.days) == 1 and len(h.windows) == 1
        assert h.game_count == 15

    def test_a_corrupt_line_costs_one_day_not_the_file(self, tmp_path):
        p = tmp_path / "h.jsonl"
        p.write_text('{"kind":"day","date":"2026-04-01","games":5,"runs":40,'
                     '"home_wins":3,"one_run":1,"blowouts":1}\nnot json\n')
        assert len(load(p).days) == 1

    def test_a_missing_record_is_empty_not_an_error(self, tmp_path):
        assert not load(tmp_path / "absent.jsonl")

    def _source(self, calls, *, per_season=2400):
        class Src:
            def fetch_season_days(self, season, through=None):
                calls.append(season)
                # Spread a plausible season across enough days to look whole.
                return [LeagueDay(date=f"{season}-04-{d:02d}", games=15,
                                  runs=130, home_wins=8, one_run=4, blowouts=3)
                        for d in range(1, per_season // 15 + 1)]

            def fetch_season_windows(self, season, through=None, **kw):
                return []
        return Src()

    def test_a_finished_season_is_fetched_once(self, tmp_path):
        """Last year cannot change, and re-fetching it every run would be a
        few thousand pointless requests a week."""
        p = tmp_path / "h.jsonl"
        calls = []
        refresh([2025, 2026], asof=date(2026, 8, 1), path=p,
                source=self._source(calls))
        calls.clear()
        refresh([2025, 2026], asof=date(2026, 8, 1), path=p,
                source=self._source(calls))
        assert calls == [2026]          # only the season still being played

    def test_a_half_fetched_season_is_picked_up_again(self, tmp_path):
        """A fetch that died partway leaves a stub. Treating one row as proof
        of coverage would freeze that stub in place and the record would look
        complete forever without being it."""
        p = tmp_path / "h.jsonl"
        calls = []
        refresh([2025], asof=date(2026, 8, 1), path=p,
                source=self._source(calls, per_season=300))
        calls.clear()
        refresh([2025], asof=date(2026, 8, 1), path=p,
                source=self._source(calls))
        assert calls == [2025]


def _history(seasons, *, weeks=20, level=lambda s, w: 9.0, games=105):
    """Weekly league scoring for several seasons, via daily records."""
    days = []
    for season in seasons:
        anchor = date(season, 3, 20)
        for w in range(weeks):
            for d in range(7):
                day = anchor + timedelta(days=w * 7 + d)
                per_day = games // 7
                days.append({"date": day.isoformat(), "games": per_day,
                             "runs": round(level(season, w) * per_day),
                             "home_wins": per_day // 2, "one_run": 1,
                             "blowouts": 1})
    return LeagueHistory(days, [])


class TestAsking:
    def test_a_season_level_is_a_ratio_of_sums(self):
        """Averaging per-day averages weights a three-game Monday like a
        fifteen-game Saturday."""
        h = LeagueHistory([
            {"date": "2026-04-01", "games": 2, "runs": 40, "home_wins": 1,
             "one_run": 0, "blowouts": 0},
            {"date": "2026-04-02", "games": 18, "runs": 180, "home_wins": 9,
             "one_run": 0, "blowouts": 0}], [])
        assert h.level("runs_per_game", season=2026) == pytest.approx(11.0)

    def test_weeks_are_anchored_so_they_line_up_year_to_year(self):
        h = _history([2024, 2025])
        a = [w for w in h.weekly("runs_per_game") if w["season"] == 2024]
        b = [w for w in h.weekly("runs_per_game") if w["season"] == 2025]
        assert a[3]["start"][5:] == b[3]["start"][5:]

    def test_a_calendar_effect_is_found_across_seasons(self):
        """A stretch of the calendar that runs hot every year is exactly what
        the week ahead should be told about. It is a stretch and not a single
        week because three seasons of one week is about 300 games, which cannot
        see an effect this size through the noise."""
        def level(season, w):
            return 11.0 if 18 <= w <= 20 else 9.0
        h = _history([2023, 2024, 2025, 2026], level=level)
        anchor = date(2026, 3, 20) + timedelta(days=19 * 7)
        cal = h.calendar_factor("runs_per_game", anchor,
                                anchor + timedelta(days=6),
                                exclude_season=2026)
        assert cal is not None
        assert cal["factor"] > 1.1 and cal["applies"]
        assert 2026 not in cal["seasons"]

    def test_three_coin_flips_are_not_a_calendar_effect(self):
        """Direction agreement alone is a one-in-four accident across three
        seasons. With eleven metrics on the page that manufactures two or three
        effects a week, so the size has to clear ordinary week-to-week wobble
        as well."""
        rng = __import__("random").Random(4)
        def level(season, w):
            # Real week-to-week noise, and one week that happens to land high
            # in all three prior seasons by luck rather than by calendar.
            base = 9.0 + rng.gauss(0, 1.2)
            return base + (0.45 if w == 19 else 0.0)
        h = _history([2023, 2024, 2025, 2026], weeks=24, level=level)
        anchor = date(2026, 3, 20) + timedelta(days=19 * 7)
        cal = h.calendar_factor("runs_per_game", anchor,
                                anchor + timedelta(days=6),
                                exclude_season=2026)
        assert cal is None or not cal["applies"]

    def test_the_season_being_forecast_is_never_its_own_evidence(self):
        h = _history([2025, 2026])
        cal = h.calendar_factor("runs_per_game", date(2026, 7, 1),
                                date(2026, 7, 7), exclude_season=2026)
        assert cal is None or 2026 not in cal["seasons"]

    def test_a_pattern_the_seasons_disagree_on_is_not_consistent(self):
        def level(season, w):
            if w != 19:
                return 9.0
            return 11.0 if season % 2 else 7.0
        h = _history([2022, 2023, 2024, 2025], level=level)
        anchor = date(2025, 3, 20) + timedelta(days=19 * 7)
        cal = h.calendar_factor("runs_per_game", anchor,
                                anchor + timedelta(days=6),
                                exclude_season=2026)
        assert not cal["applies"]

    def test_one_prior_season_is_not_a_calendar_effect(self):
        h = _history([2025])
        assert h.calendar_factor("runs_per_game", date(2025, 7, 1),
                                 date(2025, 7, 7), exclude_season=2026) is None
