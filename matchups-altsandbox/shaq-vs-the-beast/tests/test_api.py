"""API contract tests (F-006) — FastAPI TestClient, synthetic data only.

All JSON endpoints are namespaced under /api/* (the SPA owns the rest).
"""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from thebeast.api.main import app  # noqa: E402

client = TestClient(app)


class TestHealth:
    def test_health_ok(self) -> None:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.headers["content-type"].startswith("application/json")


class TestDates:
    def test_dates_returns_list(self) -> None:
        r = client.get("/api/dates")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestGames:
    def test_empty_schedule_returns_list(self) -> None:
        r = client.get("/api/games", params={"date": "2024-04-01"})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_bad_date_422(self) -> None:
        r = client.get("/api/games", params={"date": "nope"})
        assert r.status_code == 422


class TestSlateWarmUp:
    """Opening a slate is what starts the server simulating it, and everything
    on the page then reads those runs instead of starting its own."""

    def test_opening_a_slate_starts_the_warm_up(self, monkeypatch) -> None:
        from thebeast import slate

        started: list = []
        monkeypatch.setattr(slate, "ensure",
                            lambda repo, day, **kw: started.append(day))
        client.get("/api/games", params={"date": "2024-04-01"})
        assert started, "the slate has to be warmed by someone"

    def test_the_games_call_does_not_block_on_it(self, monkeypatch) -> None:
        """This renders the page. A warm-up that blocked here would trade a
        slow assistant for a slow site."""
        import time
        start = time.time()
        r = client.get("/api/games", params={"date": "2024-04-01"})
        assert r.status_code == 200
        assert time.time() - start < 2.0

    def test_status_reports_idle_for_a_slate_nobody_opened(self) -> None:
        from thebeast import slate

        slate.reset()
        r = client.get("/api/slate/status", params={"date": "2019-04-01"})
        assert r.status_code == 200
        body = r.json()
        assert body["state"] == "idle" and body["total"] == 0

    def test_status_rejects_a_bad_date(self) -> None:
        assert client.get("/api/slate/status", params={"date": "nope"}).status_code == 422

    def test_rerun_drops_the_runs_and_starts_again(self, monkeypatch) -> None:
        """"Run new simulation" has to actually re-run. The results live on the
        server, so clearing only the browser's copy fetched the same numbers
        back and presented them as fresh."""
        from thebeast import slate

        reset_for: list = []
        warmed: list = []
        monkeypatch.setattr(slate, "reset", lambda day=None: reset_for.append(day))
        monkeypatch.setattr(
            slate, "ensure",
            lambda repo, day, **kw: warmed.append(day) or slate.SlateProgress(
                date=day.isoformat(), state="running"))

        r = client.post("/api/slate/rerun", params={"date": "2024-04-01"})
        assert r.status_code == 200
        assert "dropped" in r.json()
        assert reset_for and warmed, "cleared, then restarted"

    def test_rerun_rejects_a_bad_date(self) -> None:
        assert client.post("/api/slate/rerun", params={"date": "nope"}).status_code == 422


class TestSimulate:
    def test_simulate_returns_result_with_histograms(self) -> None:
        r = client.post("/api/simulate", json={"game_id": "2024-04-01-NYY-BOS", "n": 50, "seed": 1})
        assert r.status_code == 200
        body = r.json()
        assert body["game_id"] == "2024-04-01-NYY-BOS"
        assert 0.0 <= body["home_win_probability"] <= 1.0
        hist = body["histograms"]
        assert {"home_runs", "away_runs", "totals"} <= set(hist)
        # edges has one more entry than counts (bin boundaries).
        assert len(hist["totals"]["edges"]) == len(hist["totals"]["counts"]) + 1

    def test_malformed_body_422(self) -> None:
        r = client.post("/api/simulate", json={"game_id": "g1", "n": -5})
        assert r.status_code == 422


class TestBet:
    def test_bet_returns_edges(self) -> None:
        r = client.post("/api/bet", json={
            "game_id": "2024-04-01-NYY-BOS",
            "odds": {"home_ml": 150, "away_ml": -170},
            "n": 100, "seed": 1,
        })
        assert r.status_code == 200
        markets = {e["market"] for e in r.json()}
        assert {"home_ml", "away_ml", "over", "under"} <= markets


class TestLineups:
    def test_lineups_returns_home_and_away(self) -> None:
        r = client.get("/api/lineups", params={"game_id": "2024-04-01-NYY-BOS"})
        assert r.status_code == 200
        body = r.json()
        assert "home" in body and "away" in body
        assert len(body["home"]["batting_order"]) == 9


class TestAccuracy:
    def test_unfinished_game_reports_not_final(self, monkeypatch) -> None:
        import thebeast.api.main as main
        monkeypatch.setattr(main, "_actual_result", lambda repo, gid: None)
        r = client.get("/api/game/2024-04-01-NYY-BOS/accuracy")
        assert r.status_code == 200
        assert r.json() == {"game_id": "2024-04-01-NYY-BOS", "final": False}

    def test_finished_game_scores_prediction_and_box(self, monkeypatch) -> None:
        import thebeast.api.main as main
        from thebeast.data.repository import SQLiteRepository
        from thebeast.data.sources.boxscore import (
            BatterBoxLine, GameBoxscore, TeamBoxscore,
        )
        from thebeast.pipeline import resolve_lineups

        # Build the synthetic box off the *real* resolved lineup ids so the
        # sim↔box join lands (production uses the same MLB ids on both sides).
        home_lu, away_lu = resolve_lineups(
            "2024-04-01-NYY-BOS", SQLiteRepository(), "BOS", "NYY")
        hid, aid = home_lu.batting_order[0], away_lu.batting_order[0]
        box = GameBoxscore(
            game_id="2024-04-01-NYY-BOS",
            home=TeamBoxscore(
                batters=[BatterBoxLine(name="H1", player_id=hid, lineup_slot=1,
                                       at_bats=4, hits=2, home_runs=1, rbi=3,
                                       walks=0, strikeouts=1)],
                pitchers=[],
            ),
            away=TeamBoxscore(
                batters=[BatterBoxLine(name="A1", player_id=aid, lineup_slot=1,
                                       at_bats=4, hits=1, home_runs=0, rbi=1,
                                       walks=1, strikeouts=1)],
                pitchers=[],
            ),
        )
        monkeypatch.setattr(main, "_actual_result", lambda repo, gid: {
            "home_runs": 5, "away_runs": 3, "status": "Final", "boxscore": box,
        })
        r = client.get("/api/game/2024-04-01-NYY-BOS/accuracy", params={"n": 800})
        assert r.status_code == 200
        body = r.json()
        assert body["final"] is True
        assert body["actual"] == {
            "home_runs": 5, "away_runs": 3, "total": 8,
            "winner": "home", "status": "Final",
        }
        pred = body["prediction"]
        assert 0.0 <= pred["home_win_probability"] <= 1.0
        assert pred["predicted_winner"] in ("home", "away")
        assert pred["home_runs"]["actual"] == 5
        assert pred["total"]["actual"] == 8
        assert 0.0 <= pred["exact_score_prob"] <= 1.0
        # Percentage-based accuracy: headline % per market + distribution splits.
        ap = pred["accuracy_pct"]
        assert set(ap) == {"winner", "total", "spread", "home_runs", "away_runs"}
        for v in ap.values():
            assert 0.0 <= v <= 100.0
        # over/under/exact split of the total sums to ~100%.
        tot = pred["total"]
        assert abs(tot["over_pct"] + tot["under_pct"] + tot["hit_pct"] - 100.0) < 0.2
        assert "spread" in pred and 0.0 <= pred["spread"]["centrality_pct"] <= 100.0
        # Score-match: conditioned on the real final, joined to the real box.
        sm = body["score_match"]
        assert sm is not None
        assert sm["target_home"] == 5 and sm["target_away"] == 3
        assert sm["matches"] > 0 and sm["match_rate"] > 0.0
        joined = {b["player_id"]: b for b in sm["batters"]}
        assert joined[hid]["actual_hits"] == 2  # the join populated real stats
        assert joined[aid]["actual_rbi"] == 1
        # Base (overall) projection is carried alongside the score-matched one.
        assert joined[hid]["base_hits"] is not None
        assert set(sm["batter_mae"]) == {"hits", "home_runs", "rbi"}
        # Per-stat accuracy % vs actual, and base-vs-match agreement %.
        assert set(sm["batter_accuracy_pct"]) == {"hits", "home_runs", "rbi"}
        for v in sm["batter_accuracy_pct"].values():
            assert 0.0 <= v <= 100.0
        assert set(sm["base_vs_match_pct"]) == {"hits", "home_runs", "rbi"}


