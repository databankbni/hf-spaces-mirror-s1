"""Grading the market: did the books or the people betting into them win.

The framing these tests defend is the one thing that makes the answer
meaningful. A sportsbook with balanced money wins the vig whoever wins the
game, so "did the books lose?" is never "did the favourite lose?" — favourites
and underdogs are equally capable of being the side the money is on. It is:

    which side did the money go to, and did that side win?

Line movement answers the first half by observation — books shade a price to
attract the other side, so the direction of the move is the direction of the
imbalance. The final score answers the second. Neither half needs a claim about
what bettors like in general.

What none of this can see is scale. Handle is paid data, so a game where a
million moved counts the same as one where ten thousand did. That makes it a
tally of games, and the tests below insist it keeps saying so.
"""
from __future__ import annotations

from datetime import date

import pytest

from thebeast import market
from thebeast.data.repository import SQLiteRepository

DAY = date(2026, 8, 8)


@pytest.fixture
def repo(tmp_path):
    return SQLiteRepository(str(tmp_path / "m.db"))


def line(home_ml=None, away_ml=None, total=None, over_price=-110,
         under_price=-110, book="consensus"):
    return {"home_ml": home_ml, "away_ml": away_ml, "total": total,
            "over_price": over_price, "under_price": under_price, "book": book}


def store(repo, gid, when, **kw):
    return repo.save_odds_snapshot(gid, DAY, when, line(**kw))


def finalise(repo, gid, home, away, home_runs, away_runs):
    repo.save_accuracy_game(gid, DAY, "now", {
        "game_id": gid, "home": home, "away": away,
        "actual": {"home_runs": home_runs, "away_runs": away_runs,
                   "status": "Final"}})


def moved(repo, gid, *, opened, closed):
    """A game whose line went from `opened` to `closed`."""
    store(repo, gid, "T1", **opened)
    store(repo, gid, "T2", **closed)


class TestPrices:
    def test_a_favourite_pays_less_than_the_stake(self):
        assert market.payout(-200) == pytest.approx(0.5)

    def test_an_underdog_pays_more(self):
        assert market.payout(150) == pytest.approx(1.5)

    def test_a_missing_price_is_not_a_zero(self):
        assert market.payout(None) is None
        assert market.payout(0) is None

    def test_implied_probability_includes_the_vig(self):
        assert market.implied(-200) == pytest.approx(2 / 3, abs=1e-6)
        assert market.implied(100) == pytest.approx(0.5)


class TestHold:
    """The book's edge on a balanced game — the reason "who won" is not "who
    picked the winner"."""

    def test_a_two_way_market_prices_in_more_than_certainty(self):
        # -130/+110 implies 56.5% + 47.6% = 104.1%; the 4.1% excess is the hold.
        assert market.hold_pct(-130, 110) == pytest.approx(3.98, abs=0.02)

    def test_a_standard_pick_em_holds_about_five_percent(self):
        assert market.hold_pct(-110, -110) == pytest.approx(4.55, abs=0.02)

    def test_a_missing_side_has_no_hold(self):
        assert market.hold_pct(-110, None) is None


