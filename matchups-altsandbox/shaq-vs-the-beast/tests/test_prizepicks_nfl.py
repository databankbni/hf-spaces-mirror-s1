"""The NFL prop browser, which maps nothing and prices nothing.

Two deliberate absences, both worth pinning because both look like omissions:

* **No stat map.** There is no NFL simulator, so there is nothing to translate
  onto. PrizePicks' own market name travels through to the page, and nothing is
  dropped for being unrecognised — a market we don't know is still a market
  worth showing.
* **No prices.** PrizePicks posts none; the payout is on the slip. The MLB
  board converts a break-even into odds so it can compute an edge against the
  simulation. Here there is no simulation to compare against, so deriving a
  number would be inventing the whole thing.

As with the MLB source, nothing here has reached PrizePicks — the egress policy
refuses the connection — so these run against a hand-built JSON:API document.
They prove the parser is right about that shape; `/api/nfl/props/probe` is what
proves the shape.
"""
from __future__ import annotations

from thebeast.data.sources.prizepicks_nfl import PrizePicksNFLSource


def _projection(pid: str, stat: str, line: float, *, status="pre_game",
                odds_type="standard"):
    return {
        "type": "projection", "id": pid,
        "attributes": {"line_score": line, "stat_type": stat,
                       "odds_type": odds_type, "status": status,
                       "is_promo": False, "description": "vs SF"},
        "relationships": {
            "new_player": {"data": {"type": "new_player", "id": f"p{pid}"}}},
    }


def _player(pid: str, name: str, team="LAR", position="WR"):
    return {"type": "new_player", "id": f"p{pid}",
            "attributes": {"name": name, "team": team, "position": position}}


def _doc(projections, players):
    return {"data": projections, "included": players,
            "meta": {"total_count": len(projections)}}


def _source(monkeypatch, doc):
    PrizePicksNFLSource.clear()
    src = PrizePicksNFLSource()

    def get(self, url, params=None, timeout=None):
        return {"data": []} if not params else doc

    monkeypatch.setattr(PrizePicksNFLSource, "_get", get)
    return src


class TestNothingIsMapped:
    def test_an_unknown_market_comes_through_under_its_own_name(self, monkeypatch):
        """The whole point. There's no vocabulary to fail to match."""
        doc = _doc([_projection("1", "Pass Yards", 274.5),
                    _projection("2", "Some New Market", 1.5)],
                   [_player("1", "Matthew Stafford", position="QB"),
                    _player("2", "Puka Nacua")])
        props = _source(monkeypatch, doc).fetch_props()
        assert sorted(p.market for p in props) == ["pass yards",
                                                   "some new market"]

    def test_the_readable_label_keeps_the_feeds_own_wording(self, monkeypatch):
        doc = _doc([_projection("1", "Receiving Yards", 82.5)],
                   [_player("1", "Puka Nacua")])
        props = _source(monkeypatch, doc).fetch_props()
        assert props[0].market_label == "Receiving Yards"
        assert props[0].market == "receiving yards"

    def test_demons_and_goblins_are_shown_not_dropped(self, monkeypatch):
        """This page is a browser, not a bet.

        The MLB board drops them because it would have to price them and can't.
        Here there is nothing to price, so hiding a real pick off their board
        would just make the page wrong.
        """
        doc = _doc([_projection("1", "Rush Yards", 55.5, odds_type="demon")],
                   [_player("1", "Kyren Williams", position="RB")])
        props = _source(monkeypatch, doc).fetch_props()
        assert [p.odds_type for p in props] == ["demon"]


class TestSearch:
    def _stocked(self, monkeypatch):
        return _source(monkeypatch, _doc(
            [_projection("1", "Receiving Yards", 82.5),
             _projection("2", "Receptions", 5.5),
             _projection("3", "Pass Yards", 274.5)],
            [_player("1", "Puka Nacua"), _player("2", "Ja'Marr Chase", "CIN"),
             _player("3", "Matthew Stafford", position="QB")]))

    def test_a_partial_name_finds_the_player(self, monkeypatch):
        hits = self._stocked(monkeypatch).search("nacua")
        assert [p.player_name for p in hits] == ["Puka Nacua"]

    def test_an_apostrophe_need_not_be_typed(self, monkeypatch):
        """The shared normalizer leaves a space where the apostrophe was.

        "Ja'Marr" becomes "ja marr", and nobody types the apostrophe *or* the
        space — which is exactly why a real player returned nothing once.
        """
        src = self._stocked(monkeypatch)
        for typed in ("jamarr", "Ja'Marr", "JA MARR", "chase"):
            assert [p.player_name for p in src.search(typed)] == \
                ["Ja'Marr Chase"], typed

    def test_an_empty_query_is_not_a_search(self, monkeypatch):
        assert self._stocked(monkeypatch).search("  ") == []

    def test_one_players_markets_arrive_together(self, monkeypatch):
        doc = _doc([_projection("1", "Receptions", 5.5),
                    _projection("2", "Receiving Yards", 82.5)],
                   [_player("1", "Puka Nacua"), _player("2", "Puka Nacua")])
        hits = _source(monkeypatch, doc).search("puka")
        assert [p.market for p in hits] == ["receiving yards", "receptions"]


class TestFailuresAreDistinguishable:
    def test_an_unreachable_feed_says_so(self, monkeypatch):
        """"PrizePicks is down" and "nobody has a line on him" are both empty.

        They mean opposite things to whoever typed the name, so reporting the
        first as the second states a fact about a player that is really a fact
        about the network.
        """
        PrizePicksNFLSource.clear()
        src = PrizePicksNFLSource()

        def boom(self, url, params=None, timeout=None):
            raise ConnectionError("CONNECT tunnel failed, response 403")

        monkeypatch.setattr(PrizePicksNFLSource, "_get", boom)
        assert src.search("nacua") == []
        assert "403" in src.last_error

    def test_projections_with_no_player_attached_are_counted(self, monkeypatch):
        """A broken `included` array drops every prop, and used to do it silently."""
        src = _source(monkeypatch, _doc([_projection("1", "Pass Yards", 274.5)], []))
        assert src.fetch_props() == []
        assert src.unnamed == 1
        assert "no player attached" in src.last_error

    def test_a_live_game_is_flagged(self, monkeypatch):
        doc = _doc([_projection("1", "Pass Yards", 274.5, status="in_progress")],
                   [_player("1", "Matthew Stafford", position="QB")])
        assert [p.is_live for p in _source(monkeypatch, doc).fetch_props()] == [True]


class TestProbe:
    def test_it_reports_what_arrived(self, monkeypatch):
        doc = _doc([_projection("1", "Pass Yards", 274.5)],
                   [_player("1", "Matthew Stafford", position="QB")])
        out = _source(monkeypatch, doc).probe()
        assert out["reachable"] is True
        assert out["projections"] == 1
        assert out["markets"] == {"pass yards": 1}

    def test_an_out_of_season_board_says_which_kind_of_empty_it_is(self, monkeypatch):
        out = _source(monkeypatch, _doc([], [])).probe()
        assert out["reachable"] is True
        assert "no NFL" in out["note"]