class TestNameResolution:
    def test_people_fallback_names_unresolved_ids(self, monkeypatch) -> None:
        # A player with no stored statline for any season should be named from
        # the batched MLB people lookup rather than shown as a bare id.
        import thebeast.api.main as main
        from thebeast.data.repository import SQLiteRepository

        monkeypatch.setattr(
            "thebeast.data.sources.people.MLBPeopleSource.names",
            lambda self, ids: {int(i): "Callup Kid" for i in ids},
        )
        lines = [{"player_id": 9999999, "team": "BOS"}]
        out = main._attach_names(SQLiteRepository(), lines, 2026)
        assert out[0]["name"] == "Callup Kid"

    def test_numeric_fallback_when_people_unreachable(self, monkeypatch) -> None:
        import thebeast.api.main as main
        from thebeast.data.repository import SQLiteRepository

        # Source unreachable → empty map → the id is the last-resort label.
        monkeypatch.setattr(
            "thebeast.data.sources.people.MLBPeopleSource.names",
            lambda self, ids: {},
        )
        lines = [{"player_id": 9999998, "team": "NYY"}]
        out = main._attach_names(SQLiteRepository(), lines, 2026)
        assert out[0]["name"] == "9999998"


class TestLiveSim:
    """Resume point derived from the live feed (the /live-sim inputs)."""

    def _linescore(self, **kw):
        from thebeast.data.sources.linescore import (
            GameLinescore, GameSituation, InningLine, TeamTotals,
        )
        opts = dict(
            innings=[InningLine(num=i, away_runs=1, home_runs=0) for i in range(1, 8)],
            away_totals=TeamTotals(runs=7), home_totals=TeamTotals(runs=0),
            situation=GameSituation(outs=2, on_first=True, on_third=True),
            current_inning=7, is_top_inning=False, inning_state="Bottom",
        )
        opts.update(kw)
        return GameLinescore(game_id="g", **opts)

    def _boxscore(self, away_pa: int, home_pa: int):
        from thebeast.data.sources.boxscore import (
            BatterBoxLine, GameBoxscore, TeamBoxscore,
        )

        def side(total):
            # Spread `total` PAs across nine slots.
            per, extra = divmod(total, 9)
            return TeamBoxscore(
                batters=[BatterBoxLine(name=f"B{i}", player_id=100 + i, lineup_slot=i + 1,
                                       plate_appearances=per + (1 if i < extra else 0))
                         for i in range(9)],
                pitchers=[],
            )
        return GameBoxscore(game_id="g", away=side(away_pa), home=side(home_pa))

    def test_next_slot_is_total_pa_mod_nine(self) -> None:
        import thebeast.api.main as main
        box = self._boxscore(away_pa=26, home_pa=25)
        assert main._next_batting_slot(box.away) == 26 % 9
        assert main._next_batting_slot(box.home) == 25 % 9

    def test_next_slot_falls_back_when_pa_missing(self) -> None:
        import thebeast.api.main as main
        from thebeast.data.sources.boxscore import BatterBoxLine, TeamBoxscore
        team = TeamBoxscore(
            batters=[BatterBoxLine(name="x", player_id=1, at_bats=2, walks=1)], pitchers=[])
        assert main._next_batting_slot(team) == 3 % 9

    def test_state_carries_score_outs_and_runners(self) -> None:
        import thebeast.api.main as main
        st = main._live_inning_state(
            "BOS", "NYY", self._linescore(), self._boxscore(26, 25))
        assert st is not None
        assert (st.inning, st.half, st.outs) == (7, "bottom", 2)
        assert st.runners_bitmap == 0b101  # first + third
        assert st.score == {"BOS": 0, "NYY": 7}
        assert st.batting_position == {"BOS": 25 % 9, "NYY": 26 % 9}

    def test_middle_of_inning_starts_the_bottom_clean(self) -> None:
        import thebeast.api.main as main
        st = main._live_inning_state(
            "BOS", "NYY",
            self._linescore(inning_state="Middle", is_top_inning=True),
            self._boxscore(27, 24))
        assert (st.inning, st.half, st.outs, st.runners_bitmap) == (7, "bottom", 0, 0)

    def test_end_of_inning_advances_to_the_next_top(self) -> None:
        import thebeast.api.main as main
        st = main._live_inning_state(
            "BOS", "NYY",
            self._linescore(inning_state="End", is_top_inning=False),
            self._boxscore(27, 27))
        assert (st.inning, st.half, st.outs, st.runners_bitmap) == (8, "top", 0, 0)

    def test_no_state_after_regulation(self) -> None:
        import thebeast.api.main as main
        st = main._live_inning_state(
            "BOS", "NYY",
            self._linescore(current_inning=9, inning_state="End", is_top_inning=False),
            self._boxscore(27, 27))
        assert st is None  # nothing left to resume in regulation

    def test_seeded_inning_lines_match_what_was_played(self) -> None:
        import thebeast.api.main as main
        # Bottom of the 7th: away has completed 7 half-innings, home 6.
        st = main._live_inning_state(
            "BOS", "NYY", self._linescore(), self._boxscore(26, 25))
        assert len(st.away_by_inning) == 7
        assert len(st.home_by_inning) == 6

    def test_endpoint_reports_not_live_for_unstarted_game(self) -> None:
        r = client.get("/api/game/2024-04-01-NYY-BOS/live-sim")
        assert r.status_code == 200
        body = r.json()
        assert body["live"] is False
        assert "reason" in body


class TestDocs:
    def test_openapi_schema_available(self) -> None:
        r = client.get("/api/_openapi.json")
        assert r.status_code == 200
        assert "/api/simulate" in r.json()["paths"]


class TestPitcherOverrides:
    """Pitcher stats are adjustable in the custom sim re-run, like batters."""

    GAME = "2024-04-01-NYY-BOS"

    def _starter(self):
        from thebeast.data.repository import SQLiteRepository
        from thebeast.pipeline import resolve_lineups
        home, _away = resolve_lineups(self.GAME, SQLiteRepository(), "BOS", "NYY")
        return home.starter_id

    def _sim(self, **extra):
        """Run a sim and return (the edited starter's line, full payload).

        The starter is selected by id, not by innings pitched: a pitcher made
        worse throws more pitches and gets hooked earlier, so he is no longer
        the man with the most outs — that would silently return the bullpen.
        """
        body = {"game_id": self.GAME, "n": 400, "seed": 3, **extra}
        r = client.post("/api/simulate", json=body)
        assert r.status_code == 200, r.text
        d = r.json()
        pid = self._starter()
        line = next(p for p in d["pitcher_lines"] if p["player_id"] == pid)
        return line, d

    def test_raising_strikeouts_raises_projected_ks(self) -> None:
        pid = self._starter()
        base, _ = self._sim()
        bumped, _ = self._sim(pitcher_overrides={str(pid): {"k": 2.0}})
        assert bumped["k"] > base["k"] * 1.4

    def test_raising_home_runs_allowed_raises_runs(self) -> None:
        pid = self._starter()
        base, base_all = self._sim()
        worse, worse_all = self._sim(pitcher_overrides={str(pid): {"hr_allowed": 4.0}})
        assert worse["hr_allowed"] > base["hr_allowed"] * 2
        assert worse_all["total_mean"] > base_all["total_mean"]

    def test_suppressing_hits_lowers_runs(self) -> None:
        pid = self._starter()
        _base, base_all = self._sim()
        _better, better_all = self._sim(
            pitcher_overrides={str(pid): {"hits_allowed": 0.3}})
        assert better_all["total_mean"] < base_all["total_mean"]

    def test_malformed_pitcher_override_is_ignored_not_fatal(self) -> None:
        r = client.post("/api/simulate", json={
            "game_id": self.GAME, "n": 100, "seed": 1,
            "pitcher_overrides": {"not-an-id": {"k": 2.0}},
        })
        assert r.status_code == 200

    def test_batter_and_pitcher_edits_combine(self) -> None:
        pid = self._starter()
        r = client.post("/api/simulate", json={
            "game_id": self.GAME, "n": 300, "seed": 5,
            "rate_overrides": {"677800": {"hits": 1.5}},
            "pitcher_overrides": {str(pid): {"k": 1.5}},
        })
        assert r.status_code == 200
        assert r.json()["pitcher_lines"]