class TestMoneyFlow:
    """Reading the money off the price, which is the whole basis of the answer.

    Nothing here consults who was favoured. A shortening underdog is money on
    the underdog, exactly as a shortening favourite is money on the favourite.
    """

    def test_a_rising_total_means_money_on_the_over(self):
        flow = market.money_flow({"total": 8.5}, {"total": 9.0})
        assert flow["total"] == {"side": "over", "from": 8.5, "to": 9.0}

    def test_a_falling_total_means_money_on_the_under(self):
        assert market.money_flow({"total": 9.0}, {"total": 8.0})["total"]["side"] == "under"

    def test_a_shortening_favourite_is_money_on_the_favourite(self):
        flow = market.money_flow({"home_ml": -130}, {"home_ml": -155})
        assert flow["moneyline"]["side"] == "home"

    def test_a_shortening_underdog_is_money_on_the_underdog(self):
        """The case the old favourite-based reading got backwards: +140 → +115
        is the home dog being bet, not the road favourite."""
        flow = market.money_flow({"home_ml": 140}, {"home_ml": 115})
        assert flow["moneyline"]["side"] == "home"

    def test_a_lengthening_price_is_money_on_the_other_side(self):
        flow = market.money_flow({"home_ml": -150}, {"home_ml": -120})
        assert flow["moneyline"]["side"] == "away"

    def test_a_still_line_reports_no_flow(self):
        assert market.money_flow({"home_ml": -130, "total": 8.5},
                                 {"home_ml": -130, "total": 8.5}) == {}

    def test_a_tick_is_not_money(self):
        """Prices are re-quoted constantly and half-run lines get shaded by a
        cent. Counting that as an imbalance would make every game one-sided."""
        assert market.money_flow({"home_ml": -130, "total": 8.5},
                                 {"home_ml": -133, "total": 8.6}) == {}

    def test_a_half_recorded_market_is_skipped_not_guessed(self):
        assert market.money_flow({"total": None}, {"total": 9.0}) == {}
        assert market.money_flow(None, {"total": 9.0}) == {}


