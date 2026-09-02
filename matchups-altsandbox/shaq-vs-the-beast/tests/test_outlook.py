"""The forward-looking read, and the rules that stop it inventing things.

This is the only part of the app that points at the future, so nearly all of
these are about restraint rather than capability. The dangerous failure isn't a
missing insight — it's a confident one drawn from forty games of noise, which
looks exactly like a real finding to anyone reading the box.

Two tests have to pass before a finding is used: it must hold across the whole
record, and it must be bigger than what a sample that size produces by chance.
Most of what follows is one or the other of those refusing something.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from thebeast import outlook
from thebeast.data.repository import SQLiteRepository

END = date(2026, 8, 8)


@pytest.fixture
def repo(tmp_path):
    return SQLiteRepository(str(tmp_path / "o.db"))


def game(repo, day, i, *, picked=True, total_error=0.0, covered=True,
         home_prob=0.52, home_won=True):
    """One graded game, shaped like the real scorecards."""
    gid = f"{day.isoformat()}-CWS-BAL-{i}"
    repo.save_accuracy_game(gid, day, "now", {
        "game_id": gid, "date": day.isoformat(), "home": "BAL", "away": "CWS",
        "actual": {"home_runs": 5, "away_runs": 4, "total": 9,
                   "winner": "home" if home_won else "away", "status": "Final"},
        "outcome": {
            "picked_winner": picked,
            "home_win_probability": home_prob,
            "total": {"error": total_error, "covered": covered, "mean": 8.5},
            "spread": {"error": 0.0, "covered": True, "mean": 0.0},
        },
    })


def slate(repo, days, per_day=12, **kw):
    for d in range(days):
        day = END - timedelta(days=d)
        for i in range(per_day):
            game(repo, day, i, **kw)


class TestRefusal:
    """What it declines to say, which is most of its value."""

    def test_an_empty_record_forecasts_nothing(self, repo):
        out = outlook.build(repo, end=END)
        assert out["outlook"] == []
        assert "Too little history" in out["verdict"]

    def test_a_handful_of_games_is_not_a_finding(self, repo):
        """Twenty games can show a twenty-point swing on nothing at all."""
        slate(repo, days=2, per_day=8, covered=False)
        out = outlook.build(repo, end=END)
        assert out["windows"]["lifetime"]["games"] == 16
        assert all(not s["usable"] for s in out["signals"])
        assert "Too little history" in out["verdict"]

    def test_a_bias_inside_the_noise_is_not_used(self, repo):
        """A small average miss on a small sample is an average, not a lean."""
        for d in range(8):
            day = END - timedelta(days=d)
            for i in range(12):
                # Alternating misses: a real spread, no real direction.
                game(repo, day, i, total_error=1.5 if i % 2 else -1.4)
        out = outlook.build(repo, end=END)
        bias = next(s for s in out["signals"] if s["key"] == "total_bias")
        assert not bias["significant"], "±1.5 either way is noise, not a lean"
        assert not any("Leaning" in o["where"] for o in out["outlook"])

    def test_a_lean_that_only_showed_up_lately_is_not_used(self, repo):
        """Five days pointing one way against a record pointing the other is
        five days of noise. Persistence is what separates them."""
        for d in range(20):
            day = END - timedelta(days=d)
            for i in range(12):
                # Recent days run over, the older bulk runs under.
                game(repo, day, i, total_error=3.0 if d < 5 else -2.0)
        out = outlook.build(repo, end=END)
        bias = next(s for s in out["signals"] if s["key"] == "total_bias")
        assert bias["significant"], "the record does lean"
        assert not bias["persistent"], "but the recent window leans the other way"
        assert not bias["usable"]

    def test_it_never_names_a_team(self, repo):
        """There is no path here from a club to a recommendation, and there
        shouldn't be — nothing measured supports one."""
        slate(repo, days=10, covered=False)
        out = outlook.build(repo, end=END)
        text = " ".join(o["where"] + o["detail"] for o in out["outlook"])
        assert "BAL" not in text and "CWS" not in text


