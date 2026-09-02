"""Grading the simulation against what actually happened.

The scoring math is pure — every input is passed in — so none of this needs a
network or a database.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from thebeast import accuracy
from thebeast.accuracy import build_report, ip_to_outs, parse_game_id, score_game
from thebeast.data.models import LineupCard
from thebeast.data.sources.boxscore import (
    BatterBoxLine, GameBoxscore, PitcherBoxLine, TeamBoxscore)


class _Result:
    """Stand-in for GameSimulationResult with just the fields scoring reads."""

    def __init__(self, p_home=0.6, players=None, pitchers=None):
        self.home_win_probability = p_home
        self.n = 100
        self.player_lines = players or []
        self.pitcher_lines = pitchers or []


class _Raw:
    def __init__(self, home, away):
        self.home_runs = np.array(home)
        self.away_runs = np.array(away)
        self.totals = self.home_runs + self.away_runs


def _batter(pid, team="BOS", **kw):
    line = {"team": team, "player_id": pid, "pa": 4.0, "ab": 3.6, "hits": 1.0,
            "home_runs": 0.2, "rbi": 0.5, "bb": 0.4, "k": 0.9}
    line.update(kw)
    return line


def _pitcher(pid, team="BOS", **kw):
    line = {"team": team, "player_id": pid, "outs": 16.0, "hits_allowed": 5.0,
            "runs_allowed": 2.5, "bb_allowed": 1.5, "k": 5.0, "pitches": 88.0}
    line.update(kw)
    return line


def _lineups(home_starter=201, away_starter=200):
    home = LineupCard(game_id="g", team_id="BOS", batting_order=[110, 111],
                      starter_id=home_starter, bullpen_ids=[301], confirmed=True)
    away = LineupCard(game_id="g", team_id="NYY", batting_order=[100],
                      starter_id=away_starter, bullpen_ids=[300], confirmed=True)
    return home, away


def _box(batters=None, pitchers=None):
    return GameBoxscore(
        game_id="g",
        home=TeamBoxscore(batters=batters or [], pitchers=pitchers or []),
        away=TeamBoxscore(batters=[], pitchers=[]))


def _score(result, raw, actual, home_lineup=None, away_lineup=None):
    hl, al = _lineups()
    return score_game(
        game_id="2026-06-28-NYY-BOS", game_date=date(2026, 6, 28),
        home="BOS", away="NYY", result=result, raw=raw,
        home_lineup=home_lineup or hl, away_lineup=away_lineup or al,
        actual=actual)


class TestGameIdAndInnings:
    def test_parses_a_game_id(self):
        assert parse_game_id("2026-06-28-NYY-BOS") == (date(2026, 6, 28), "BOS", "NYY")

    def test_parses_a_doubleheader_suffix(self):
        assert parse_game_id("2026-06-28-NYY-BOS-g2")[1] == "BOS"

    def test_rejects_a_malformed_id(self):
        assert parse_game_id("nonsense") == (None, None, None)

    @pytest.mark.parametrize("ip,outs", [("6.2", 20), ("5.0", 15), ("0.1", 1),
                                         (None, None), ("", 0)])
    def test_innings_pitched_converts_to_outs(self, ip, outs):
        assert ip_to_outs(ip) == outs


class TestOutcomeScoring:
    def test_a_correct_pick_is_recorded_with_its_confidence(self):
        s = _score(_Result(p_home=0.7), _Raw([5, 6, 4], [2, 3, 1]),
                   {"home_runs": 5, "away_runs": 2, "status": "Final",
                    "boxscore": None})
        o = s["outcome"]
        assert o["picked_winner"] is True
        assert o["winner_prob"] == 0.7
        assert o["brier"] == pytest.approx(0.09)

    def test_a_tie_is_neither_a_hit_nor_a_miss(self):
        """Scoring a tie as a miss would penalise the model for an outcome it
        was never asked to predict."""
        s = _score(_Result(p_home=0.7), _Raw([3], [3]),
                   {"home_runs": 3, "away_runs": 3, "status": "Final",
                    "boxscore": None})
        assert s["outcome"]["picked_winner"] is None

    def test_coverage_reports_whether_reality_fell_inside_the_range(self):
        # Simulated totals cluster near 8; a 20-run game is outside any p10-p90.
        s = _score(_Result(), _Raw([4, 4, 5, 4, 4], [4, 3, 4, 4, 4]),
                   {"home_runs": 14, "away_runs": 6, "status": "Final",
                    "boxscore": None})
        assert s["outcome"]["total"]["covered"] is False
        assert s["outcome"]["total"]["error"] > 0   # reality above the mean


class TestPlayerScoring:
    def test_a_projected_hitter_is_graded_against_his_real_line(self):
        s = _score(
            _Result(players=[_batter(110, hits=1.2, home_runs=0.3)]),
            _Raw([5], [2]),
            {"home_runs": 5, "away_runs": 2, "status": "Final",
             "boxscore": _box(batters=[BatterBoxLine(
                 name="Devers", player_id=110, position="3B",
                 plate_appearances=4, at_bats=4, hits=2, home_runs=1,
                 rbi=3, walks=0, strikeouts=1)])})
        row = next(b for b in s["batters"] if b["player_id"] == 110)
        assert row["position"] == "3B"
        assert row["projected"] and row["played"]
        assert row["stats"]["hits"]["actual"] == 2
        assert row["stats"]["hits"]["error"] == pytest.approx(0.8)

    def test_an_unprojected_pinch_hitter_is_kept_and_flagged(self):
        """Dropping him would grade the model only on players it happened to
        forecast, which quietly removes a real source of error."""
        s = _score(
            _Result(players=[_batter(110)]), _Raw([5], [2]),
            {"home_runs": 5, "away_runs": 2, "status": "Final",
             "boxscore": _box(batters=[BatterBoxLine(
                 name="Sub", player_id=999, position="PH",
                 plate_appearances=1, at_bats=1, hits=1, home_runs=0,
                 rbi=1, walks=0, strikeouts=0)])})
        row = next(b for b in s["batters"] if b["player_id"] == 999)
        assert row["projected"] is False and row["played"] is True
        assert row["stats"]["hits"]["projected"] is None

    def test_a_projected_hitter_who_never_played_is_kept_and_flagged(self):
        s = _score(_Result(players=[_batter(110)]), _Raw([5], [2]),
                   {"home_runs": 5, "away_runs": 2, "status": "Final",
                    "boxscore": _box(batters=[])})
        row = next(b for b in s["batters"] if b["player_id"] == 110)
        assert row["projected"] is True and row["played"] is False


class TestPitcherScoring:
    def test_the_start_is_graded_individually(self):
        s = _score(
            _Result(pitchers=[_pitcher(201, outs=16.0, k=5.0)]), _Raw([5], [2]),
            {"home_runs": 5, "away_runs": 2, "status": "Final",
             "boxscore": _box(pitchers=[PitcherBoxLine(
                 name="Bello", player_id=201, innings_pitched="5.2",
                 pitches=95, hits_allowed=6, earned_runs=3,
                 walks_allowed=2, strikeouts=4)])})
        sp = next(p for p in s["pitchers"] if p["role"] == "SP")
        assert sp["stats"]["outs"]["actual"] == 17
        assert sp["stats"]["k"]["actual"] == 4
        # Runs are graded against earned runs — the sim has no fielding errors.
        assert sp["stats"]["runs_allowed"]["actual"] == 3

    def test_relief_is_graded_as_one_aggregate_line(self):
        """The sim's bullpen is a single synthetic arm, so matching it against
        named relievers would score a claim it never made."""
        s = _score(
            _Result(pitchers=[_pitcher(201), _pitcher(-1, outs=11.0, k=3.0)]),
            _Raw([5], [2]),
            {"home_runs": 5, "away_runs": 2, "status": "Final",
             "boxscore": _box(pitchers=[
                 PitcherBoxLine(name="Bello", player_id=201,
                                innings_pitched="5.2", pitches=95,
                                hits_allowed=6, earned_runs=3,
                                walks_allowed=2, strikeouts=4),
                 PitcherBoxLine(name="Arm A", player_id=301,
                                innings_pitched="2.0", pitches=30,
                                hits_allowed=1, earned_runs=0,
                                walks_allowed=1, strikeouts=2),
                 PitcherBoxLine(name="Arm B", player_id=302,
                                innings_pitched="1.1", pitches=18,
                                hits_allowed=0, earned_runs=0,
                                walks_allowed=0, strikeouts=1)])})
        pen = next(p for p in s["pitchers"] if p["role"] == "RP")
        assert pen["aggregate"] is True
        assert pen["arms_used"] == 2
        assert pen["stats"]["outs"]["actual"] == 10        # 6 + 4
        assert pen["stats"]["k"]["actual"] == 3            # 2 + 1

    def test_a_late_starter_change_is_not_graded_as_the_same_pitcher(self):
        """Forecasting one starter and grading it against a different one
        measures nothing about the model."""
        s = _score(
            _Result(pitchers=[_pitcher(201)]), _Raw([5], [2]),
            {"home_runs": 5, "away_runs": 2, "status": "Final",
             "boxscore": _box(pitchers=[PitcherBoxLine(
                 name="Someone Else", player_id=777, innings_pitched="5.0",
                 pitches=80, hits_allowed=4, earned_runs=2,
                 walks_allowed=1, strikeouts=6)])})
        sp = next(p for p in s["pitchers"] if p["role"] == "SP")
        assert sp["starter_changed"] is True
        assert sp["stats"]["outs"]["actual"] is None


class TestReport:
    def _two_games(self):
        made = []
        for i, (hr, ar) in enumerate([(5, 2), (1, 4)]):
            made.append(_score(
                _Result(p_home=0.7, players=[_batter(110, hits=1.0)],
                        pitchers=[_pitcher(201)]),
                _Raw([hr, hr, hr], [ar, ar, ar]),
                {"home_runs": hr, "away_runs": ar, "status": "Final",
                 "boxscore": _box(
                     batters=[BatterBoxLine(
                         name="Devers", player_id=110, position="3B",
                         plate_appearances=4, at_bats=4, hits=hr - 3 if hr > 3 else 1,
                         home_runs=0, rbi=1, walks=0, strikeouts=1)],
                     pitchers=[PitcherBoxLine(
                         name="Bello", player_id=201, innings_pitched="5.0",
                         pitches=90, hits_allowed=5, earned_runs=2,
                         walks_allowed=1, strikeouts=5)])}))
        return made

    def test_it_aggregates_outcomes_across_games(self):
        rep = build_report(self._two_games(), start="2026-06-28", end="2026-06-29")
        # One home win predicted at 0.7: right once, wrong once.
        assert rep["outcomes"]["games_scored"] == 2
        assert rep["outcomes"]["winner_accuracy_pct"] == 50.0
        assert rep["window"]["games"] == 2

    def test_it_groups_by_position_and_by_player(self):
        rep = build_report(self._two_games(), start="2026-06-28", end="2026-06-29")
        positions = {p["position"] for p in rep["by_position"]}
        assert {"3B", "SP"} <= positions
        devers = next(p for p in rep["players"] if p["player_id"] == 110)
        assert devers["games"] == 2
        assert devers["stats"]["hits"]["n"] == 2

    def test_bias_keeps_its_sign(self):
        """An unbiased model that misses by one in both directions and one that
        is always short must not report the same number."""
        rep = build_report(self._two_games(), start="2026-06-28", end="2026-06-29")
        assert "bias" in rep["batting"]["hits"]

    def test_an_empty_window_is_a_valid_empty_report(self):
        rep = build_report([], start="2026-06-28", end="2026-07-02")
        assert rep["window"]["games"] == 0
        assert rep["outcomes"]["winner_accuracy_pct"] is None
        assert rep["players"] == []

    def test_accuracy_percent_is_not_inflated_by_rare_stats(self):
        """Home runs happen a fraction of a game, so scaling the miss against
        the actual total would divide by ~0 and print nonsense."""
        rep = build_report(self._two_games(), start="2026-06-28", end="2026-06-29")
        hr = rep["batting"]["home_runs"]
        assert 0.0 <= hr["accuracy_pct"] <= 100.0


class TestTheDurableRecord:
    """The database is a cache — the container's filesystem is rebuilt from the
    image on every deploy and `data/` is copied in wholesale, so anything the
    running app writes is erased by the next push. The committed JSONL is the
    record, and these pin the properties that makes it safe to rely on."""

    def _repo(self, tmp_path, name="t.db"):
        from thebeast.data.repository import SQLiteRepository
        return SQLiteRepository(str(tmp_path / name))

    def _store(self, repo, n=2):
        made = TestReport()._two_games()[:n]
        for i, s in enumerate(made):
            s["game_id"] = f"2026-07-2{5 + i}-NYY-BOS"
            s["date"] = f"2026-07-2{5 + i}"
            repo.save_accuracy_game(s["game_id"], date(2026, 7, 25 + i),
                                    s["scored_at"], s)
        return made

    def test_a_round_trip_preserves_the_report(self, tmp_path):
        src = self._repo(tmp_path, "a.db")
        self._store(src)
        path = tmp_path / "scored.jsonl"
        assert accuracy.export_scored(src, path) == 2

        dst = self._repo(tmp_path, "b.db")
        assert accuracy.import_scored(dst, path) == 2
        rep = accuracy.load_report(dst, end=date(2026, 7, 26), days=5)
        assert rep["window"]["games"] == 2

    def test_importing_twice_adds_nothing(self, tmp_path):
        """The app loads the record at startup and the job loads it before
        scoring; neither may duplicate or overwrite."""
        src = self._repo(tmp_path, "a.db")
        self._store(src)
        path = tmp_path / "scored.jsonl"
        accuracy.export_scored(src, path)
        dst = self._repo(tmp_path, "b.db")
        assert accuracy.import_scored(dst, path) == 2
        assert accuracy.import_scored(dst, path) == 0

    def test_export_is_byte_stable(self, tmp_path):
        """A rerun that grades nothing new must produce no diff, or the job
        commits noise every five days."""
        src = self._repo(tmp_path, "a.db")
        self._store(src)
        one, two = tmp_path / "1.jsonl", tmp_path / "2.jsonl"
        accuracy.export_scored(src, one)
        dst = self._repo(tmp_path, "b.db")
        accuracy.import_scored(dst, one)
        accuracy.export_scored(dst, two)
        assert one.read_text() == two.read_text()

    def test_a_missing_record_is_not_an_error(self, tmp_path):
        """First run, before the job has ever written one."""
        repo = self._repo(tmp_path)
        assert accuracy.import_scored(repo, tmp_path / "absent.jsonl") == 0

    def test_a_corrupt_line_is_skipped_not_fatal(self, tmp_path):
        """A broken record should cost the report, not stop the app booting."""
        repo = self._repo(tmp_path)
        path = tmp_path / "scored.jsonl"
        good = TestReport()._two_games()[0]
        good["game_id"], good["date"] = "2026-07-25-NYY-BOS", "2026-07-25"
        import json
        path.write_text("not json\n"
                        '{"game_id":"x"}\n'          # no date
                        + json.dumps(good) + "\n")
        assert accuracy.import_scored(repo, path) == 1

    def test_an_existing_game_is_not_overwritten(self, tmp_path):
        """A container that scored something itself must not lose it to an
        older line in the record."""
        repo = self._repo(tmp_path)
        mine = TestReport()._two_games()[0]
        mine["game_id"], mine["date"] = "2026-07-25-NYY-BOS", "2026-07-25"
        mine["n"] = 999999
        repo.save_accuracy_game(mine["game_id"], date(2026, 7, 25), "now", mine)

        import json
        stale = dict(mine, n=1)
        path = tmp_path / "scored.jsonl"
        path.write_text(json.dumps(stale) + "\n")
        assert accuracy.import_scored(repo, path) == 0
        assert repo.get_accuracy_game("2026-07-25-NYY-BOS")["n"] == 999999


class TestNightlyLookback:
    """A nightly run grades the previous day. It has to *look* further than that.

    Games already in the record are skipped by id, so the window is a search
    span rather than an amount of work — widening it costs a schedule fetch per
    day and no simulations. That distinction is the whole point: a one-day
    window grades last night and never looks behind it, so a missed run becomes
    a permanent hole. That is not hypothetical. The first nightly run under a
    one-day window graded 2026-08-02 and stepped straight over 2026-08-01,
    which had nothing, and nothing would ever have gone back for it.
    """

    def _repo(self, tmp_path):
        from thebeast.data.repository import SQLiteRepository
        return SQLiteRepository(str(tmp_path / "t.db"))

    def _grade(self, repo, day: date):
        s = TestReport()._two_games()[0]
        s["game_id"] = f"{day.isoformat()}-NYY-BOS"
        s["date"] = day.isoformat()
        repo.save_accuracy_game(s["game_id"], day, s["scored_at"], s)

    def test_an_empty_record_has_no_latest_date(self, tmp_path):
        assert self._repo(tmp_path).latest_accuracy_date() is None

    def test_it_reports_the_newest_graded_day(self, tmp_path):
        repo = self._repo(tmp_path)
        for d in (date(2026, 7, 28), date(2026, 7, 31), date(2026, 7, 30)):
            self._grade(repo, d)
        assert repo.latest_accuracy_date() == date(2026, 7, 31)

    def test_the_default_window_reaches_behind_the_newest_graded_day(self):
        """The bug in one line. The record's newest day was 08-02 while 08-01
        was empty, so any window measured forward from the newest day could
        never see the hole."""
        from thebeast.api.main import ACCURACY_GRADE_DAYS

        end, hole = date(2026, 8, 3), date(2026, 8, 1)
        start = end - timedelta(days=ACCURACY_GRADE_DAYS - 1)
        assert start <= hole <= end

    def test_an_interior_hole_is_offered_for_grading(self, tmp_path):
        """Days either side already graded, one day in the middle not. The
        ungraded day must be the one — and the only one — that comes back."""
        repo = self._repo(tmp_path)
        for d in (date(2026, 7, 31), date(2026, 8, 2)):
            self._grade(repo, d)

        end = date(2026, 8, 2)
        start = end - timedelta(days=7 - 1)
        already = repo.accuracy_game_ids(start, end)
        span = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        ungraded = [d for d in span
                    if f"{d.isoformat()}-NYY-BOS" not in already]

        assert date(2026, 8, 1) in ungraded, "the hole is visible"
        assert date(2026, 7, 31) not in ungraded, "already graded, skipped"
        assert date(2026, 8, 2) not in ungraded, "already graded, skipped"

    def test_a_healthy_record_leaves_only_last_night_to_grade(self, tmp_path):
        """The steady state, and the thing that was actually asked for: a wide
        lookback must not mean wide work."""
        repo = self._repo(tmp_path)
        end = date(2026, 8, 2)
        for i in range(1, 7):
            self._grade(repo, end - timedelta(days=i))

        start = end - timedelta(days=7 - 1)
        already = repo.accuracy_game_ids(start, end)
        span = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        ungraded = [d for d in span
                    if f"{d.isoformat()}-NYY-BOS" not in already]

        assert ungraded == [end], "only the previous day is simulated"


class TestGradingIsReproducible:
    """The record grades what the app showed, or it isn't a record of anything.

    This ran its own n=1500 unseeded simulation while the cards ran n=2000
    seed=7 — a different sample size and a different draw, so a game's grade
    moved by up to half a point between scorings and no two agreed. Measured on
    one game: the card said .4894 and three gradings said .4890, .4957, .4939.
    """

    def test_it_grades_at_the_slate_s_sample_size_and_seed(self, monkeypatch):
        from thebeast.simcache import SLATE_N, SLATE_SEED

        seen: dict = {}

        def capture(game_id, repo, **kwargs):
            seen.update(kwargs)
            raise RuntimeError("stop here — the parameters are the assertion")

        monkeypatch.setattr("thebeast.simcache.simulate_cached", capture)
        monkeypatch.setattr("thebeast.pipeline.ensure_lineups",
                            lambda *a, **k: None)
        monkeypatch.setattr(accuracy, "fetch_actual",
                            lambda repo, gid: {"home_runs": 5, "away_runs": 3,
                                               "status": "Final"})

        class Repo:
            def get_accuracy_game(self, gid):
                return None

        with pytest.raises(RuntimeError):
            accuracy.score_and_store(Repo(), "2026-06-30-CWS-BAL",
                                     season=2026, park_season=2023)
        assert seen["n"] == SLATE_N, "same sample size as the card"
        assert seen["seed"] == SLATE_SEED, "seeded, so a re-score reproduces"

    def test_it_reads_the_shared_cache_rather_than_re_running(self, monkeypatch):
        """Every graded game used to cost a fresh Monte Carlo even when the run
        was already in hand."""
        monkeypatch.setattr("thebeast.pipeline.simulate_matchup",
                            lambda *a, **k: pytest.fail("re-ran instead of reading"))
        monkeypatch.setattr("thebeast.simcache.simulate_cached",
                            lambda *a, **k: (_ for _ in ()).throw(
                                RuntimeError("reached the cache")))
        monkeypatch.setattr("thebeast.pipeline.ensure_lineups", lambda *a, **k: None)
        monkeypatch.setattr(accuracy, "fetch_actual",
                            lambda repo, gid: {"home_runs": 5, "away_runs": 3,
                                               "status": "Final"})

        class Repo:
            def get_accuracy_game(self, gid):
                return None

        with pytest.raises(RuntimeError, match="reached the cache"):
            accuracy.score_and_store(Repo(), "2026-06-30-CWS-BAL",
                                     season=2026, park_season=2023)

    def test_new_rows_carry_the_grading_method(self):
        """Rows without it were scored the old way and aren't comparable. They
        are left alone: a graded record is a log of what was claimed and when,
        and re-running them now would replay them against today's lineups and
        statlines rather than the ones in force when the game was played."""
        assert accuracy.GRADING_METHOD >= 2
