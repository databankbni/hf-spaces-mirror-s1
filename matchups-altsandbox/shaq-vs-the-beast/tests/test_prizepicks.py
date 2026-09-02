"""The PrizePicks source, and the arithmetic that makes a pick'em priceable.

Nothing here reaches PrizePicks. The environment this was written in can't —
the egress policy refuses the connection — so these run against a hand-built
JSON:API document shaped the way every open-source reader of that endpoint
describes it. That is worth being blunt about: these tests prove the parser
does the right thing *with that shape*. Whether the shape is right is what
`/api/props-probe` answers, and only from a host that can reach them.

What they do prove properly is the part that has nothing to do with the network:
a PrizePicks pick carries no odds, so the bar it has to clear is a number we
chose, and every one of those choices is pinned here.
"""
from __future__ import annotations

import pytest

from thebeast.betting.odds import american_to_implied
from thebeast.data.sources.prizepicks import (
    BREAK_EVEN,
    STANDARD_PRICE,
    PrizePicksSource,
    _side_and_stat,
)


def _projection(pid: str, stat: str, line: float, *, odds_type="standard",
                promo=False, projection_type="Single Stat", status="pre_game"):
    return {
        "type": "projection", "id": pid,
        "attributes": {
            "line_score": line, "stat_type": stat, "odds_type": odds_type,
            "status": status, "is_promo": promo,
            "projection_type": projection_type,
        },
        "relationships": {
            "new_player": {"data": {"type": "new_player", "id": f"p{pid}"}},
        },
    }


def _player(pid: str, name: str, team: str, position: str):
    return {
        "type": "new_player", "id": f"p{pid}",
        "attributes": {"name": name, "display_name": name, "team": team,
                       "position": position},
    }


def _doc(projections, players, total=None):
    """One JSON:API page. `total` is the slate-wide count, not this page's.

    They differ only when there is more than one page, which is exactly the
    case the pagination test is about.
    """
    return {"data": projections, "included": players,
            "meta": {"total_count": len(projections) if total is None else total}}


def _source(monkeypatch, doc):
    """A source wired to one canned page, with the cross-call cache cleared."""
    PrizePicksSource.clear()
    src = PrizePicksSource()
    monkeypatch.setattr(PrizePicksSource, "_get",
                        lambda self, url, params=None, timeout=None: doc)
    return src


class TestTheBreakEven:
    """A pick'em pick has no price, so the bar is ours. It has to be right."""

    def test_two_pick_power_play_needs_57_7_percent(self):
        """3x on two legs that both have to land: (1/3)^(1/2).

        This is the whole basis for every "needs" percentage the board shows
        against PrizePicks, so it is pinned rather than left to a comment.
        """
        assert BREAK_EVEN == pytest.approx(0.5773502, abs=1e-6)

    def test_the_synthetic_price_implies_the_break_even_back(self):
        """The American number we hand downstream has to mean what we meant.

        Everything after this point — the edge, the Kelly stake, the implied
        percentage on the card — reads the price, not the break-even. If the
        conversion drifted, every number on the board would be quietly wrong
        and nothing would look broken.
        """
        assert STANDARD_PRICE == -137
        assert american_to_implied(STANDARD_PRICE) == pytest.approx(
            BREAK_EVEN, abs=0.001)

    def test_rounding_errs_towards_demanding_more_not_less(self):
        """A whole-number price can't land exactly on 57.735%.

        Which way it misses matters: rounding down would mark plays as bets
        that aren't. So the price has to imply *at least* the true break-even.
        """
        assert american_to_implied(STANDARD_PRICE) >= BREAK_EVEN

    def test_both_sides_get_the_same_bar(self, monkeypatch):
        """PrizePicks charges the same for MORE and LESS. Nothing may tilt it."""
        doc = _doc([_projection("1", "Hits", 0.5)],
                   [_player("1", "Pete Crow-Armstrong", "CHC", "CF")])
        props = _source(monkeypatch, doc).fetch_props()
        assert len(props) == 1
        assert props[0].over_price == props[0].under_price == STANDARD_PRICE

    def test_the_bar_is_well_above_a_coin_flip(self):
        """The trap this constant exists to avoid.

        A pick'em line *looks* like a 50/50, and reading it that way makes any
        model that says 54% look like an edge. It isn't one — it's a losing
        slip. The bar has to be meaningfully above half.
        """
        assert BREAK_EVEN > 0.55