class TestSettlement:
    def test_money_on_a_winner_is_the_public_beating_the_book(self, repo):
        gid = f"{DAY.isoformat()}-CWS-BAL"
        moved(repo, gid, opened={"home_ml": -130, "away_ml": 110, "total": 8.5},
              closed={"home_ml": -155, "away_ml": 130, "total": 9.0})
        finalise(repo, gid, "BAL", "CWS", 6, 4)   # home won, 10 runs is over 9
        m = market.game_market(repo, gid)
        assert m.money_on["moneyline"]["side"] == "home"
        assert m.money_right == {"moneyline": True, "total": True}
        assert m.winner == "public"

    def test_money_on_a_loser_is_the_book_beating_the_public(self, repo):
        gid = f"{DAY.isoformat()}-CWS-BAL"
        moved(repo, gid, opened={"home_ml": -130, "away_ml": 110, "total": 8.5},
              closed={"home_ml": -155, "away_ml": 130, "total": 9.0})
        finalise(repo, gid, "BAL", "CWS", 2, 5)   # home lost, 7 runs is under
        m = market.game_market(repo, gid)
        assert m.money_right == {"moneyline": False, "total": False}
        assert m.winner == "book"

    def test_money_on_a_winning_underdog_still_beats_the_book(self, repo):
        """The correction this module exists for. The home side is a +140 dog,
        the money comes to it, and it wins — the book lost that game even
        though no favourite was involved."""
        gid = f"{DAY.isoformat()}-CWS-BAL"
        moved(repo, gid, opened={"home_ml": 140, "away_ml": -160, "total": 8.5},
              closed={"home_ml": 112, "away_ml": -132, "total": 8.5})
        finalise(repo, gid, "BAL", "CWS", 4, 3)
        m = market.game_market(repo, gid)
        assert m.money_on["moneyline"]["side"] == "home"
        assert m.winner == "public"

    def test_a_line_that_never_moved_is_balanced_not_unknown(self, repo):
        """A still line is a real answer: the book took both sides evenly and
        keeps the hold whoever won. It takes two readings to know that."""
        gid = f"{DAY.isoformat()}-CWS-BAL"
        store(repo, gid, "2026-08-08T18:00:00+00:00",
              home_ml=-155, away_ml=130, total=9.0)
        # Looked again an hour later and it hadn't moved. No new row — that's
        # the dedupe — but the look is what makes "it held" sayable.
        store(repo, gid, "2026-08-08T19:00:00+00:00",
              home_ml=-155, away_ml=130, total=9.0)
        finalise(repo, gid, "BAL", "CWS", 3, 2)
        m = market.game_market(repo, gid)
        assert m.snapshots == 1, "one price, but seen twice"
        assert m.winner == "balanced"
        assert m.money_right == {}
        assert any("never moved" in n for n in m.notes)

    def test_one_price_is_not_a_line_that_never_moved(self, repo):
        """The distinction the backfill makes necessary. A game we only ever
        caught once has a real price and a real hold, and nothing whatever to
        say about where the money went — claiming it 'never moved' would be a
        statement about hours nobody was watching."""
        gid = f"{DAY.isoformat()}-CWS-BAL"
        store(repo, gid, "T1", home_ml=-155, away_ml=130, total=9.0)
        finalise(repo, gid, "BAL", "CWS", 3, 2)
        m = market.game_market(repo, gid)
        assert m.snapshots == 1
        assert m.winner is None, "no verdict from one reading"
        assert m.closed is not None and m.hold_pct is not None, "the price is real"
        assert any("only the closing line" in n for n in m.notes)

    def test_one_price_plus_a_published_split_still_settles(self, repo):
        """Splits don't need history — a single reading says where the money
        is. So a backfilled game with a split gets a verdict and one without
        doesn't, which is exactly the right difference."""
        gid = f"{DAY.isoformat()}-CWS-BAL"
        store(repo, gid, "T1", home_ml=-155, away_ml=130, total=9.0)
        repo.save_splits_snapshot(gid, DAY, "T1", {
            "book": "draftkings", "ml_home_handle": 71.0, "ml_home_bets": 64.0,
            "total_over_handle": None, "total_over_bets": None})
        finalise(repo, gid, "BAL", "CWS", 3, 2)
        m = market.game_market(repo, gid)
        assert m.money_on["moneyline"]["source"] == "handle"
        assert m.winner == "public"

    def test_the_hold_is_reported_whoever_won(self, repo):
        gid = f"{DAY.isoformat()}-CWS-BAL"
        store(repo, gid, "T1", home_ml=-130, away_ml=110, total=8.5)
        assert market.game_market(repo, gid).hold_pct == pytest.approx(3.98, abs=0.02)

    def test_a_total_landing_on_the_line_pushes(self, repo):
        """Common in baseball. Grading a push as a miss would tilt every
        over/under number one way."""
        gid = f"{DAY.isoformat()}-CWS-BAL"
        moved(repo, gid, opened={"home_ml": -150, "away_ml": 130, "total": 8.5},
              closed={"home_ml": -150, "away_ml": 130, "total": 9.0})
        finalise(repo, gid, "BAL", "CWS", 5, 4)   # exactly 9
        m = market.game_market(repo, gid)
        assert "total" not in m.money_right
        assert any("push" in n for n in m.notes)

    def test_a_tied_game_settles_no_moneyline(self, repo):
        gid = f"{DAY.isoformat()}-CWS-BAL"
        moved(repo, gid, opened={"home_ml": -130, "away_ml": 110},
              closed={"home_ml": -160, "away_ml": 140})
        finalise(repo, gid, "BAL", "CWS", 3, 3)
        m = market.game_market(repo, gid)
        assert "moneyline" not in m.money_right
        assert any("tie" in n for n in m.notes)
        assert m.winner == "balanced", "nothing settled, so nobody won it"

    def test_it_settles_against_the_closing_line(self, repo):
        """The last price anyone could take, and the one the money had finished
        moving into."""
        gid = f"{DAY.isoformat()}-CWS-BAL"
        moved(repo, gid, opened={"home_ml": -110, "away_ml": -110, "total": 7.5},
              closed={"home_ml": -110, "away_ml": -110, "total": 9.5})
        finalise(repo, gid, "BAL", "CWS", 5, 4)   # 9: under the close, over the open
        m = market.game_market(repo, gid)
        assert m.money_on["total"]["side"] == "over"
        assert m.money_right["total"] is False

    def test_an_unfinished_game_is_not_settled(self, repo):
        gid = f"{DAY.isoformat()}-CWS-BAL"
        moved(repo, gid, opened={"home_ml": -150, "away_ml": 130, "total": 8.5},
              closed={"home_ml": -180, "away_ml": 155, "total": 8.5})
        m = market.game_market(repo, gid)
        assert m.winner is None and m.money_right == {}
        assert m.money_on["moneyline"]["side"] == "home", "the move is still shown"
        assert m.opened is not None

    def test_a_game_with_no_line_is_empty_not_an_error(self, repo):
        m = market.game_market(repo, f"{DAY.isoformat()}-CWS-BAL")
        assert m.snapshots == 0 and m.winner is None and m.money_on == {}


