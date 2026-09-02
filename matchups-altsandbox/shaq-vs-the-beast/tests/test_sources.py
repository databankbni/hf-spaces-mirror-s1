"""Tests for thebeast.data.sources — external HTTP calls are mocked at the
requests/pybaseball boundary. Internal logic (normalization, rate calculation,
idempotent writes) runs against real fixture DataFrames."""
from __future__ import annotations

from datetime import date, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from thebeast.data.models import BatterStatline, GameSchedule, LineupCard, PitcherStatline
from thebeast.data.repository import SQLiteRepository
from thebeast.data.sources.statcast import StatcastSource
from thebeast.data.sources.schedules import MLBScheduleSource


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def repo(tmp_path: Path) -> SQLiteRepository:
    return SQLiteRepository(str(tmp_path / "test.db"))


def _make_statcast_pa_df() -> pd.DataFrame:
    """Minimal Statcast PA-level DataFrame with 100 rows for one batter."""
    import numpy as np
    rng = np.random.default_rng(42)
    n = 100
    events = rng.choice(
        ["single", "double", "triple", "home_run", "walk", "hit_by_pitch",
         "strikeout", "field_out"],
        size=n,
        p=[0.15, 0.05, 0.01, 0.04, 0.10, 0.01, 0.22, 0.42],
    )
    return pd.DataFrame({
        "batter": [621566] * n,
        "pitcher": [477132] * n,
        "game_year": [2023] * n,
        "events": events,
        "stand": rng.choice(["L", "R"], size=n),
        "p_throws": rng.choice(["L", "R"], size=n),
        "woba_value": rng.uniform(0, 2, size=n),
        "estimated_woba_using_speedangle": rng.uniform(0, 2, size=n),
    })


def _make_schedule_response() -> dict:
    """Minimal MLB Stats API schedule response for one game."""
    return {
        "dates": [{
            "date": "2024-04-01",
            "games": [{
                "gamePk": 745456,
                "gameDate": "2024-04-01T23:05:00Z",
                "teams": {
                    "home": {
                        "team": {"id": 111, "abbreviation": "BOS"},
                        "probablePitcher": {"id": 477132},
                    },
                    "away": {
                        "team": {"id": 147, "abbreviation": "NYY"},
                        "probablePitcher": {"id": 543243},
                    },
                },
                "venue": {"id": 3, "name": "Fenway Park"},
                "lineups": {
                    "homePlayers": [{"id": 646240}, {"id": 605141}],
                    "awayPlayers": [{"id": 621566}, {"id": 545361}],
                },
            }],
        }]
    }


# ─── StatcastSource ───────────────────────────────────────────────────────────

class TestStatcastSource:
    def test_builds_batter_statline_from_df(self, repo: SQLiteRepository) -> None:
        src = StatcastSource(repo)
        df = _make_statcast_pa_df()

        with patch.object(src, "_fetch_statcast_df", return_value=df):
            src.fetch_batter(player_id=621566, season=2023)

        b = repo.get_batter(621566, 2023)
        assert b is not None
        assert b.player_id == 621566
        assert b.season == 2023
        assert b.pa == 100

    def test_outcome_rates_sum_to_one(self, repo: SQLiteRepository) -> None:
        src = StatcastSource(repo)
        df = _make_statcast_pa_df()

        with patch.object(src, "_fetch_statcast_df", return_value=df):
            src.fetch_batter(player_id=621566, season=2023)

        b = repo.get_batter(621566, 2023)
        assert b is not None
        total = (b.single_rate + b.double_rate + b.triple_rate + b.hr_rate
                 + b.bb_rate + b.hbp_rate + b.k_rate + b.ipo_rate)
        assert abs(total - 1.0) < 1e-6

    def test_idempotent_fetch(self, repo: SQLiteRepository) -> None:
        src = StatcastSource(repo)
        df = _make_statcast_pa_df()

        with patch.object(src, "_fetch_statcast_df", return_value=df):
            src.fetch_batter(player_id=621566, season=2023)
            src.fetch_batter(player_id=621566, season=2023)

        import sqlite3
        conn = sqlite3.connect(repo.path)
        count = conn.execute(
            "SELECT COUNT(*) FROM batter_statlines WHERE player_id=621566"
        ).fetchone()[0]
        conn.close()
        assert count == 1

    def test_builds_pitcher_statline_from_df(self, repo: SQLiteRepository) -> None:
        src = StatcastSource(repo)
        df = _make_statcast_pa_df()

        with patch.object(src, "_fetch_statcast_df", return_value=df):
            src.fetch_pitcher(player_id=477132, season=2023, role="starter")

        p = repo.get_pitcher(477132, 2023)
        assert p is not None
        assert p.role == "starter"
        assert p.bf > 0


# ─── MLBScheduleSource ────────────────────────────────────────────────────────