class TestSideAndStat:
    """Which distribution a market gets priced against.

    The one place a silent bug here would be catastrophic rather than merely
    wrong: pricing a pitcher's strikeout prop off a batter's strikeout
    distribution produces a confident number and a nonsense bet.
    """

    def test_an_explicit_prefix_names_the_side(self):
        assert _side_and_stat("Pitcher Strikeouts", "P") == ("pitcher", "k")
        assert _side_and_stat("Hitter Strikeouts", "CF") == ("batter", "k")

    def test_position_decides_when_the_market_doesnt(self):
        """"Strikeouts" alone means opposite things either side of the ball."""
        assert _side_and_stat("Strikeouts", "SP") == ("pitcher", "k")
        assert _side_and_stat("Strikeouts", "2B") == ("batter", "k")

    def test_walks_versus_walks_allowed(self):
        """Same word, two markets. Drawing them is not giving them up."""
        assert _side_and_stat("Walks", "1B") == ("batter", "bb")
        assert _side_and_stat("Walks Allowed", "1B") == ("pitcher", "bb_allowed")

    def test_a_prefix_beats_the_position(self):
        """Two-way players are listed as hitters and still get pitching lines.

        Ohtani's position says DH on both. Only the market name distinguishes
        them, so it has to win.
        """
        assert _side_and_stat("Pitcher Strikeouts", "DH") == ("pitcher", "k")

    def test_markets_we_dont_simulate_are_refused_not_guessed(self):
        """A run belongs to the runner, and our bases have no runner identity.

        There is no per-batter runs distribution, so there is nothing honest to
        price these against — and a wrong mapping here would look completely
        normal on the board.
        """
        assert _side_and_stat("Runs", "CF") is None
        assert _side_and_stat("Hits+Runs+RBIs", "CF") is None
        assert _side_and_stat("Stolen Bases", "CF") is None
        assert _side_and_stat("Fantasy Score", "CF") is None


class TestParsing:
    def test_a_projection_becomes_a_two_sided_prop(self, monkeypatch):
        doc = _doc([_projection("1", "Total Bases", 1.5)],
                   [_player("1", "Aaron Judge", "NYY", "RF")])
        props = _source(monkeypatch, doc).fetch_props()
        assert len(props) == 1
        p = props[0]
        assert p.player_name == "Aaron Judge"
        assert (p.side, p.stat, p.line) == ("batter", "total_bases", 1.5)
        assert p.team == "NYY"

    def test_the_player_comes_from_included_not_the_projection(self, monkeypatch):
        """JSON:API keeps them apart and joins by reference.

        A projection on its own cannot name anyone, so a parser that only read
        `data` would drop the entire board — and it would look exactly like an
        empty slate.
        """
        doc = _doc([_projection("1", "Hits", 0.5)], [])
        assert _source(monkeypatch, doc).fetch_props() == []

    def test_a_pitcher_prop_is_priced_as_one(self, monkeypatch):
        doc = _doc([_projection("1", "Pitching Outs", 17.5)],
                   [_player("1", "Zack Wheeler", "PHI", "P")])
        props = _source(monkeypatch, doc).fetch_props()
        assert [(p.side, p.stat) for p in props] == [("pitcher", "outs")]

    def test_in_progress_lines_are_flagged_not_dropped(self, monkeypatch):
        """A live prop needs a different simulation, not no simulation."""
        doc = _doc([_projection("1", "Hits", 0.5, status="in_progress")],
                   [_player("1", "Mookie Betts", "LAD", "SS")])
        props = _source(monkeypatch, doc).fetch_props()
        assert [p.is_live for p in props] == [True]

    def test_team_codes_are_translated_to_ours(self, monkeypatch):
        """PrizePicks says CHW and OAK; the rest of this app says CWS and ATH.

        Only used to attribute a prop to a game for the coverage count — but a
        prop filed under the wrong game is worse than one filed under none.
        """
        doc = _doc(
            [_projection("1", "Hits", 0.5), _projection("2", "Hits", 0.5)],
            [_player("1", "Luis Robert", "CHW", "CF"),
             _player("2", "Brent Rooker", "OAK", "DH")])
        props = _source(monkeypatch, doc).fetch_props()
        assert sorted(p.team for p in props) == ["ATH", "CWS"]