class TestObservedHandle:
    """Where a book publishes its splits, nothing has to be inferred.

    These are the cases that separate reading the money from deducing it —
    including the one where the two disagree, which is the whole reason to
    prefer the published number.
    """

    def _splits(self, repo, gid, **kw):
        base = {"book": "draftkings", "ml_home_handle": None,
                "ml_home_bets": None, "total_over_handle": None,
                "total_over_bets": None}
        base.update(kw)
        repo.save_splits_snapshot(gid, DAY, "T1", base)

    def test_the_published_share_names_the_side(self, repo):
        gid = f"{DAY.isoformat()}-CWS-BAL"
        store(repo, gid, "T1", home_ml=-130, away_ml=110, total=8.5)
        self._splits(repo, gid, ml_home_handle=71.0, ml_home_bets=64.0)
        m = market.game_market(repo, gid)
        assert m.money_on["moneyline"]["side"] == "home"
        assert m.money_on["moneyline"]["handle_pct"] == 71.0
        assert m.money_on["moneyline"]["source"] == "handle"

    def test_an_away_lean_is_reported_as_the_away_side(self, repo):
        gid = f"{DAY.isoformat()}-CWS-BAL"
        store(repo, gid, "T1", home_ml=-130, away_ml=110, total=8.5)
        self._splits(repo, gid, ml_home_handle=28.0, ml_home_bets=35.0)
        ml = market.game_market(repo, gid).money_on["moneyline"]
        assert ml["side"] == "away" and ml["handle_pct"] == 72.0
        assert ml["bets_pct"] == 65.0, "the ticket share flips with it"

    def test_the_published_share_beats_the_line_move(self, repo):
        """A line can drift for reasons other than money — a pitcher scratch,
        a total re-shaded round a weather forecast. When the book has told us
        where the money is, the deduction doesn't get a vote."""
        gid = f"{DAY.isoformat()}-CWS-BAL"
        moved(repo, gid, opened={"home_ml": -130, "away_ml": 110, "total": 8.5},
              closed={"home_ml": -170, "away_ml": 145, "total": 8.5})
        self._splits(repo, gid, ml_home_handle=22.0, ml_home_bets=30.0)
        ml = market.game_market(repo, gid).money_on["moneyline"]
        assert ml["side"] == "away", "movement said home; the handle says away"
        assert ml["source"] == "handle"

    def test_an_even_split_stops_the_fallback(self, repo):
        """52/48 is a balanced book. Falling back to a line move here would
        take a real finding of 'balanced' and overwrite it with a guess."""
        gid = f"{DAY.isoformat()}-CWS-BAL"
        moved(repo, gid, opened={"home_ml": -130, "away_ml": 110, "total": 8.5},
              closed={"home_ml": -170, "away_ml": 145, "total": 8.5})
        self._splits(repo, gid, ml_home_handle=52.0, ml_home_bets=51.0)
        assert "moneyline" not in market.game_market(repo, gid).money_on

    def test_the_fallback_is_per_market_not_per_game(self, repo):
        """A published moneyline split and no total split should mean one of
        each, not one thrown away."""
        gid = f"{DAY.isoformat()}-CWS-BAL"
        moved(repo, gid, opened={"home_ml": -130, "away_ml": 110, "total": 8.5},
              closed={"home_ml": -130, "away_ml": 110, "total": 9.5})
        self._splits(repo, gid, ml_home_handle=71.0, ml_home_bets=64.0)
        on = market.game_market(repo, gid).money_on
        assert on["moneyline"]["source"] == "handle"
        assert on["total"]["source"] == "movement" and on["total"]["side"] == "over"

    def test_big_money_on_few_tickets_reads_as_sharp(self, repo):
        """The distinction line movement cannot make: both of these push the
        price the same way, and only one is a handful of large bets."""
        gid = f"{DAY.isoformat()}-CWS-BAL"
        store(repo, gid, "T1", home_ml=-130, away_ml=110, total=8.5)
        self._splits(repo, gid, ml_home_handle=68.0, ml_home_bets=31.0)
        assert market.game_market(repo, gid).money_on["moneyline"]["sharp"]

    def test_money_and_tickets_together_is_just_the_crowd(self, repo):
        gid = f"{DAY.isoformat()}-CWS-BAL"
        store(repo, gid, "T1", home_ml=-130, away_ml=110, total=8.5)
        self._splits(repo, gid, ml_home_handle=68.0, ml_home_bets=66.0)
        assert not market.game_market(repo, gid).money_on["moneyline"]["sharp"]

    def test_a_ticket_share_we_never_got_is_not_sharp_by_default(self, repo):
        gid = f"{DAY.isoformat()}-CWS-BAL"
        store(repo, gid, "T1", home_ml=-130, away_ml=110, total=8.5)
        self._splits(repo, gid, ml_home_handle=68.0)
        ml = market.game_market(repo, gid).money_on["moneyline"]
        assert ml["bets_pct"] is None and ml["sharp"] is False

    def test_it_settles_a_published_split_like_any_other(self, repo):
        gid = f"{DAY.isoformat()}-CWS-BAL"
        store(repo, gid, "T1", home_ml=-130, away_ml=110, total=8.5)
        self._splits(repo, gid, ml_home_handle=71.0, ml_home_bets=64.0,
                     total_over_handle=66.0, total_over_bets=60.0)
        finalise(repo, gid, "BAL", "CWS", 6, 4)   # home won, 10 is over 8.5
        m = market.game_market(repo, gid)
        assert m.money_right == {"moneyline": True, "total": True}
        assert m.winner == "public"

    def test_an_evenly_split_game_says_so_rather_than_blaming_the_line(self, repo):
        gid = f"{DAY.isoformat()}-CWS-BAL"
        store(repo, gid, "T1", home_ml=-130, away_ml=110, total=8.5)
        self._splits(repo, gid, ml_home_handle=51.0, total_over_handle=49.0)
        finalise(repo, gid, "BAL", "CWS", 6, 4)
        m = market.game_market(repo, gid)
        assert m.winner == "balanced"
        assert any("near enough even" in n for n in m.notes)

    def test_the_scorecard_says_how_much_was_measured(self, repo):
        """A scorecard built on published splits and one built on inferred
        movement are not the same claim, so the mix is reported."""
        with_splits = f"{DAY.isoformat()}-CWS-BAL"
        store(repo, with_splits, "T1", home_ml=-130, away_ml=110, total=8.5)
        self._splits(repo, with_splits, ml_home_handle=71.0, ml_home_bets=30.0)
        finalise(repo, with_splits, "BAL", "CWS", 6, 4)

        inferred = f"{DAY.isoformat()}-NYM-PHI"
        moved(repo, inferred, opened={"home_ml": -120, "away_ml": 100, "total": 8.5},
              closed={"home_ml": -160, "away_ml": 138, "total": 8.5})
        finalise(repo, inferred, "PHI", "NYM", 2, 5)

        s = market.scorecard(repo, end=DAY, days=1)
        assert s["games_settled"] == 2 and s["games_from_splits"] == 1
        assert "1 of 2 games came from published splits" in s["method"]
        # The sharp side was the one that won, and is graded separately.
        assert s["sharp_side"] == {"right": 1, "wrong": 0}

    def test_a_window_with_no_splits_admits_it(self, repo):
        gid = f"{DAY.isoformat()}-CWS-BAL"
        moved(repo, gid, opened={"home_ml": -120, "away_ml": 100, "total": 8.5},
              closed={"home_ml": -160, "away_ml": 138, "total": 8.5})
        finalise(repo, gid, "BAL", "CWS", 5, 2)
        s = market.scorecard(repo, end=DAY, days=1)
        assert s["games_from_splits"] == 0
        assert "No published splits in this window" in s["method"]

    def test_shares_are_published_and_amounts_are_not(self, repo):
        """Splits shrink the caveat, they don't remove it: a 70/30 on a game
        taking fifty thousand and one taking five million still count alike."""
        s = market.scorecard(repo, end=DAY, days=1)
        assert "counts games, not dollars" in s["method"]
        assert "amounts are not" in s["method"]


