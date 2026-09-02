"""The prop board: every priced prop, paired into cards.

This is a view over the ranked report rather than a second pricing, so almost
nothing here is about probability — that's `test_betting`'s job and the numbers
arrive already computed. What's new is the pairing, and the pairing is where
this can go wrong in ways nobody would notice: two sides of one prop collapsing
into one card, a live line merging with its pregame twin, or the "we like this
side" mark going to whichever number is bigger rather than to the one that
actually beats its price.
"""
from __future__ import annotations

from datetime import date

import pytest

from thebeast.betting.board import _multiplier, build_board

DAY = date(2026, 8, 8)


def bet(market="prop_over", player="Chase Meidroth", stat="hits", line=0.5,
        price=-110, model=0.60, implied=0.52, edge=0.08, has_edge=True,
        is_live=False, category="batter_prop", game_id="2026-08-08-CWS-DET",
        team="CWS"):
    return {
        "market": market, "player": player, "stat": stat, "line": line,
        "price": price, "model_probability": model,
        "implied_probability": implied, "edge": edge, "has_edge": has_edge,
        "is_live": is_live, "category": category, "game_id": game_id,
        "away": "CWS", "home": "DET", "first_pitch": "2026-08-08T16:10:00Z",
        "n_sims": 2000, "team": team, "kelly_pct": 3.2,
    }


class FakeReport:
    def __init__(self, bets):
        self.bets = bets
        self.date = DAY.isoformat()
        self.generated_at = "now"
        self.games_considered = 1
        self.games_priced = 1
        self.props_available = True
        self.live_games = 0
        self.notes = []


@pytest.fixture
def build(monkeypatch):
    def run(bets, **kw):
        captured = {}

        def fake(repo, day, **kwargs):
            captured.update(kwargs)
            return FakeReport(bets)

        monkeypatch.setattr("thebeast.betting.best_bets.build_best_bets", fake)
        out = build_board(None, DAY, **kw)
        out["_kwargs"] = captured
        return out
    return run


class TestMultiplier:
    def test_american_becomes_the_multiple_a_board_shows(self):
        """Their board is in multiples. A reader comparing the two pages should
        not have to convert in their head."""
        assert _multiplier(-110) == 1.91
        assert _multiplier(150) == 2.5

    def test_a_missing_price_has_no_multiple(self):
        assert _multiplier(None) is None
        assert _multiplier(0) is None


class TestPairing:
    def test_the_two_sides_of_a_prop_are_one_card(self, build):
        out = build([bet("prop_over"), bet("prop_under", price=105,
                                           model=0.40, edge=-0.05,
                                           has_edge=False)])
        cards = out["groups"][0]["cards"]
        assert len(cards) == 1
        assert cards[0]["over"]["model_pct"] == 60.0
        assert cards[0]["under"]["model_pct"] == 40.0

    def test_a_live_prop_is_not_merged_with_its_pregame_twin(self, build):
        """Same player, same stat, same number — and genuinely different bets,
        because one is on the whole game and one on what's left of it."""
        out = build([bet(), bet(is_live=True)])
        assert len(out["groups"][0]["cards"]) == 2

    def test_two_lines_on_one_stat_stay_apart(self, build):
        out = build([bet(line=0.5), bet(line=1.5)])
        assert len(out["groups"][0]["cards"]) == 2

    def test_a_one_sided_prop_still_makes_a_card(self, build):
        """A feed sometimes posts only one side. Dropping the card would hide
        a real offer; showing an empty half says what's actually true."""
        out = build([bet("prop_over")])
        card = out["groups"][0]["cards"][0]
        assert card["over"] is not None and card["under"] is None

    def test_batter_and_pitcher_strikeouts_are_different_tabs(self, build):
        """Both are stat "k". The side is the only thing telling them apart,
        and merging them would put a hitter's card in a pitcher's tab."""
        out = build([bet(stat="k"),
                     bet(stat="k", player="Garrett Crochet",
                         category="pitcher_prop")])
        tabs = [(g["side"], g["stat"]) for g in out["groups"]]
        assert ("batter", "k") in tabs and ("pitcher", "k") in tabs

    def test_game_markets_are_not_props(self, build):
        out = build([bet(market="over"), bet(market="home_ml"), bet()])
        assert out["totals"]["cards"] == 1