class TestMLBScheduleSource:
    def test_saves_schedule_from_api(self, repo: SQLiteRepository) -> None:
        src = MLBScheduleSource(repo)
        payload = _make_schedule_response()

        with patch.object(src, "_fetch_json", return_value=payload):
            src.fetch_schedule(date(2024, 4, 1))

        games = repo.get_schedule(date(2024, 4, 1))
        assert len(games) == 1
        g = games[0]
        assert g.home_team_id == "BOS"
        assert g.away_team_id == "NYY"

    def test_a_posted_lineup_survives_a_missing_probable_pitcher(
        self, repo: SQLiteRepository
    ) -> None:
        """MLB posts a batting order before it names a starter, and this used to
        discard the whole card when that happened — throwing away the one thing
        actually confirmed, the nine hitters, because the pitcher hadn't been
        announced. Zero is the sentinel the rest of the app already reads as
        'starter not yet announced'."""
        src = MLBScheduleSource(repo)
        payload = _make_schedule_response()
        for side in ("home", "away"):
            payload["dates"][0]["games"][0]["teams"][side].pop("probablePitcher")

        with patch.object(src, "_fetch_json", return_value=payload):
            src.fetch_schedule(date(2024, 4, 1))

        lc = repo.get_lineup("2024-04-01-NYY-BOS", "BOS")
        assert lc is not None, "the posted lineup was kept"
        assert lc.confirmed is True
        assert lc.starter_id == 0
        assert lc.batting_order == [646240, 605141]

    def test_a_later_poll_cannot_downgrade_a_posted_lineup(
        self, repo: SQLiteRepository
    ) -> None:
        """MLB drops `lineups` from the payload once a game goes final. Writing
        that over the top would replace the real card with placeholders."""
        src = MLBScheduleSource(repo)
        with patch.object(src, "_fetch_json",
                          return_value=_make_schedule_response()):
            src.fetch_schedule(date(2024, 4, 1))
        confirmed = repo.get_lineup("2024-04-01-NYY-BOS", "BOS")
        assert confirmed.confirmed is True

        stripped = _make_schedule_response()
        stripped["dates"][0]["games"][0].pop("lineups")
        with patch.object(src, "_fetch_json", return_value=stripped):
            src.fetch_schedule(date(2024, 4, 1))

        after = repo.get_lineup("2024-04-01-NYY-BOS", "BOS")
        assert after.confirmed is True
        assert after.batting_order == confirmed.batting_order

    def test_idempotent_schedule_fetch(self, repo: SQLiteRepository) -> None:
        src = MLBScheduleSource(repo)
        payload = _make_schedule_response()

        with patch.object(src, "_fetch_json", return_value=payload):
            src.fetch_schedule(date(2024, 4, 1))
            src.fetch_schedule(date(2024, 4, 1))

        games = repo.get_schedule(date(2024, 4, 1))
        assert len(games) == 1


class TestMLBBoxscoreSource:
    """Pitchers must come back in the order they appeared.

    MLB keys `players` by "IDnnnnnn", so iterating it yields no meaningful
    order. Anything downstream that reads the starter off the front of the list
    — the accuracy scorer does — silently gets a reliever instead, drops the
    real start as a mismatch, and folds the starter's line into the bullpen's.
    That is a wrong number, not an error, so it is pinned here.
    """

    def _payload(self, *, order=True):
        def arm(pid, name, ip, pitches):
            return {
                "person": {"id": pid, "fullName": name},
                "position": {"abbreviation": "P"},
                "stats": {"pitching": {
                    "inningsPitched": ip, "numberOfPitches": pitches,
                    "hits": 4, "earnedRuns": 2, "baseOnBalls": 1,
                    "strikeOuts": 5}},
            }

        team = {
            # Deliberately not in appearance order, and not sorted by id.
            "players": {
                "ID300": arm(300, "Third Arm", "1.0", 14),
                "ID100": arm(100, "The Starter", "6.0", 95),
                "ID200": arm(200, "Second Arm", "2.0", 28),
            },
        }
        if order:
            team["pitchers"] = [100, 200, 300]
        return {"teams": {"home": team, "away": {"players": {}}}}

    def _parse(self, payload):
        from thebeast.data.sources.boxscore import MLBBoxscoreSource
        return MLBBoxscoreSource()._parse(payload, "g1")

    def test_pitchers_follow_the_appearance_order_array(self) -> None:
        box = self._parse(self._payload())
        assert [p.name for p in box.home.pitchers] == [
            "The Starter", "Second Arm", "Third Arm"]
        assert box.home.pitchers[0].player_id == 100

    def test_without_the_order_array_the_workhorse_leads(self) -> None:
        """A fallback, not a guess at appearance order: if MLB stops sending
        the array, the pitcher who threw the most is the best available proxy
        for the starter, and far better than dict order."""
        box = self._parse(self._payload(order=False))
        assert box.home.pitchers[0].name == "The Starter"

    def test_pitch_counts_are_read_from_the_payload(self) -> None:
        box = self._parse(self._payload())
        assert [p.pitches for p in box.home.pitchers] == [95, 28, 14]

    def test_a_pitcher_missing_from_the_order_array_is_kept(self) -> None:
        payload = self._payload()
        payload["teams"]["home"]["pitchers"] = [100, 200]   # 300 omitted
        box = self._parse(payload)
        assert [p.player_id for p in box.home.pitchers] == [100, 200, 300]