class TestSnapshots:
    def test_an_unchanged_line_is_not_stored_twice(self, repo):
        """A slate is polled all evening. Recording every fetch would bury the
        moves that matter in copies of the ones that didn't."""
        gid = f"{DAY.isoformat()}-CWS-BAL"
        assert store(repo, gid, "T1", home_ml=-130, away_ml=110, total=8.5)
        assert not store(repo, gid, "T2", home_ml=-130, away_ml=110, total=8.5)
        assert len(repo.odds_history(gid)) == 1

    def test_looking_again_is_recorded_even_when_nothing_changed(self, repo):
        """The dedupe keeps storage small and would otherwise erase the
        difference between a line that held all evening and one we glanced at
        once. Those support opposite conclusions, so the look is recorded even
        when the price isn't."""
        gid = f"{DAY.isoformat()}-CWS-BAL"
        store(repo, gid, "2026-08-08T18:00:00+00:00",
              home_ml=-130, away_ml=110, total=8.5)
        assert repo.latest_odds(gid)["last_seen"] is None
        store(repo, gid, "2026-08-08T19:00:00+00:00",
              home_ml=-130, away_ml=110, total=8.5)
        assert len(repo.odds_history(gid)) == 1, "still one price"
        assert repo.latest_odds(gid)["last_seen"] == "2026-08-08T19:00:00+00:00"

    def test_history_comes_back_oldest_first(self, repo):
        gid = f"{DAY.isoformat()}-CWS-BAL"
        store(repo, gid, "T2", total=9.0)
        store(repo, gid, "T1", total=8.5)
        assert [r["taken_at"] for r in repo.odds_history(gid)] == ["T1", "T2"]