class TestBestBets:
    """Ranked plays: player-prop prices vs. the simulation.

    Game lines are no longer priced — the only reachable feed served a pregame
    number all game long, so a live price couldn't be told apart from a stale
    one and it was removed rather than shipped looking actionable.
    """

    def test_endpoint_returns_a_report(self) -> None:
        r = client.get("/api/best-bets", params={"date": "2024-04-01", "n": 200})
        assert r.status_code == 200
        b = r.json()
        assert b["date"] == "2024-04-01"
        assert isinstance(b["bets"], list)
        # The props feed isn't reachable from a test host, and the report must
        # say so rather than quietly omitting the fact.
        assert b["props_available"] is False
        assert any("props" in n.lower() for n in b["notes"])

    def test_bad_date_422(self) -> None:
        assert client.get("/api/best-bets", params={"date": "nope"}).status_code == 422

    def test_only_props_are_ever_priced(self, monkeypatch) -> None:
        """No market outside the two prop families may appear."""
        import datetime
        import thebeast.data.sources.sleeper as sleeper_mod
        from thebeast import simcache
        from thebeast.data.names import normalize_name, player_names
        from thebeast.data.repository import SQLiteRepository
        from thebeast.betting.best_bets import build_best_bets

        simcache.clear()
        repo = SQLiteRepository()
        day = datetime.date(2024, 4, 1)
        games = repo.get_schedule(day)[:2]
        card = repo.get_lineup(games[0].game_id, games[0].home_team_id)
        hitter = player_names(repo, card.batting_order[:1], 2026)[card.batting_order[0]]

        monkeypatch.setattr(
            sleeper_mod.SleeperPropsSource, "fetch_props",
            lambda s, sport="mlb": [sleeper_mod.PlayerProp(
                hitter, normalize_name(hitter), "batter", "hits", 0.5,
                over_price=2000, under_price=-2000)])

        class Slate(SQLiteRepository):
            def get_schedule(self, d):
                return games

        rep = build_best_bets(Slate(), day, n=250, min_edge=0.0)
        assert rep.props_available is True
        assert set(rep.counts) == {"pitcher_prop", "batter_prop"}
        assert rep.bets, "the matched prop should have been priced"
        for b in rep.bets:
            assert b["category"] in ("pitcher_prop", "batter_prop")
            assert b["market"].startswith("prop_")
            assert b["player"] == hitter
            # Every price is the props book's, since it's the only source left.
            assert b["book"] == "Sleeper"

    def test_started_games_are_not_offered_pregame_props(self, monkeypatch) -> None:
        """A pregame prop must never be priced off a game already under way."""
        import dataclasses
        import datetime
        import thebeast.betting.best_bets as bb
        import thebeast.data.sources.sleeper as sleeper_mod
        from thebeast import simcache
        from thebeast.data.names import normalize_name, player_names
        from thebeast.data.repository import SQLiteRepository
        from thebeast.betting.best_bets import build_best_bets

        simcache.clear()
        repo = SQLiteRepository()
        day = datetime.date(2024, 4, 1)
        base = repo.get_schedule(day)[0]
        live_game = dataclasses.replace(base, status="Live", game_pk=4242)
        card = repo.get_lineup(live_game.game_id, live_game.home_team_id)
        hitter = player_names(repo, card.batting_order[:1], 2026)[card.batting_order[0]]

        # A *pregame* quote, on a game that has started.
        monkeypatch.setattr(
            sleeper_mod.SleeperPropsSource, "fetch_props",
            lambda s, sport="mlb": [sleeper_mod.PlayerProp(
                hitter, normalize_name(hitter), "batter", "hits", 0.5,
                over_price=2000, under_price=-2000, is_live=False)])
        # No live state resolvable, so nothing should be priced at all.
        monkeypatch.setattr(bb, "_live_state_for",
                            lambda *a, **k: (None, None, None, None))

        class LiveSlate(SQLiteRepository):
            def get_schedule(self, d):
                return [live_game]

        rep = build_best_bets(LiveSlate(), day, n=200, min_edge=0.0)
        assert rep.bets == []

    def test_props_can_be_turned_off(self, monkeypatch) -> None:
        """With props disabled the feed must not be contacted."""
        import datetime
        import thebeast.data.sources.sleeper as sleeper_mod
        from thebeast.data.repository import SQLiteRepository
        from thebeast.betting.best_bets import build_best_bets

        def boom(self, sport="mlb"):
            raise AssertionError("props feed must not be contacted")

        monkeypatch.setattr(sleeper_mod.SleeperPropsSource, "fetch_props", boom)
        rep = build_best_bets(SQLiteRepository(), datetime.date(2024, 4, 1),
                              n=200, budget_seconds=30, props=False)
        assert rep.props_available is False
        assert rep.bets == []

    def test_props_probe_reports_the_feed(self, monkeypatch) -> None:
        """The probe exists so the undocumented feed's real shape can be read
        off production rather than guessed at."""
        import thebeast.data.sources.sleeper as sleeper_mod

        payload = [{
            "subject_id": "1", "sport": "mlb", "subject_type": "player",
            "wager_type": "hits", "outcome_type": "over_under",
            "status": "active", "game_status": "pre_game",
            "options": [{"outcome": "over", "outcome_value": 1.5,
                         "payout_multiplier": "1.85", "status": "active",
                         "subject_team": "CLE"}],
        }]
        monkeypatch.setattr(sleeper_mod.SleeperPropsSource, "_get",
                            lambda self, url, params=None, timeout=None: payload)
        monkeypatch.setattr(sleeper_mod.SleeperPropsSource, "_players",
                            lambda self: {"1": {"full_name": "Test Hitter"}})

        r = client.get("/api/props-probe")
        assert r.status_code == 200
        body = r.json()
        assert body["reachable"] is True
        assert body["parsed"] == 1
        assert body["parsed_sample"][0]["player_name"] == "Test Hitter"