class TestFindings:
    def test_a_narrow_range_is_reported_and_explained(self, repo):
        """The band is built to hold 80%. Holding far less is a fact about the
        simulator, and one a reader can act on."""
        for d in range(10):
            day = END - timedelta(days=d)
            for i in range(12):
                game(repo, day, i, covered=(i < 6))     # 50%, well under 80
        out = outlook.build(repo, end=END)
        cov = next(s for s in out["signals"] if s["key"] == "coverage")
        assert cov["usable"] and cov["direction"] == "low"
        assert any("edges of our range" in o["where"] for o in out["outlook"])

    def test_a_persistent_lean_becomes_a_direction(self, repo):
        for d in range(12):
            day = END - timedelta(days=d)
            for i in range(12):
                game(repo, day, i, total_error=2.0 + (0.2 if i % 2 else -0.2))
        out = outlook.build(repo, end=END)
        bias = next(s for s in out["signals"] if s["key"] == "total_bias")
        assert bias["usable"] and bias["direction"] == "over"
        assert any("overs" in o["where"] for o in out["outlook"])

    def test_a_coin_flip_record_says_not_the_moneyline(self, repo):
        """The most useful thing it can say about picks is that they aren't
        worth backing, and that has to survive being unflattering."""
        for d in range(10):
            day = END - timedelta(days=d)
            for i in range(12):
                game(repo, day, i, picked=(i % 2 == 0))
        out = outlook.build(repo, end=END)
        assert any(o["where"] == "Not the moneyline" for o in out["outlook"])

    def test_a_model_with_no_opinions_says_so(self, repo):
        slate(repo, days=10, home_prob=0.51)
        out = outlook.build(repo, end=END)
        flat = next(s for s in out["signals"] if s["key"] == "flatness")
        assert flat["lifetime"] == 100.0
        assert any("actually separate" in o["where"] for o in out["outlook"])


class TestWindows:
    def test_all_three_windows_are_measured(self, repo):
        """The comparison is the request: last night against the stretch it
        belongs to, and both against everything ever graded."""
        slate(repo, days=10)
        w = outlook.build(repo, end=END)["windows"]
        assert w["latest"]["games"] == 12
        assert w["recent"]["games"] == 60
        assert w["lifetime"]["games"] == 120

    def test_the_lifetime_window_starts_at_the_first_graded_game(self, repo):
        slate(repo, days=4)
        life = outlook.build(repo, end=END)["windows"]["lifetime"]
        assert life["start"] == (END - timedelta(days=3)).isoformat()
        assert life["days"] == 4

    def test_windows_end_at_the_last_graded_day_not_today(self, repo):
        """Grading runs overnight and can fall behind. Anchoring to today would
        quietly shorten every window by however long the gap is."""
        slate(repo, days=3)
        out = outlook.build(repo, end=END + timedelta(days=30))
        assert out["windows"]["latest"]["games"] == 12

    def test_the_signed_bias_keeps_its_direction(self, repo):
        """An absolute error says how noisy we are; only the signed one points
        at a side, which is the whole reason it's carried separately."""
        slate(repo, days=6, total_error=-2.0)
        life = outlook.build(repo, end=END)["windows"]["lifetime"]
        assert life["total_bias"] == -2.0
        assert life["total_mae"] == 2.0


class TestHonesty:
    def test_failed_signals_are_kept_not_hidden(self, repo):
        """A forecast that only ever shows its hits is indistinguishable from
        one that makes them up."""
        slate(repo, days=10)
        out = outlook.build(repo, end=END)
        assert any(not s["usable"] for s in out["signals"])
        for s in out["signals"]:
            assert {"significant", "persistent", "usable"} <= set(s)

    def test_a_thin_record_says_it_is_thin(self, repo):
        slate(repo, days=4)
        out = outlook.build(repo, end=END)
        assert any("graded games over" in c for c in out["caveats"])

    def test_a_single_game_day_is_flagged_as_uncomparable(self, repo):
        """One game is not a day. It's shown, but never as a trend."""
        slate(repo, days=6)
        lone = END + timedelta(days=1)
        game(repo, lone, 0)
        out = outlook.build(repo, end=lone)
        assert out["windows"]["latest"]["games"] == 1
        assert any("too few to compare" in c for c in out["caveats"])

    def test_a_stale_record_says_how_stale(self, repo):
        slate(repo, days=6)
        out = outlook.build(repo, end=END)
        assert any("ungraded" in c for c in out["caveats"])

    def test_it_never_claims_to_know_the_books(self, repo):
        slate(repo, days=10, covered=False)
        out = outlook.build(repo, end=END)
        assert any("not the books'" in c for c in out["caveats"])

    def test_nothing_usable_is_reported_as_a_result(self, repo):
        """"We looked and found nothing" is a finding, and reads very
        differently from a box that simply came up empty."""
        for d in range(10):
            day = END - timedelta(days=d)
            for i in range(12):
                game(repo, day, i, picked=(i % 2 == 0),
                     covered=(i < 10), total_error=0.5 if i % 2 else -0.5,
                     home_prob=0.30 if i % 3 else 0.70)
        out = outlook.build(repo, end=END)
        if not any(s["usable"] for s in out["signals"]):
            assert "clears the noise" in out["verdict"]