class TestScorecard:
    def _game(self, repo, gid, *, opened, closed, home_runs, away_runs):
        moved(repo, gid, opened=opened, closed=closed)
        finalise(repo, gid, gid[-3:], "OPP", home_runs, away_runs)

    def test_it_names_the_public_when_the_money_kept_winning(self, repo):
        # Home won all three and every one went over the closing 9.5.
        for i, (hr, ar) in enumerate([(6, 4), (7, 3), (8, 5)]):
            self._game(repo, f"{DAY.isoformat()}-OPP-B{i}A",
                       opened={"home_ml": -120, "away_ml": 100, "total": 8.5},
                       closed={"home_ml": -155, "away_ml": 135, "total": 9.5},
                       home_runs=hr, away_runs=ar)
        s = market.scorecard(repo, end=DAY, days=1)
        assert s["public_won"] == 3 and s["book_won"] == 0
        assert "public won" in s["verdict"]

    def test_it_names_the_books_when_the_money_kept_losing(self, repo):
        for i in range(3):
            self._game(repo, f"{DAY.isoformat()}-OPP-B{i}A",
                       opened={"home_ml": -120, "away_ml": 100, "total": 8.5},
                       closed={"home_ml": -155, "away_ml": 135, "total": 9.5},
                       home_runs=1, away_runs=4)   # home lost, 5 runs is under
        s = market.scorecard(repo, end=DAY, days=1)
        assert s["book_won"] == 3 and s["public_won"] == 0
        assert "books won" in s["verdict"]

    def test_a_favourite_heavy_night_is_not_automatically_a_book_loss(self, repo):
        """The bug the rewrite fixes, stated as a test. Every home side here is
        a solid favourite and every one of them wins — the old reading called
        that a public win by definition. The money went the other way, so it
        wasn't."""
        for i in range(3):
            self._game(repo, f"{DAY.isoformat()}-OPP-B{i}A",
                       opened={"home_ml": -180, "away_ml": 155, "total": 8.5},
                       closed={"home_ml": -150, "away_ml": 130, "total": 8.5},
                       home_runs=5, away_runs=2)   # favourites all held
        s = market.scorecard(repo, end=DAY, days=1)
        assert s["book_won"] == 3, "the money was leaving the side that won"
        assert s["public_won"] == 0

    def test_still_lines_are_counted_as_balanced_not_ignored(self, repo):
        gid = f"{DAY.isoformat()}-CWS-BAL"
        store(repo, gid, "2026-08-08T18:00:00+00:00",
              home_ml=-130, away_ml=110, total=8.5)
        store(repo, gid, "2026-08-08T19:00:00+00:00",   # watched, and it held
              home_ml=-130, away_ml=110, total=8.5)
        finalise(repo, gid, "BAL", "CWS", 5, 4)
        s = market.scorecard(repo, end=DAY, days=1)
        assert s["balanced"] == 1 and s["games_settled"] == 1
        assert "Every line held" in s["verdict"]

    def test_it_tallies_each_market_separately(self, repo):
        self._game(repo, f"{DAY.isoformat()}-OPP-BAL",
                   opened={"home_ml": -120, "away_ml": 100, "total": 8.5},
                   closed={"home_ml": -155, "away_ml": 135, "total": 9.5},
                   home_runs=6, away_runs=1)   # home won; 7 runs is under 9.5
        s = market.scorecard(repo, end=DAY, days=1)
        assert s["money_side"]["moneyline"] == {"right": 1, "wrong": 0}
        assert s["money_side"]["total"] == {"right": 0, "wrong": 1}

    def test_an_unfinished_game_does_not_count(self, repo):
        moved(repo, f"{DAY.isoformat()}-CWS-BAL",
              opened={"home_ml": -120, "away_ml": 100, "total": 8.5},
              closed={"home_ml": -155, "away_ml": 135, "total": 9.5})
        s = market.scorecard(repo, end=DAY, days=1)
        assert s["games_settled"] == 0
        assert "Nothing settled" in s["verdict"]

    def test_an_empty_window_says_so(self, repo):
        s = market.scorecard(repo, end=DAY, days=5)
        assert s["games_settled"] == 0
        assert "Nothing settled" in s["verdict"]

    def test_the_typical_hold_is_reported(self, repo):
        """The number that makes a balanced night a good one for the book, so
        it belongs next to the verdict rather than buried."""
        self._game(repo, f"{DAY.isoformat()}-OPP-BAL",
                   opened={"home_ml": -120, "away_ml": 100, "total": 8.5},
                   closed={"home_ml": -110, "away_ml": -110, "total": 8.5},
                   home_runs=5, away_runs=4)
        assert market.scorecard(repo, end=DAY, days=1)["typical_hold_pct"] == \
            pytest.approx(4.55, abs=0.02)

    def test_it_never_claims_to_have_counted_dollars(self, repo):
        """Direction is observable; size is not. Anything that reads as a P&L
        would be a claim this has no data for."""
        s = market.scorecard(repo, end=DAY, days=1)
        assert "counts games, not dollars" in s["method"]
        assert "moved" in s["method"]