class TestWhichSideWeLike:
    def test_the_mark_follows_edge_not_probability(self, build):
        """The mistake this page could most easily encourage. A 70% shot at a
        price implying 75% is not a bet, and it must not be marked as one just
        for carrying the bigger number."""
        out = build([
            bet("prop_over", model=0.70, implied=0.75, edge=-0.05, has_edge=False),
            bet("prop_under", model=0.30, implied=0.20, edge=0.10, has_edge=True),
        ])
        card = out["groups"][0]["cards"][0]
        assert card["over"]["model_pct"] > card["under"]["model_pct"]
        assert card["best"] == "under", "the side that beats its price"

    def test_neither_side_is_marked_when_neither_clears(self, build):
        out = build([
            bet("prop_over", edge=-0.02, has_edge=False),
            bet("prop_under", edge=-0.03, has_edge=False),
        ])
        assert out["groups"][0]["cards"][0]["best"] is None
        assert out["totals"]["with_edge"] == 0

    def test_the_better_of_two_qualifying_sides_wins(self, build):
        out = build([
            bet("prop_over", edge=0.03, has_edge=True),
            bet("prop_under", edge=0.09, has_edge=True),
        ])
        assert out["groups"][0]["cards"][0]["best"] == "under"


class TestGrouping:
    def test_tabs_come_in_the_stated_order(self, build):
        out = build([bet(stat="rbi"), bet(stat="hits"),
                     bet(stat="total_bases")])
        assert [g["stat"] for g in out["groups"]] == \
            ["hits", "total_bases", "rbi"]

    def test_live_cards_lead_their_tab(self, build):
        """The most time-sensitive thing in a tab, and the thing a stale board
        is most wrong about."""
        out = build([bet(edge=0.20, has_edge=True),
                     bet(player="Someone Else", is_live=True, edge=0.01)])
        assert out["groups"][0]["cards"][0]["is_live"] is True

    def test_within_a_tab_the_best_edge_leads(self, build):
        out = build([bet(player="Small", edge=0.01),
                     bet(player="Big", edge=0.15)])
        assert out["groups"][0]["cards"][0]["player"] == "Big"

    def test_a_tab_counts_its_own_qualifiers(self, build):
        out = build([bet(player="A", has_edge=True),
                     bet(player="B", has_edge=False, edge=-0.01)])
        g = out["groups"][0]
        assert g["count"] == 2 and g["with_edge"] == 1

    def test_a_stat_with_no_tab_is_reported_not_swallowed(self, build):
        """A market priced but absent from the tab order would vanish with no
        trace. Better to say so than to quietly show less than we have."""
        out = build([bet(stat="something_new")])
        assert out["unmapped_stats"] == ["batter/something_new"]

    def test_an_empty_board_is_not_an_error(self, build):
        out = build([])
        assert out["groups"] == [] and out["totals"]["cards"] == 0


class TestItAsksForEverything:
    def test_the_ranker_is_asked_for_every_play_not_the_top_five(self, build):
        """The whole difference between this page and the ranked panel."""
        out = build([bet()])
        assert out["_kwargs"]["per_category"] >= 100_000

    def test_an_explicit_limit_is_still_honoured(self, build):
        out = build([bet()], per_category=3)
        assert out["_kwargs"]["per_category"] == 3


class TestCardShape:
    def test_a_card_carries_what_the_layout_needs(self, build):
        card = build([bet(), bet("prop_under")])["groups"][0]["cards"][0]
        for k in ("player", "team", "matchup", "line", "first_pitch",
                  "is_live", "n_sims", "over", "under", "best"):
            assert k in card, k
        assert card["matchup"] == "CWS @ DET"

    def test_both_the_model_and_the_price_are_reported(self, build):
        """One without the other is unreadable: our percentage alone can't say
        whether it's a bet, and the price alone is just their board."""
        side = build([bet()])["groups"][0]["cards"][0]["over"]
        assert side["model_pct"] == 60.0
        assert side["implied_pct"] == 52.0
        assert side["multiplier"] == 1.91
        assert side["edge_pct"] == 8.0