class TestWhatGetsDropped:
    """Every drop here is a card that won't appear, and they all look alike."""

    def test_goblins_and_demons_are_dropped_by_default(self, monkeypatch):
        """They move the line without saying what the leg now pays.

        A goblin priced at the standard break-even is the dangerous direction:
        an easier line makes our model's number go up while the bar stays put,
        so it reads as free money. Dropped rather than flattered.
        """
        doc = _doc([_projection("1", "Hits", 0.5, odds_type="goblin"),
                    _projection("2", "Hits", 1.5, odds_type="demon"),
                    _projection("3", "Hits", 0.5)],
                   [_player("1", "A B", "CHC", "CF"),
                    _player("2", "C D", "CHC", "CF"),
                    _player("3", "E F", "CHC", "CF")])
        drops: dict = {}
        props = _source(monkeypatch, doc).fetch_props(drops=drops)
        assert [p.player_name for p in props] == ["E F"]
        assert drops["odds_type=goblin"] == 1
        assert drops["odds_type=demon"] == 1

    def test_specials_can_be_switched_back_on(self, monkeypatch):
        monkeypatch.setenv("PRIZEPICKS_INCLUDE_SPECIALS", "1")
        doc = _doc([_projection("1", "Hits", 0.5, odds_type="goblin")],
                   [_player("1", "A B", "CHC", "CF")])
        assert len(_source(monkeypatch, doc).fetch_props()) == 1

    def test_combos_are_dropped(self, monkeypatch):
        """Two players in one line. No single distribution to price it against."""
        doc = _doc([_projection("1", "Hits", 1.5, projection_type="Combo")],
                   [_player("1", "A B + C D", "CHC", "CF")])
        drops: dict = {}
        assert _source(monkeypatch, doc).fetch_props(drops=drops) == []
        assert drops["combo_projection"] == 1

    def test_unmapped_markets_are_counted_by_name(self, monkeypatch):
        """The difference between "they don't offer it" and "we don't read it".

        Only one of those is our bug, and from the board they are identical, so
        the market's own name has to survive the drop.
        """
        doc = _doc([_projection("1", "Hits+Runs+RBIs", 2.5)],
                   [_player("1", "A B", "CHC", "CF")])
        src = _source(monkeypatch, doc)
        drops: dict = {}
        assert src.fetch_props(drops=drops) == []
        assert drops["unmapped_market=hits+runs+rbis"] == 1
        assert src.unmapped["hits+runs+rbis"] == 1

    def test_an_unreachable_endpoint_is_empty_and_says_why(self, monkeypatch):
        """"PrizePicks blocked us" and "no slate today" are both an empty list.

        They mean completely different things to whoever is looking at an empty
        board, so the reason has to survive.
        """
        PrizePicksSource.clear()
        src = PrizePicksSource()

        def boom(self, url, params=None, timeout=None):
            raise ConnectionError("tunnel refused")

        monkeypatch.setattr(PrizePicksSource, "_get", boom)
        assert src.fetch_props() == []
        assert "tunnel refused" in src.last_error

    def test_a_non_mlb_sport_returns_nothing_rather_than_mlb(self, monkeypatch):
        """Callers may pass a sport; PrizePicks selects by league id.

        Quietly serving MLB for an NFL request would be the worst possible
        answer: plausible data for the wrong league.
        """
        doc = _doc([_projection("1", "Hits", 0.5)],
                   [_player("1", "A B", "CHC", "CF")])
        assert _source(monkeypatch, doc).fetch_props(sport="nfl") == []