class TestBackfill:
    """Filling in a game the app hadn't got to yet.

    Not one from a past day: the splits page shows tonight's board, and there
    is no going back for a market. A price a game closed at is gone once nobody
    wrote it down, which is the cost of taking everything from one book and
    worth being plain about.
    """

    def _source(self, monkeypatch, splits):
        from thebeast.data.sources import splits as splits_mod

        class Fake:
            def fetch(self, day, game_ids=None):
                return splits
        monkeypatch.setattr(splits_mod, "VSiNSplitsSource", Fake)

    def _split(self, gid, **kw):
        from thebeast.data.sources.splits import GameSplits

        base = dict(ml_home_handle=68.0, ml_home_bets=55.0,
                    ml_home_price=-155, ml_away_price=130, total_line=9.0)
        base.update(kw)
        return GameSplits(gid, "BAL", "CWS", **base)

    def test_it_stores_the_book_price_for_a_game_we_never_watched(self, repo, monkeypatch):
        gid = f"{DAY.isoformat()}-CWS-BAL"
        self._source(monkeypatch, [self._split(gid)])
        assert market.backfill(repo, gid) == 1
        m = market.game_market(repo, gid)
        assert m.closed["home_ml"] == -155 and m.closed["book"] == "draftkings"

    def test_it_stores_the_split_alongside_the_price(self, repo, monkeypatch):
        """Both come off the same page and belong to the same ledger, so a
        backfill that took one and left the other would put the panel back in
        the state this exists to fix."""
        gid = f"{DAY.isoformat()}-CWS-BAL"
        self._source(monkeypatch, [self._split(gid)])
        market.backfill(repo, gid)
        m = market.game_market(repo, gid)
        assert m.splits["ml_home_handle"] == 68.0
        assert m.money_on["moneyline"]["source"] == "handle"

    def test_a_backfilled_game_settles_on_its_split(self, repo, monkeypatch):
        """One reading gives no movement, but a split needs none."""
        gid = f"{DAY.isoformat()}-CWS-BAL"
        self._source(monkeypatch, [self._split(gid)])
        market.backfill(repo, gid)
        finalise(repo, gid, "BAL", "CWS", 3, 2)
        m = market.game_market(repo, gid)
        assert m.hold_pct is not None
        assert m.winner == "public", "money on the home side, home won"

    def test_without_a_split_there_is_a_price_and_no_verdict(self, repo, monkeypatch):
        gid = f"{DAY.isoformat()}-CWS-BAL"
        self._source(monkeypatch, [self._split(
            gid, ml_home_handle=None, ml_home_bets=None)])
        market.backfill(repo, gid)
        finalise(repo, gid, "BAL", "CWS", 3, 2)
        m = market.game_market(repo, gid)
        assert m.closed is not None and m.winner is None

    def test_it_does_not_invent_a_second_reading(self, repo, monkeypatch):
        gid = f"{DAY.isoformat()}-CWS-BAL"
        self._source(monkeypatch, [self._split(gid)])
        market.backfill(repo, gid)
        market.backfill(repo, gid)
        m = market.game_market(repo, gid)
        assert m.snapshots == 1
        assert not market._was_watched(m), "asking twice quickly is not watching"

    def test_an_unparseable_id_fetches_nothing(self, repo, monkeypatch):
        self._source(monkeypatch, [self._split("x")])
        assert market.backfill(repo, "not-a-game-id") == 0

    def test_an_unreachable_page_is_not_an_error(self, repo, monkeypatch):
        from thebeast.data.sources import splits as splits_mod

        class Broken:
            def fetch(self, day, game_ids=None):
                raise ConnectionError("down")
        monkeypatch.setattr(splits_mod, "VSiNSplitsSource", Broken)
        assert market.backfill(repo, f"{DAY.isoformat()}-CWS-BAL") == 0
