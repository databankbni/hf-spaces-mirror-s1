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


# ─── SleeperPropsSource ───────────────────────────────────────────────────────

class TestSleeperPropsSource:
    """Parsing Sleeper's player-prop feed.

    The payload below is the real shape, copied from a production probe: the
    line and both prices live on the `options`, prices are decimal payout
    multipliers quoted as strings, and an MLB request comes back carrying
    other sports' markets too. These tests pin that, and pin that anything
    unrecognised is dropped rather than guessed at.
    """

    @staticmethod
    def _line(subject, wager, value, over, under, sport="mlb", **kw):
        def opt(outcome, mult):
            return {"status": "active", "subject_id": subject, "outcome": outcome,
                    "sport": sport, "wager_type": wager, "outcome_type": "over_under",
                    "line_type": "normal", "game_status": "pre_game",
                    "outcome_value": value, "payout_multiplier": mult,
                    "subject_position": "SS", "subject_team": "CHC"}
        item = {"status": "active", "subject_id": subject, "sport": sport,
                "season": "2026", "game_id": "1301364100386791424",
                "market_type": f"{wager}_over_under_player_{subject}",
                "subject_type": "player", "wager_type": wager,
                "outcome_type": "over_under", "line_type": "normal",
                "game_status": "pre_game",
                "options": [opt("over", over), opt("under", under)]}
        item.update(kw)
        return item

    @property
    def LINES(self):
        return [
            self._line("1049", "bat_walks", 0.5, "3.22", "1.19"),
            self._line("6002", "strike_outs", 5.5, "1.90", "1.75"),
            # Sleeper serves every sport it runs regardless of the request.
            self._line("9001", "kills_maps_1_2", 30.5, "1.85", "1.85", sport="cs2"),
            # Runs scored have no per-batter distribution to price against.
            self._line("1049", "runs", 0.5, "2.50", "1.45"),
            # In-progress lines are kept and tagged, not dropped — they're
            # priced against a simulation of the innings that are left.
            self._line("1049", "hits", 0.5, "1.60", "2.10", game_status="in_game"),
        ]

    PLAYERS = {
        "1049": {"first_name": "Jos\u00e9", "last_name": "Ram\u00edrez", "team": "CLE"},
        "6002": {"full_name": "Tarik Skubal", "team": "DET"},
        "9001": {"full_name": "Some Esports Player"},
    }

    def _source(self):
        from thebeast.data.sources.sleeper import SleeperPropsSource

        src = SleeperPropsSource()
        SleeperPropsSource._players_cache = self.PLAYERS
        return src

    def _fetch(self, src):
        with patch.object(type(src), "_get", return_value=self.LINES):
            return src.fetch_props()

    def test_parses_batter_and_pitcher_props(self) -> None:
        props = {(p.side, p.stat): p for p in self._fetch(self._source())}
        # ("batter", "hits") is the in-game line, which is kept and tagged.
        assert set(props) == {("batter", "bb"), ("pitcher", "k"), ("batter", "hits")}

        walks = props[("batter", "bb")]
        # The line lives on the options, not the parent item.
        assert walks.line == 0.5
        # Decimal payout multipliers, quoted as strings: 3.22x → +222,
        # 1.19x → -526. The 15% hold that implies is this product's normal.
        assert walks.over_price == 222
        assert walks.under_price == -526
        # Accents are stripped so the name matches our own statlines.
        assert walks.player_key == "jose ramirez"
        assert walks.team == "CHC"  # the line's own team, not the directory's

        ks = props[("pitcher", "k")]
        assert ks.line == 5.5
        assert ks.over_price == -111 and ks.under_price == -133

    def test_other_sports_are_dropped(self) -> None:
        """An MLB request comes back carrying esports markets; a name collision
        there would otherwise be priced against a hitter's distribution."""
        assert all(p.raw_stat != "kills_maps_1_2" for p in self._fetch(self._source()))

    def test_unpriceable_markets_are_dropped(self) -> None:
        stats = {p.raw_stat for p in self._fetch(self._source())}
        assert "runs" not in stats   # no per-batter runs-scored distribution

    def test_live_lines_come_back_tagged(self) -> None:
        """In-progress props are the most time-sensitive thing the feed carries.
        They were being dropped at parse time, which is why none ever appeared."""
        props = self._fetch(self._source())
        live = [p for p in props if p.raw_stat == "hits"]
        assert live, "an in-game prop must survive parsing"
        assert live[0].is_live is True
        assert live[0].game_status == "in_game"
        # Pregame ones are still marked as such, so the two can't be confused.
        pre = [p for p in props if p.raw_stat == "bat_walks"]
        assert pre and pre[0].is_live is False

    def test_unreachable_feed_yields_no_props(self) -> None:
        src = self._source()
        with patch.object(type(src), "_get", side_effect=OSError("no route")):
            assert src.fetch_props() == []

    def test_probe_reports_what_came_back(self) -> None:
        src = self._source()
        with patch.object(type(src), "_get", return_value=self.LINES):
            out = src.probe()
        assert out["reachable"] is True
        assert out["count"] == len(self.LINES)
        assert "wager_type" in out["sample_keys"]
        assert "payout_multiplier" in out["option_keys"]
        # The vocabulary is what a broken parser gets corrected against.
        assert out["vocabulary"]["wager_type=bat_walks"] == 1

    def test_probe_reports_an_unreachable_feed(self) -> None:
        src = self._source()
        with patch.object(type(src), "_get", side_effect=OSError("no route")):
            out = src.probe()
        assert out["reachable"] is False
        assert "no route" in out["error"]


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