class TestHomeRunsDontVanish:
    """The bug that emptied the home-run board, guarded on the new source.

    On the old feed a gate on `outcome_type` silently removed every one-sided
    market, and home runs were mostly those — so the HR tab came through with a
    single card while hits and total bases were full, and from the page it
    looked like the model had nothing to say about home runs. It took three
    wrong explanations to find.

    Nothing in this parser can be selective by stat: a home run travels the
    identical path as a hit. These pin that, so the next filter added here has
    to prove it isn't doing what that one did.
    """

    def test_home_runs_survive_exactly_as_hits_do(self, monkeypatch):
        doc = _doc([_projection("1", "Home Runs", 0.5),
                    _projection("2", "Hits", 0.5)],
                   [_player("1", "Pete Crow-Armstrong", "CHC", "CF"),
                    _player("2", "Nico Hoerner", "CHC", "2B")])
        props = _source(monkeypatch, doc).fetch_props()
        assert sorted(p.stat for p in props) == ["hits", "home_runs"]

    def test_many_players_home_runs_all_come_through(self, monkeypatch):
        """One card in a tab is a fact about the feed or a bug in the parser.

        This is the parser half, pinned: given six, six arrive.
        """
        names = ["A One", "B Two", "C Three", "D Four", "E Five", "F Six"]
        doc = _doc(
            [_projection(str(i), "Home Runs", 0.5) for i in range(6)],
            [_player(str(i), n, "CHC", "CF") for i, n in enumerate(names)])
        props = _source(monkeypatch, doc).fetch_props()
        assert sorted(p.player_name for p in props) == sorted(names)

    def test_every_filter_is_countable(self, monkeypatch):
        """A drop nobody can count is how the last one hid for a week."""
        doc = _doc([_projection("1", "Home Runs", 0.5, odds_type="demon"),
                    _projection("2", "Runs", 0.5),
                    _projection("3", "Home Runs", 0.5, promo=True)],
                   [_player("1", "A B", "CHC", "CF"),
                    _player("2", "C D", "CHC", "CF"),
                    _player("3", "E F", "CHC", "CF")])
        drops: dict = {}
        assert _source(monkeypatch, doc).fetch_props(drops=drops) == []
        assert sum(drops.values()) == 3, drops


class TestPagination:
    def test_it_keeps_asking_until_the_pages_run_out(self, monkeypatch):
        """A board truncated at page one looks exactly like a thin slate.

        This app has already spent a week on "why is there only one home run
        prop", so a silent stop after 250 is not a failure mode worth having.
        """
        from thebeast.data.sources import prizepicks as pp

        monkeypatch.setattr(pp, "PAGE_SIZE", 2)
        PrizePicksSource.clear()
        src = PrizePicksSource()

        pages = {
            1: _doc([_projection("1", "Hits", 0.5),
                     _projection("2", "Hits", 0.5)],
                    [_player("1", "A B", "CHC", "CF"),
                     _player("2", "C D", "CHC", "CF")], total=3),
            2: _doc([_projection("3", "Hits", 0.5)],
                    [_player("3", "E F", "CHC", "CF")], total=3),
        }
        seen = []

        def get(self, url, params=None, timeout=None):
            if not params:                      # the league lookup, not a page
                return {"data": []}
            seen.append(params["page"])
            return pages.get(params["page"], {"data": [], "included": []})

        monkeypatch.setattr(PrizePicksSource, "_get", get)
        props = src.fetch_props()
        assert seen == [1, 2]
        assert sorted(p.player_name for p in props) == ["A B", "C D", "E F"]


class TestProbe:
    def test_it_reports_the_vocabulary_it_found(self, monkeypatch):
        """The parser's stat map is the thing most likely to be wrong.

        Nothing here has seen a real response, so the probe has to report what
        actually arrived rather than assert the map handled it.
        """
        doc = _doc([_projection("1", "Hits", 0.5),
                    _projection("2", "Hits+Runs+RBIs", 2.5)],
                   [_player("1", "A B", "CHC", "CF"),
                    _player("2", "C D", "CHC", "CF")])
        out = _source(monkeypatch, doc).probe()
        assert out["reachable"] is True
        assert out["stat_types"]["hits"] == 1
        assert out["unmapped_markets"]["hits+runs+rbis"] == 1
        assert out["parsed"] == 1

    def test_it_states_the_assumption_every_time(self, monkeypatch):
        """The break-even is the one number here that's a decision.

        It rides on every probe so it can never be mistaken for something
        PrizePicks quoted.
        """
        doc = _doc([], [])
        out = _source(monkeypatch, doc).probe()
        assert out["break_even_pct"] == pytest.approx(57.74, abs=0.01)
        assert out["synthetic_price"] == STANDARD_PRICE

    def test_an_unreachable_endpoint_probes_as_unreachable(self, monkeypatch):
        PrizePicksSource.clear()

        def boom(self, url, params=None, timeout=None):
            raise ConnectionError("CONNECT tunnel failed, response 403")

        monkeypatch.setattr(PrizePicksSource, "_get", boom)
        out = PrizePicksSource().probe()
        assert out["reachable"] is False
        assert "403" in out["error"]