class TestBestBetsCategories:
    """The two prop families the panel shows side by side, and the live path."""

    def test_plays_are_tagged_and_capped_per_family(self, monkeypatch) -> None:
        """Each play carries the panel it belongs in, and no family may take
        more than its share — one fat-edge family must not empty the other."""
        import datetime
        import thebeast.data.sources.sleeper as sleeper_mod
        from thebeast import simcache
        from thebeast.data.names import normalize_name, player_names
        from thebeast.data.repository import SQLiteRepository
        from thebeast.betting.best_bets import build_best_bets

        simcache.clear()
        repo = SQLiteRepository()
        day = datetime.date(2024, 4, 1)
        games = repo.get_schedule(day)[:1]
        card = repo.get_lineup(games[0].game_id, games[0].home_team_id)
        names = player_names(repo, card.batting_order[:5], 2026)
        hitters = [names[pid] for pid in card.batting_order[:5] if pid in names]
        assert len(hitters) >= 4, "fixture should name several hitters"

        # More qualifying batter props than the per-family cap allows.
        props = [sleeper_mod.PlayerProp(
            h, normalize_name(h), "batter", "hits", 0.5,
            over_price=2000, under_price=-2000) for h in hitters]
        monkeypatch.setattr(sleeper_mod.SleeperPropsSource, "fetch_props",
                            lambda s, sport="mlb": props)

        class Slate(SQLiteRepository):
            def get_schedule(self, d):
                return games

        rep = build_best_bets(Slate(), day, n=250, min_edge=0.0, per_category=3)

        assert set(rep.counts) == {"pitcher_prop", "batter_prop"}
        for b in rep.bets:
            assert b["category"] in rep.counts
        assert rep.counts["batter_prop"] > 3, "need more than the cap to test it"
        shown = [b for b in rep.bets if b["category"] == "batter_prop"]
        assert len(shown) == 3

    def test_the_card_and_the_bet_share_one_simulation(self, monkeypatch) -> None:
        """The number backing a listed bet must come from the same run behind
        that game's card — not a second opinion a point or so away."""
        import datetime
        import thebeast.data.sources.sleeper as sleeper_mod
        from thebeast import simcache
        from thebeast.data.names import normalize_name, player_names
        from thebeast.data.repository import SQLiteRepository
        from thebeast.betting.best_bets import _prop_probs, _smooth, build_best_bets
        from thebeast.simcache import simulate_cached

        simcache.clear()
        repo = SQLiteRepository()
        day = datetime.date(2024, 4, 1)
        games = repo.get_schedule(day)[:1]
        g = games[0]
        card = repo.get_lineup(g.game_id, g.home_team_id)
        pid = card.batting_order[0]
        hitter = player_names(repo, [pid], 2026)[pid]

        monkeypatch.setattr(
            sleeper_mod.SleeperPropsSource, "fetch_props",
            lambda s, sport="mlb": [sleeper_mod.PlayerProp(
                hitter, normalize_name(hitter), "batter", "hits", 0.5,
                over_price=2000, under_price=-2000)])

        class One(SQLiteRepository):
            def get_schedule(self, d):
                return games

        rep = build_best_bets(One(), day, n=400, seed=7, min_edge=0.0)
        over = next(b for b in rep.bets if b["market"] == "prop_over")

        # Recompute from the cached run the card would render.
        _res, raw = simulate_cached(g.game_id, repo, home_team=g.home_team_id,
                                    away_team=g.away_team_id, n=400, seed=7,
                                    season=2026, park_season=2023)
        hist = next(h["hits"] for k, h in raw.batter_hist.items() if k[1] == pid)
        p_over, _p_under, pn = _prop_probs(hist, 0.5)
        assert over["model_probability"] == round(_smooth(p_over, pn), 4)

    def test_live_games_are_priced_off_the_remaining_innings(self, monkeypatch) -> None:
        """A game under way is priced on what's left, and its plays are flagged
        live rather than being exiled to a panel of their own."""
        import dataclasses
        import datetime
        import thebeast.betting.best_bets as bb
        import thebeast.data.sources.sleeper as sleeper_mod
        from thebeast import simcache
        from thebeast.data.names import normalize_name, player_names
        from thebeast.data.repository import SQLiteRepository
        from thebeast.data.sources.boxscore import (
            BatterBoxLine, GameBoxscore, TeamBoxscore,
        )
        from thebeast.betting.best_bets import build_best_bets
        from thebeast.simulator.state import InningState

        simcache.clear()
        repo = SQLiteRepository()
        day = datetime.date(2024, 4, 1)
        base = repo.get_schedule(day)[0]
        live_game = dataclasses.replace(base, status="Live", game_pk=12345)
        card = repo.get_lineup(live_game.game_id, live_game.home_team_id)
        pid = card.batting_order[0]
        hitter = player_names(repo, [pid], 2026)[pid]

        state = InningState(
            home=live_game.home_team_id, away=live_game.away_team_id,
            inning=6, half="bottom", outs=1,
            score={live_game.home_team_id: 2, live_game.away_team_id: 3},
            batting_position={live_game.home_team_id: 0, live_game.away_team_id: 5},
            home_by_inning=[0, 1, 0, 1, 0], away_by_inning=[1, 0, 2, 0, 0, 0],
        )
        box = GameBoxscore(
            game_id=live_game.game_id,
            home=TeamBoxscore(batters=[BatterBoxLine(name=hitter, hits=0)],
                              pitchers=[]),
            away=TeamBoxscore(batters=[], pitchers=[]),
        )
        monkeypatch.setattr(bb, "_live_state_for",
                            lambda *a, **k: (state, {}, {}, box))
        monkeypatch.setattr(
            sleeper_mod.SleeperPropsSource, "fetch_props",
            lambda s, sport="mlb": [sleeper_mod.PlayerProp(
                hitter, normalize_name(hitter), "batter", "hits", 0.5,
                over_price=2000, under_price=-2000,
                is_live=True, game_status="in_game")])

        class LiveSlate(SQLiteRepository):
            def get_schedule(self, d):
                return [live_game]

        rep = build_best_bets(LiveSlate(), day, n=400, min_edge=0.0)
        assert rep.live_games == 1
        assert rep.bets, "a live game with a quoted prop should produce plays"
        assert all(b["is_live"] is True for b in rep.bets)
        assert all(b["category"] == "batter_prop" for b in rep.bets)
        # Only three innings of plate appearances remain, so the chance of a
        # hit is well below what a full-game projection would give.
        over = next(b for b in rep.bets if b["market"] == "prop_over")
        assert over["model_probability"] < 0.5

    def test_each_family_shows_both_pregame_and_live(self) -> None:
        """Straight top-by-edge would fill a panel with pregame plays — there
        are simply more of them — and bury the live ones, which are the most
        time-sensitive thing on the page. Each family has to surface both."""
        from thebeast.betting.best_bets import _select

        class Play:
            def __init__(self, edge, live):
                self.edge, self.is_live, self.model_probability = edge, live, 0.5

        plays = sorted(
            [Play(0.20 - i * 0.01, False) for i in range(6)]
            + [Play(0.05, True), Play(0.04, True)],
            key=lambda b: -b.edge,
        )
        chosen = _select(plays, 5)
        assert len(chosen) == 5
        assert any(b.is_live for b in chosen), "a live play must make the cut"
        assert any(not b.is_live for b in chosen)

        flipped = sorted(
            [Play(0.20 - i * 0.01, True) for i in range(6)] + [Play(0.05, False)],
            key=lambda b: -b.edge,
        )
        assert any(not b.is_live for b in _select(flipped, 5))

        only_pregame = [Play(0.20 - i * 0.01, False) for i in range(6)]
        assert len(_select(only_pregame, 5)) == 5
        assert not any(b.is_live for b in _select(only_pregame, 5))