class TestSleeperTeamLines:
    """Team markets come from the Picks GraphQL API, not the REST props feed.

    Every field asserted here is one Sleeper's own schema introspection
    named on its `Line` type, so this is written against the server's
    vocabulary rather than a guess at it. What the schema does *not* describe
    is the container `my_picks_init` returns — it is an opaque `Map` — so the
    parser finds Lines by their own shape, and that is what these pin.
    """

    def _line(self, wager, subject_type="team", **kw):
        line = {
            "sport": "mlb", "status": "active", "subject_type": subject_type,
            "wager_type": wager, "outcome_type": "over_under",
            "game_id": "1301363865124085761", "game_status": "pre_game",
            "subject": {"team": "WSH"}, "payout_multiplier": "1.54",
            "outcome": "over", "outcome_value": None,
        }
        line.update(kw)
        return line

    def _fetch(self, monkeypatch, payload):
        from thebeast.data.sources import sleeper as mod
        monkeypatch.setenv("SLEEPER_AUTH_TOKEN", "test-token")
        monkeypatch.setattr(
            mod.SleeperPropsSource, "_graphql_authed",
            lambda s, q, t: {"data": {"my_picks_init": payload}})
        return mod.SleeperPropsSource().fetch_team_lines()

    def test_without_a_token_it_asks_for_nothing(self, monkeypatch):
        """my_picks_init answers an anonymous call 'Unauthorized', so calling
        it tokenless would be a guaranteed-failed request every slate."""
        from thebeast.data.sources import sleeper as mod
        monkeypatch.delenv("SLEEPER_AUTH_TOKEN", raising=False)

        def fail(*a, **k):
            raise AssertionError("must not call the API without a token")

        monkeypatch.setattr(mod.SleeperPropsSource, "_graphql_authed", fail)
        assert mod.SleeperPropsSource().fetch_team_lines() == []

    def test_a_moneyline_is_read_off_the_line_fields(self, monkeypatch):
        lines = self._fetch(monkeypatch, {"lines": [self._line("moneyline")]})
        assert len(lines) == 1
        assert lines[0].market == "moneyline"
        assert lines[0].team == "WSH"
        assert lines[0].price == -185          # 1.54x → -185
        assert lines[0].game_id == "1301363865124085761"

    def test_a_spread_keeps_its_number(self, monkeypatch):
        lines = self._fetch(monkeypatch,
                            {"lines": [self._line("spread", outcome_value=-1.5)]})
        assert lines[0].market == "spread" and lines[0].line == -1.5

    def test_a_total_records_which_side_the_price_is_for(self, monkeypatch):
        lines = self._fetch(monkeypatch, {"lines": [
            self._line("total", outcome="over", outcome_value=7.5),
            self._line("total", outcome="under", outcome_value=7.5),
        ]})
        assert {l.market for l in lines} == {"total"}
        assert lines[0].over_price is not None and lines[0].under_price is None
        assert lines[1].under_price is not None and lines[1].over_price is None

    def test_lines_are_found_however_deeply_they_are_nested(self, monkeypatch):
        """`my_picks_init` returns an opaque Map, so the container shape is not
        in the schema and must not be assumed."""
        buried = {"picks": {"mlb": {"boards": [
            {"markets": [self._line("moneyline")]}]}}}
        assert len(self._fetch(monkeypatch, buried)) == 1

    def test_player_props_are_left_to_the_rest_feed(self, monkeypatch):
        assert self._fetch(monkeypatch, {"lines": [
            self._line("hits", subject_type="player")]}) == []

    def test_other_sports_are_dropped(self, monkeypatch):
        assert self._fetch(monkeypatch, {"lines": [
            self._line("moneyline", sport="nba")]}) == []

    def test_an_unknown_market_is_dropped_rather_than_mispriced(self, monkeypatch):
        assert self._fetch(monkeypatch, {"lines": [
            self._line("first_five_innings")]}) == []

    def test_an_inactive_line_is_dropped(self, monkeypatch):
        assert self._fetch(monkeypatch, {"lines": [
            self._line("moneyline", status="closed")]}) == []

    def test_a_live_line_is_flagged(self, monkeypatch):
        lines = self._fetch(monkeypatch, {"lines": [
            self._line("moneyline", game_status="in_game")]})
        assert lines[0].is_live is True

    def test_an_unauthorized_response_is_empty_not_a_crash(self, monkeypatch):
        """This is exactly what the API returns today."""
        from thebeast.data.sources import sleeper as mod
        monkeypatch.setenv("SLEEPER_AUTH_TOKEN", "stale")
        monkeypatch.setattr(
            mod.SleeperPropsSource, "_graphql_authed",
            lambda s, q, t: {"data": {"my_picks_init": None},
                             "errors": [{"code": "unauthorized"}]})
        assert mod.SleeperPropsSource().fetch_team_lines() == []