class TestTheGamesStrip:
    """The filter row across the top, built from the cards themselves.

    From the schedule it would list games with nothing priced on them, and a
    filter chip that selects an empty board is worse than no chip.
    """

    def _two_games(self):
        return [
            bet(game_id="g1", player="A"),
            bet("prop_under", game_id="g1", player="A", has_edge=False, edge=-0.02),
            bet(game_id="g2", player="B", team="STL", has_edge=False, edge=-0.01),
        ]

    def test_it_lists_a_game_once_with_its_own_counts(self, build):
        games = {g["game_id"]: g for g in build(self._two_games())["games"]}
        assert set(games) == {"g1", "g2"}
        assert games["g1"]["cards"] == 1 and games["g1"]["with_edge"] == 1
        assert games["g2"]["cards"] == 1 and games["g2"]["with_edge"] == 0

    def test_a_game_with_nothing_priced_is_not_listed(self, build):
        """It would be a chip that filters the board down to nothing."""
        assert build([bet(game_id="g1")])["games"] == [
            g for g in build([bet(game_id="g1")])["games"] if g["game_id"] == "g1"
        ]
        assert len(build([bet(game_id="g1")])["games"]) == 1

    def test_live_games_lead_the_strip(self, build):
        out = build([bet(game_id="early", is_live=False),
                     bet(game_id="now", player="B", is_live=True)])
        assert out["games"][0]["game_id"] == "now"

    def test_pregame_games_run_in_first_pitch_order(self, build):
        late = bet(game_id="late", player="B")
        late["first_pitch"] = "2026-08-08T23:05:00Z"
        early = bet(game_id="early", player="C")
        early["first_pitch"] = "2026-08-08T16:10:00Z"
        out = build([late, early])
        assert [g["game_id"] for g in out["games"]] == ["early", "late"]

    def test_a_game_is_live_if_any_of_its_props_are(self, build):
        out = build([bet(game_id="g1"), bet(game_id="g1", player="B", is_live=True)])
        assert out["games"][0]["is_live"] is True

    def test_the_strip_carries_what_the_chip_needs(self, build):
        g = build([bet()])["games"][0]
        for k in ("game_id", "away", "home", "matchup", "first_pitch",
                  "is_live", "cards", "with_edge"):
            assert k in g, k


class TestPropAccounting:
    """Where props go that never become a card.

    Three causes, identical symptom — a prop plainly on PrizePicks that isn't on
    our board. The feed never sent it, we couldn't map the market, or the
    player isn't in a lineup we simulated. Answering that took reading the
    parser; now the page carries it.
    """

    def _report(self, bets, **kw):
        class R:
            date, generated_at = DAY.isoformat(), "now"
            games_considered = games_priced = 1
            props_available, live_games, notes = True, 0, []
            props_offered = kw.get("offered", 0)
            props_unmatched = kw.get("unmatched", 0)
            prop_drops = kw.get("drops", {})
            def __init__(s): s.bets = bets
        return R()

    def _build(self, monkeypatch, bets, **kw):
        monkeypatch.setattr("thebeast.betting.best_bets.build_best_bets",
                            lambda repo, day, **k: self._report(bets, **kw))
        return build_board(None, DAY)

    def test_it_reports_what_the_feed_offered_against_what_was_priced(self, monkeypatch):
        out = self._build(monkeypatch, [bet()], offered=40)
        assert out["source"]["offered"] == 40
        assert out["source"]["priced"] == 1

    def test_props_on_a_player_we_did_not_simulate_are_counted(self, monkeypatch):
        """The quiet one. PrizePicks quotes a bench bat, we have no distribution
        for him, and the prop leaves no trace anywhere."""
        out = self._build(monkeypatch, [bet()], offered=10, unmatched=6)
        assert out["source"]["unmatched_player"] == 6

    def test_the_source_filters_are_named_with_their_counts(self, monkeypatch):
        out = self._build(monkeypatch, [bet()], offered=10,
                          drops={"unmapped_market=stolen_bases": 4})
        assert out["source"]["dropped"]["unmapped_market=stolen_bases"] == 4

    def test_a_report_without_the_counters_still_builds(self, monkeypatch):
        """The board must not require a field the ranker might not carry."""
        class Old:
            date, generated_at = DAY.isoformat(), "now"
            games_considered = games_priced = 1
            props_available, live_games, notes = True, 0, []
            bets = [bet()]
        monkeypatch.setattr("thebeast.betting.best_bets.build_best_bets",
                            lambda repo, day, **k: Old())
        out = build_board(None, DAY)
        assert out["source"]["offered"] == 0 and out["source"]["priced"] == 1