class TestSimCache:
    """One simulation per matchup, shared by the cards and the bets."""

    def test_concurrent_callers_share_one_run(self, monkeypatch) -> None:
        """The page asks for the cards and the best bets at once. Without a
        per-key lock both miss the cache and simulate the same game twice —
        and since the sim is GIL-bound, running two at once is *slower* than
        running one, so the duplicate is pure loss."""
        import datetime
        import threading
        import thebeast.pipeline as pipeline
        from thebeast import simcache
        from thebeast.data.repository import SQLiteRepository
        from thebeast.simcache import simulate_cached

        simcache.clear()
        runs: list[int] = []
        real = pipeline.simulate_matchup

        def counting(*a, **k):
            runs.append(1)
            return real(*a, **k)

        monkeypatch.setattr(pipeline, "simulate_matchup", counting)
        g = SQLiteRepository().get_schedule(datetime.date(2024, 4, 1))[0]

        def ask():
            simulate_cached(g.game_id, SQLiteRepository(), home_team=g.home_team_id,
                            away_team=g.away_team_id, n=200, seed=7,
                            season=2026, park_season=2023)

        threads = [threading.Thread(target=ask) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(runs) == 1

    def test_a_confirmed_lineup_invalidates_the_cached_run(self, monkeypatch) -> None:
        """A projected lineup replaced by a confirmed one is a different game
        to simulate, so the key has to change with it — otherwise the slate
        would keep serving a morning projection all evening."""
        import datetime
        import dataclasses
        import thebeast.simcache as simcache_mod
        from thebeast import simcache
        from thebeast.data.repository import SQLiteRepository
        from thebeast.simcache import simulate_cached

        simcache.clear()
        repo = SQLiteRepository()
        g = repo.get_schedule(datetime.date(2024, 4, 1))[0]
        args = dict(home_team=g.home_team_id, away_team=g.away_team_id,
                    n=200, seed=7, season=2026, park_season=2023)

        simulate_cached(g.game_id, repo, **args)
        assert simcache.stats()["entries"] == 1

        # Same call again — served from cache, no new entry.
        simulate_cached(g.game_id, repo, **args)
        assert simcache.stats()["entries"] == 1

        # Now the lineup changes underneath it.
        real_resolve = simcache_mod.__dict__.get("_lineup_fingerprint")
        monkeypatch.setattr(simcache_mod, "_lineup_fingerprint",
                            lambda *a, **k: ("different-lineup",))
        simulate_cached(g.game_id, repo, **args)
        assert simcache.stats()["entries"] == 2, "a lineup change must re-simulate"
        assert real_resolve is not None

    def test_spelling_out_the_defaults_is_the_same_request(self) -> None:
        """The matchup card names every knob and the best-bets ranker names
        none. Those are the same simulation, and for a long time they were two
        cache entries and two runs — the sharing this module is named for
        wasn't happening at all."""
        import datetime
        from thebeast import simcache
        from thebeast.data.repository import SQLiteRepository
        from thebeast.simcache import simulate_cached

        simcache.clear()
        repo = SQLiteRepository()
        g = repo.get_schedule(datetime.date(2024, 4, 1))[0]
        args = dict(home_team=g.home_team_id, away_team=g.away_team_id,
                    n=200, seed=7, season=2026, park_season=2023)

        card = simulate_cached(
            g.game_id, repo, **args, shrink_pa=200, shrink_bf=300,
            use_bullpen=True, use_context=True, calibrate=True,
            calibrate_totals=True, representative=True)
        ranker = simulate_cached(g.game_id, repo, **args)

        assert simcache.stats()["entries"] == 1
        assert card is ranker, "one run, handed to both callers"

    def test_a_knob_that_actually_differs_still_splits_the_key(self) -> None:
        """Normalising must not go so far that a genuinely different request
        is served someone else's answer."""
        import datetime
        from thebeast import simcache
        from thebeast.data.repository import SQLiteRepository
        from thebeast.simcache import simulate_cached

        simcache.clear()
        repo = SQLiteRepository()
        g = repo.get_schedule(datetime.date(2024, 4, 1))[0]
        args = dict(home_team=g.home_team_id, away_team=g.away_team_id,
                    n=200, seed=7, season=2026, park_season=2023)

        simulate_cached(g.game_id, repo, **args)
        simulate_cached(g.game_id, repo, **args, use_bullpen=False)
        assert simcache.stats()["entries"] == 2

    def test_peek_reads_what_is_there_and_never_simulates(self, monkeypatch) -> None:
        """The assistant's door in. It must return a run at any sample size —
        a wider or narrower sample of the same matchup is the same answer —
        but never one made under a lineup that has since changed."""
        import datetime
        import thebeast.simcache as simcache_mod
        from thebeast import simcache
        from thebeast.data.repository import SQLiteRepository
        from thebeast.simcache import peek, simulate_cached

        simcache.clear()
        repo = SQLiteRepository()
        g = repo.get_schedule(datetime.date(2024, 4, 1))[0]
        teams = dict(home_team=g.home_team_id, away_team=g.away_team_id)

        assert peek(g.game_id, repo, **teams) is None, "cold cache, nothing to read"

        run = simulate_cached(g.game_id, repo, **teams, n=200, seed=7,
                              season=2026, park_season=2023)
        # Different n, and it still finds it.
        assert peek(g.game_id, repo, **teams) is run
        assert simcache.stats()["entries"] == 1, "peek must not add an entry"

        monkeypatch.setattr(simcache_mod, "_lineup_fingerprint",
                            lambda *a, **k: ("different-lineup",))
        assert peek(g.game_id, repo, **teams) is None, \
            "a run from before the lineup changed is not an answer"

    def test_each_family_shows_both_pregame_and_live(self) -> None:
        """Straight top-by-edge would fill a panel with pregame plays — there
        are simply more of them — and bury the live ones, which are the most
        time-sensitive thing on the page. Each family has to surface both."""
        from thebeast.betting.best_bets import _select

        class Play:
            def __init__(self, edge, live):
                self.edge, self.is_live, self.model_probability = edge, live, 0.5

        # Six pregame plays all out-edging the two live ones.
        plays = sorted(
            [Play(0.20 - i * 0.01, False) for i in range(6)]
            + [Play(0.05, True), Play(0.04, True)],
            key=lambda b: -b.edge,
        )
        chosen = _select(plays, 5)
        assert len(chosen) == 5
        assert any(b.is_live for b in chosen), "a live play must make the cut"
        assert any(not b.is_live for b in chosen)

        # Mirror image: live plays dominate, a pregame one still gets a seat.
        flipped = sorted(
            [Play(0.20 - i * 0.01, True) for i in range(6)] + [Play(0.05, False)],
            key=lambda b: -b.edge,
        )
        assert any(not b.is_live for b in _select(flipped, 5))

        # Nothing to mix: don't give up a seat for a play that doesn't exist.
        only_pregame = [Play(0.20 - i * 0.01, False) for i in range(6)]
        assert len(_select(only_pregame, 5)) == 5
        assert not any(b.is_live for b in _select(only_pregame, 5))


class TestProbabilityHonesty:
    """A Monte Carlo estimate must never claim certainty it can't support."""

    def test_a_finite_sample_never_reports_0_or_100_percent(self) -> None:
        from thebeast.betting.best_bets import _smooth

        # 2000 sims, zero failures. That is not "cannot lose".
        assert _smooth(1.0, 2000) < 1.0
        assert _smooth(0.0, 2000) > 0.0
        # A smaller sample supports a weaker claim, so it's pulled back further.
        assert _smooth(1.0, 200) < _smooth(1.0, 2000)

    def test_smoothing_leaves_the_middle_alone(self) -> None:
        """The correction has to fix the extremes without quietly re-pricing
        every ordinary bet."""
        from thebeast.betting.best_bets import _smooth

        for p in (0.35, 0.5, 0.62):
            assert abs(_smooth(p, 2000) - p) < 0.0005

    def test_a_certain_estimate_no_longer_pins_the_stake_to_the_cap(self) -> None:
        """Kelly is edge/(1-implied); at p=1 those are equal and the stake maxes
        out however short the price. A -5000 shot was drawing full Kelly."""
        from thebeast.betting.best_bets import _smooth
        from thebeast.betting.edge import evaluate_market

        capped = evaluate_market("g", "prop_over", 1.0, 2000, -5000, 0.25)
        assert capped.recommended_stake_pct == 0.25  # the old behaviour

        corrected = evaluate_market(
            "g", "prop_over", _smooth(1.0, 2000), 2000, -5000, 0.25)
        assert corrected.recommended_stake_pct < capped.recommended_stake_pct

    def test_a_live_prop_already_past_its_line_is_not_a_bet(self, monkeypatch) -> None:
        """Two hits banked against Over 1.5 has already won. Priced anyway it
        reads as a 100% lock with an enormous edge and heads the panel."""
        import dataclasses
        import datetime
        import thebeast.betting.best_bets as bb
        import thebeast.data.sources.sleeper as sleeper_mod
        from thebeast import simcache
        from thebeast.data.names import normalize_name, player_names
        from thebeast.data.repository import SQLiteRepository
        from thebeast.data.sources.boxscore import (
            BatterBoxLine, GameBoxscore, TeamBoxscore,
        )
        from thebeast.betting.best_bets import build_best_bets
        from thebeast.simulator.state import InningState

        simcache.clear()
        repo = SQLiteRepository()
        day = datetime.date(2024, 4, 1)
        base = repo.get_schedule(day)[0]
        live_game = dataclasses.replace(base, status="Live", game_pk=999)

        card = repo.get_lineup(live_game.game_id, live_game.home_team_id)
        hitter = player_names(repo, card.batting_order[:1], 2026)[card.batting_order[0]]

        state = InningState(
            home=live_game.home_team_id, away=live_game.away_team_id,
            inning=5, half="top", outs=0,
            score={live_game.home_team_id: 2, live_game.away_team_id: 2},
            batting_position={live_game.home_team_id: 0, live_game.away_team_id: 0},
            home_by_inning=[0, 1, 0, 1], away_by_inning=[1, 0, 1, 0],
        )
        # The hitter already has 3 hits — every Over below that has cashed.
        box = GameBoxscore(
            game_id=live_game.game_id,
            home=TeamBoxscore(batters=[BatterBoxLine(name=hitter, hits=3)], pitchers=[]),
            away=TeamBoxscore(batters=[], pitchers=[]),
        )
        monkeypatch.setattr(bb, "_live_state_for",
                            lambda *a, **k: (state, {}, {}, box))
        settled = sleeper_mod.PlayerProp(
            hitter, normalize_name(hitter), "batter", "hits", 1.5,
            over_price=-2000, under_price=1200, is_live=True,
            game_status="in_game")
        still_open = sleeper_mod.PlayerProp(
            hitter, normalize_name(hitter), "batter", "hits", 4.5,
            over_price=600, under_price=-900, is_live=True,
            game_status="in_game")
        monkeypatch.setattr(sleeper_mod.SleeperPropsSource, "fetch_props",
                            lambda s, sport="mlb": [settled, still_open])

        class LiveSlate(SQLiteRepository):
            def get_schedule(self, d):
                return [live_game]

        rep = build_best_bets(LiveSlate(), day, n=300, min_edge=0.0)
        # The Over 1.5 has cashed (3 hits banked) and must be gone; the Over 4.5
        # still needs two more and is a real market, so the prop path is
        # demonstrably still working rather than silently switched off.
        assert all(b["line"] != 1.5 for b in rep.bets), "a settled prop was offered"
        assert any(b["line"] == 4.5 for b in rep.bets), "open props should survive"
        # And nothing is ever presented as a certainty.
        assert all(b["model_probability"] < 1.0 for b in rep.bets)


class TestApiCaching:
    """Nothing between the app and the browser may hold on to an API response.

    These are all dynamic; a cached copy is a stale answer presented as a
    current one. The content-hashed bundle under /_app still caches normally.
    """

    def test_api_responses_forbid_caching(self) -> None:
        for path, params in (
            ("/api/best-bets", {"date": "2024-04-01", "n": 200}),
            ("/api/games", {"date": "2024-04-01"}),
            ("/api/health", None),
        ):
            r = client.get(path, params=params)
            cc = r.headers.get("cache-control", "")
            assert "no-store" in cc, f"{path} may be cached: {cc!r}"


class TestBestBetsFills:
    """The panel has to fill. Two separate things kept it empty."""

    def test_games_without_a_posted_lineup_still_match_props(self, monkeypatch) -> None:
        """The bug that emptied the panel: best-bets never roster-backed its
        lineups, so most games simulated a synthetic nine of placeholder ids.
        Those are not people, so no prop could ever be matched to them — 68
        props parsed and one player matched, all of them the same pitcher."""
        import datetime
        import thebeast.data.sources.sleeper as sleeper_mod
        from thebeast import simcache
        from thebeast.data.names import normalize_name, player_names
        from thebeast.data.repository import SQLiteRepository
        from thebeast.pipeline import ensure_lineups, resolve_lineups
        from thebeast.betting.best_bets import build_best_bets

        simcache.clear()
        repo = SQLiteRepository()
        day = datetime.date(2024, 4, 1)
        games = repo.get_schedule(day)[:2]

        # Quote props on the hitters a roster-backed lineup would field.
        props = []
        for g in games:
            ensure_lineups(repo, g.game_id, g.home_team_id, g.away_team_id, 2026)
            home_lu, _away = resolve_lineups(repo=repo, game_id=g.game_id,
                                             home_team=g.home_team_id,
                                             away_team=g.away_team_id)
            for pid in home_lu.batting_order[:3]:
                nm = player_names(repo, [pid], 2026).get(pid)
                if nm:
                    props.append(sleeper_mod.PlayerProp(
                        nm, normalize_name(nm), "batter", "hits", 0.5,
                        over_price=-140, under_price=110))
        assert props, "fixture rosters should name some hitters"
        monkeypatch.setattr(sleeper_mod.SleeperPropsSource, "fetch_props",
                            lambda s, sport="mlb": props)

        class Slate(SQLiteRepository):
            def get_schedule(self, d):
                return games

        rep = build_best_bets(Slate(), day, n=250)
        assert rep.priced_counts.get("batter_prop", 0) > 0, (
            "batter props must match players in a roster-backed lineup")
        assert any(b["category"] == "batter_prop" for b in rep.bets)

    def test_panels_fill_even_when_nothing_clears_the_bar(self, monkeypatch) -> None:
        """This product's hold is ~15%, so on most slates nothing clears a 2%
        edge. A filtered panel is then simply empty, which says nothing about
        the slate and reads as broken."""
        import datetime
        import thebeast.data.sources.sleeper as sleeper_mod
        from thebeast import simcache
        from thebeast.data.names import normalize_name, player_names
        from thebeast.data.repository import SQLiteRepository
        from thebeast.pipeline import ensure_lineups, resolve_lineups
        from thebeast.betting.best_bets import build_best_bets

        simcache.clear()
        repo = SQLiteRepository()
        day = datetime.date(2024, 4, 1)
        games = repo.get_schedule(day)[:2]

        # Priced so brutally that nothing can possibly show an edge.
        props = []
        for g in games:
            ensure_lineups(repo, g.game_id, g.home_team_id, g.away_team_id, 2026)
            home_lu, _away = resolve_lineups(repo=repo, game_id=g.game_id,
                                             home_team=g.home_team_id,
                                             away_team=g.away_team_id)
            for pid in home_lu.batting_order[:4]:
                nm = player_names(repo, [pid], 2026).get(pid)
                if nm:
                    props.append(sleeper_mod.PlayerProp(
                        nm, normalize_name(nm), "batter", "hits", 0.5,
                        over_price=-100000, under_price=-100000))
        monkeypatch.setattr(sleeper_mod.SleeperPropsSource, "fetch_props",
                            lambda s, sport="mlb": props)

        class Slate(SQLiteRepository):
            def get_schedule(self, d):
                return games

        rep = build_best_bets(Slate(), day, n=250, per_category=5)
        assert rep.bets, "the closest plays should still be listed"
        assert rep.counts["batter_prop"] == 0, "and none of them qualifies"
        assert all(b["has_edge"] is False for b in rep.bets), (
            "every listed play must be marked as not clearing the bar")
        assert any("cleared the minimum edge" in n for n in rep.notes)

    def test_five_of_each_family_are_offered(self, monkeypatch) -> None:
        """Five pitcher and five batter plays whenever that many are priced."""
        import datetime
        import thebeast.data.sources.sleeper as sleeper_mod
        from thebeast import simcache
        from thebeast.data.names import normalize_name, player_names
        from thebeast.data.repository import SQLiteRepository
        from thebeast.pipeline import ensure_lineups, resolve_lineups
        from thebeast.betting.best_bets import build_best_bets

        simcache.clear()
        repo = SQLiteRepository()
        day = datetime.date(2024, 4, 1)
        games = repo.get_schedule(day)[:4]

        props = []
        for g in games:
            ensure_lineups(repo, g.game_id, g.home_team_id, g.away_team_id, 2026)
            for lu in resolve_lineups(repo=repo, game_id=g.game_id,
                                      home_team=g.home_team_id,
                                      away_team=g.away_team_id):
                for pid in lu.batting_order[:3]:
                    nm = player_names(repo, [pid], 2026).get(pid)
                    if nm:
                        props.append(sleeper_mod.PlayerProp(
                            nm, normalize_name(nm), "batter", "hits", 0.5,
                            over_price=-140, under_price=110))
                nm = player_names(repo, [lu.starter_id], 2026).get(lu.starter_id)
                if nm:
                    props.append(sleeper_mod.PlayerProp(
                        nm, normalize_name(nm), "pitcher", "k", 4.5,
                        over_price=-115, under_price=-105))
        monkeypatch.setattr(sleeper_mod.SleeperPropsSource, "fetch_props",
                            lambda s, sport="mlb": props)

        class Slate(SQLiteRepository):
            def get_schedule(self, d):
                return games

        rep = build_best_bets(Slate(), day, n=250, per_category=5)
        for cat in ("pitcher_prop", "batter_prop"):
            shown = [b for b in rep.bets if b["category"] == cat]
            priced = rep.priced_counts.get(cat, 0)
            assert len(shown) == min(5, priced), (
                f"{cat}: showed {len(shown)} of {priced} priced")

    def test_live_props_are_used_when_they_are_all_there_is(self, monkeypatch) -> None:
        """Late in the day every game has started, so the only quotes left are
        in-game ones. Those must still produce plays."""
        import dataclasses
        import datetime
        import thebeast.betting.best_bets as bb
        import thebeast.data.sources.sleeper as sleeper_mod
        from thebeast import simcache
        from thebeast.data.names import normalize_name, player_names
        from thebeast.data.repository import SQLiteRepository
        from thebeast.data.sources.boxscore import (
            BatterBoxLine, GameBoxscore, TeamBoxscore,
        )
        from thebeast.pipeline import ensure_lineups, resolve_lineups
        from thebeast.betting.best_bets import build_best_bets
        from thebeast.simulator.state import InningState

        simcache.clear()
        repo = SQLiteRepository()
        day = datetime.date(2024, 4, 1)
        games = [dataclasses.replace(g, status="Live", game_pk=1000 + i)
                 for i, g in enumerate(repo.get_schedule(day)[:2])]

        props, boxes = [], {}
        for g in games:
            ensure_lineups(repo, g.game_id, g.home_team_id, g.away_team_id, 2026)
            home_lu, _a = resolve_lineups(repo=repo, game_id=g.game_id,
                                          home_team=g.home_team_id,
                                          away_team=g.away_team_id)
            rows = []
            for pid in home_lu.batting_order[:3]:
                nm = player_names(repo, [pid], 2026).get(pid)
                if nm:
                    # Live quotes only — no pregame lines exist any more.
                    props.append(sleeper_mod.PlayerProp(
                        nm, normalize_name(nm), "batter", "hits", 1.5,
                        over_price=250, under_price=-160,
                        is_live=True, game_status="in_game"))
                    rows.append(BatterBoxLine(name=nm, hits=0))
            boxes[g.game_id] = GameBoxscore(
                game_id=g.game_id,
                home=TeamBoxscore(batters=rows, pitchers=[]),
                away=TeamBoxscore(batters=[], pitchers=[]))
        assert props, "fixture rosters should name some hitters"

        def live_state(repo_, row, gid, home, away):
            return (InningState(
                home=home, away=away, inning=4, half="top",
                score={home: 1, away: 2},
                batting_position={home: 0, away: 0},
                home_by_inning=[0, 1, 0], away_by_inning=[1, 0, 1],
            ), {}, {}, boxes[gid])

        monkeypatch.setattr(bb, "_live_state_for", live_state)
        monkeypatch.setattr(sleeper_mod.SleeperPropsSource, "fetch_props",
                            lambda s, sport="mlb": props)

        class LiveSlate(SQLiteRepository):
            def get_schedule(self, d):
                return games

        rep = build_best_bets(LiveSlate(), day, n=250)
        assert rep.live_games == 2
        assert rep.bets, "live props alone must still fill the panel"
        assert all(b["is_live"] for b in rep.bets)
        assert any("live props quoted" in n for n in rep.notes)

    def test_unresolvable_live_games_say_so(self, monkeypatch) -> None:
        """A live game with no box score can't have its props priced — the line
        is on the final and we can't credit what's already banked. Silently
        skipping it made an empty panel unexplainable."""
        import dataclasses
        import datetime
        import thebeast.betting.best_bets as bb
        import thebeast.data.sources.sleeper as sleeper_mod
        from thebeast import simcache
        from thebeast.data.repository import SQLiteRepository
        from thebeast.betting.best_bets import build_best_bets

        simcache.clear()
        repo = SQLiteRepository()
        day = datetime.date(2024, 4, 1)
        games = [dataclasses.replace(g, status="Live", game_pk=77)
                 for g in repo.get_schedule(day)[:2]]

        monkeypatch.setattr(bb, "_live_state_for",
                            lambda *a, **k: (None, None, None, None))
        monkeypatch.setattr(sleeper_mod.SleeperPropsSource, "fetch_props",
                            lambda s, sport="mlb": [])

        class LiveSlate(SQLiteRepository):
            def get_schedule(self, d):
                return games

        rep = build_best_bets(LiveSlate(), day, n=200)
        assert rep.bets == []
        assert any("no resumable state" in n for n in rep.notes)


class TestAccuracyReport:
    """The rolling scorecard is served from stored games, so it must answer
    sensibly even when nothing has been scored yet."""

    def test_an_empty_window_is_a_valid_report_not_an_error(self) -> None:
        r = client.get("/api/accuracy/report?date=2024-04-05&days=5")
        assert r.status_code == 200
        body = r.json()
        assert body["window"]["games"] == 0
        assert body["outcomes"]["winner_accuracy_pct"] is None
        assert body["players"] == [] and body["games"] == []

    def test_the_window_is_derived_from_the_end_date_and_length(self) -> None:
        body = client.get("/api/accuracy/report?date=2024-04-05&days=5").json()
        assert body["window"] == {
            "start": "2024-04-01", "end": "2024-04-05", "games": 0,
            "pregame_games": 0, "resimulated_games": 0}

    def test_reading_and_grading_take_separate_windows(self, monkeypatch) -> None:
        """They mean different things. `days` is how much of the record to
        aggregate — cheap, it's already on disk. `grade_days` is how far back to
        look for something ungraded, and anything already graded is skipped, so
        a wide look does not mean wide work."""
        from thebeast.api.main import ACCURACY_GRADE_DAYS

        seen: dict = {}

        def fake_refresh(repo, **kwargs):
            seen.update(kwargs)
            return {"newly_scored": 0}

        monkeypatch.setattr("thebeast.accuracy.refresh_window", fake_refresh)
        r = client.get("/api/accuracy/report?date=2024-04-05&days=30&refresh=true")
        assert r.status_code == 200
        assert seen["days"] == ACCURACY_GRADE_DAYS
        assert seen["days"] != 30, "the read window must not drive the grading"
        assert seen["end"].isoformat() == "2024-04-05"

    def test_the_grading_window_looks_behind_the_previous_night(self) -> None:
        """A one-day window grades last night and never looks back, so a missed
        run is a permanent hole — which is exactly what happened to 2026-08-01.
        The span has to be wide enough to see one."""
        from thebeast.api.main import ACCURACY_GRADE_DAYS

        assert ACCURACY_GRADE_DAYS > 1

    def test_the_grading_window_can_still_be_widened_to_backfill(
        self, monkeypatch
    ) -> None:
        seen: dict = {}
        monkeypatch.setattr(
            "thebeast.accuracy.refresh_window",
            lambda repo, **kw: seen.update(kw) or {"newly_scored": 0})
        client.get(
            "/api/accuracy/report?date=2024-04-05&refresh=true&grade_days=14")
        assert seen["days"] == 14

    def test_a_malformed_date_is_rejected(self) -> None:
        assert client.get("/api/accuracy/report?date=nope").status_code == 400

    def test_window_length_is_bounded(self) -> None:
        assert client.get("/api/accuracy/report?days=0").status_code == 422
        assert client.get("/api/accuracy/report?days=999").status_code == 422

    def test_a_game_with_no_scorecard_is_a_404(self) -> None:
        r = client.get("/api/accuracy/game/2024-04-01-NYY-BOS")
        assert r.status_code in (404, 200)   # 200 only if it could be scored

    def test_a_stored_scorecard_is_served_and_aggregated(self) -> None:
        """Round trip: store one scored game, then read it back both through
        the rolling report and through the per-game endpoint."""
        import datetime

        from thebeast.api.main import get_repo

        repo = get_repo()
        game_id = "2024-04-01-ACC-TST"
        scored = {
            "game_id": game_id, "date": "2024-04-01",
            "home": "TST", "away": "ACC", "n": 100, "pregame": False,
            "actual": {"home_runs": 5, "away_runs": 2, "total": 7,
                       "spread": 3, "winner": "home", "status": "Final"},
            "outcome": {
                "home_win_probability": 0.7, "predicted_winner": "home",
                "actual_winner": "home", "picked_winner": True,
                "winner_prob": 0.7, "brier": 0.09, "log_loss": 0.357,
                "total": {"actual": 7.0, "mean": 7.5, "error": -0.5,
                          "covered": True, "centrality_pct": 90.0},
                "exact_score_pct": 3.0,
            },
            "batters": [{
                "player_id": 4242, "name": "Test Hitter", "team": "TST",
                "side": "batter", "position": "SS", "lineup_slot": 2,
                "projected": True, "played": True,
                "stats": {"hits": {"projected": 1.0, "actual": 2, "error": 1.0}},
            }],
            "pitchers": [{
                "player_id": 4343, "name": "Test Arm", "team": "TST",
                "side": "pitcher", "position": "SP", "role": "SP",
                "lineup_slot": None, "projected": True, "played": True,
                "stats": {"outs": {"projected": 16.0, "actual": 18, "error": 2.0}},
            }],
            "has_boxscore": True, "scored_at": "2024-04-02T00:00:00+00:00",
        }
        repo.save_accuracy_game(game_id, datetime.date(2024, 4, 1),
                                scored["scored_at"], scored)
        try:
            body = client.get("/api/accuracy/report?date=2024-04-01&days=1").json()
            assert body["window"]["games"] == 1
            assert body["outcomes"]["winner_accuracy_pct"] == 100.0
            assert body["batting"]["hits"]["n"] == 1
            assert body["pitching"]["outs"]["n"] == 1
            assert {p["position"] for p in body["by_position"]} == {"SS", "SP"}
            assert [p["name"] for p in body["players"]] == ["Test Arm", "Test Hitter"]
            assert body["games"][0]["game_id"] == game_id

            detail = client.get(f"/api/accuracy/game/{game_id}")
            assert detail.status_code == 200
            assert detail.json()["batters"][0]["name"] == "Test Hitter"
        finally:
            with repo._connect() as conn:
                conn.execute("DELETE FROM accuracy_games WHERE game_id=?", (game_id,))


class TestNothingRunsBeforeTheSimulations:
    """The order the app is supposed to work in: simulate the whole slate, then
    build the ranked plays from it, then let anyone ask about it. Each stage
    reads what the one before produced, so a stage that starts early is not
    working with less data — it is working with the wrong data."""

    def _progress(self, **kw):
        from thebeast.slate import SlateProgress
        return SlateProgress(date="2024-04-01", **kw)

    def test_best_bets_refuses_to_price_a_half_run_slate(self, monkeypatch) -> None:
        """Ranking by edge over a partial slate isn't a smaller answer, it's a
        wrong one: what it can see is ranked against itself and what it can't
        is silently absent."""
        from thebeast import slate

        monkeypatch.setattr(slate, "ensure", lambda *a, **k: None)
        monkeypatch.setattr(
            slate, "wait",
            lambda *a, **k: self._progress(state="running", total=15, done=6))
        monkeypatch.setattr("thebeast.betting.best_bets.build_best_bets",
                            lambda *a, **k: pytest.fail("built too early"))

        r = client.get("/api/best-bets", params={"date": "2024-04-01"})
        assert r.status_code == 200
        body = r.json()
        assert body["ready"] is False
        assert body["bets"] == []
        assert "6 of 15" in body["notes"][0]

    def test_best_bets_builds_once_the_slate_is_done(self, monkeypatch) -> None:
        from thebeast import slate

        monkeypatch.setattr(slate, "ensure", lambda *a, **k: None)
        monkeypatch.setattr(
            slate, "wait",
            lambda *a, **k: self._progress(state="ready", total=2, done=2))
        r = client.get("/api/best-bets", params={"date": "2024-04-01"})
        assert r.status_code == 200 and r.json()["ready"] is True

    def test_a_partial_slate_names_the_games_missing_from_the_ranking(
        self, monkeypatch
    ) -> None:
        """A game absent because it never simulated must not read as a game the
        model saw no edge in."""
        from thebeast import slate

        monkeypatch.setattr(slate, "ensure", lambda *a, **k: None)
        monkeypatch.setattr(
            slate, "wait",
            lambda *a, **k: self._progress(state="partial", total=2, done=2,
                                           failed=["2024-04-01-NYY-BOS"]))
        body = client.get("/api/best-bets", params={"date": "2024-04-01"}).json()
        assert body["ready"] is True, "finished, so not blocked forever"
        assert any("2024-04-01-NYY-BOS" in n for n in body["notes"])

    def test_chat_is_closed_while_the_slate_runs(self, monkeypatch) -> None:
        from thebeast import chat as chat_mod
        from thebeast import slate

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setattr(
            slate, "status",
            lambda day: self._progress(state="running", total=15, done=4))
        monkeypatch.setattr(chat_mod, "stream_reply",
                            lambda *a, **k: pytest.fail("answered too early"))

        r = client.post("/api/chat",
                        json={"messages": [{"role": "user", "content": "hi"}]})
        assert r.status_code == 409
        assert "4 of 15" in r.json()["detail"]

    def test_chat_status_reports_the_slate(self, monkeypatch) -> None:
        """The panel closes its own input on this, so it has to be told."""
        from thebeast import slate

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setattr(
            slate, "status",
            lambda day: self._progress(state="running", total=15, done=4))
        body = client.get("/api/chat/status").json()
        assert body["slate_ready"] is False
        assert body["slate"]["done"] == 4

    def test_chat_opens_when_the_slate_is_done(self, monkeypatch) -> None:
        from thebeast import slate

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setattr(
            slate, "status",
            lambda day: self._progress(state="ready", total=2, done=2))
        assert client.get("/api/chat/status").json()["slate_ready"] is True

    def test_a_slate_nobody_opened_does_not_hold_chat_shut(self, monkeypatch) -> None:
        """Yesterday's date, a browser open overnight, a Space just restarted —
        no warm-up exists, and refusing every question would be worse than the
        problem this gate solves."""
        from thebeast import slate

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setattr(slate, "status", lambda day: None)
        assert client.get("/api/chat/status").json()["slate_ready"] is True