class TestPerStatCoverage:
    """"One card" and "one of sixteen quoted" are different facts, and only
    one of them is a bug. The tab has to be able to tell them apart."""

    def _build(self, monkeypatch, bets, offered=None, unmatched=None):
        class R:
            date, generated_at = DAY.isoformat(), "now"
            games_considered = games_priced = 1
            props_available, live_games, notes = True, 0, []
            props_quoted = props_offered = props_unmatched = 0
            prop_drops = {}
            offered_by_stat = offered or {}
            unmatched_by_stat = unmatched or {}
            def __init__(s): s.bets = bets
        monkeypatch.setattr("thebeast.betting.best_bets.build_best_bets",
                            lambda repo, day, **k: R())
        return build_board(None, DAY)

    def test_a_tab_knows_how_many_were_quoted_against_how_many_it_shows(self, monkeypatch):
        out = self._build(monkeypatch, [bet(stat="home_runs")],
                          offered={"batter/home_runs": 16},
                          unmatched={"batter/home_runs": 15})
        g = out["groups"][0]
        assert g["count"] == 1 and g["offered"] == 16 and g["unmatched"] == 15

    def test_a_tab_with_nothing_missing_says_nothing_is_missing(self, monkeypatch):
        out = self._build(monkeypatch, [bet(stat="hits")],
                          offered={"batter/hits": 1})
        g = out["groups"][0]
        assert g["offered"] == g["count"] and g["unmatched"] == 0

    def test_the_quoted_total_counts_what_the_feed_sent_not_what_we_mapped(self, monkeypatch):
        """The first version of this reported the post-mapping count as "what
        the feed quoted", which made 541 dropped markets invisible and the
        arithmetic on the panel impossible to follow."""
        class R:
            date, generated_at = DAY.isoformat(), "now"
            games_considered = games_priced = 1
            props_available, live_games, notes = True, 0, []
            props_quoted, props_offered, props_unmatched = 1928, 1387, 206
            prop_drops = {"unmapped_market=runs": 255}
            offered_by_stat = unmatched_by_stat = {}
            bets = [bet()]
        monkeypatch.setattr("thebeast.betting.best_bets.build_best_bets",
                            lambda repo, day, **k: R())
        src = build_board(None, DAY)["source"]
        assert src["quoted"] == 1928 and src["offered"] == 1387


class TestPerGameCoverage:
    """Coverage has to be per game, because the game filter is how anyone
    compares this page against the app. Board-wide "1 of 16" is worse than no
    number at all once a game is selected."""

    def _build(self, monkeypatch, bets, by_game=None):
        class R:
            date, generated_at = DAY.isoformat(), "now"
            games_considered = games_priced = 1
            props_available, live_games, notes = True, 0, []
            props_quoted = props_offered = props_unmatched = 0
            prop_drops = offered_by_stat = unmatched_by_stat = {}
            offered_by_game_stat = by_game or {}
            def __init__(s): s.bets = bets
        monkeypatch.setattr("thebeast.betting.best_bets.build_best_bets",
                            lambda repo, day, **k: R())
        return build_board(None, DAY)

    def test_coverage_is_keyed_by_game_and_stat(self, monkeypatch):
        out = self._build(monkeypatch, [bet(stat="home_runs")],
                          by_game={"2026-08-08-CWS-DET|batter/home_runs": 16})
        assert out["coverage"]["2026-08-08-CWS-DET|batter/home_runs"] == 16

    def test_a_board_without_coverage_still_builds(self, monkeypatch):
        out = self._build(monkeypatch, [bet()])
        assert out["coverage"] == {}
