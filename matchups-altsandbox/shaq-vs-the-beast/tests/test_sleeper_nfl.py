"""Sleeper's NFL board, and the search over it.

The parser is shared in spirit with the MLB source — same endpoint, same
option-walking, same odds handling — and those parts are proven in production.
What's new here is the decision *not* to map markets onto anything: there is no
NFL simulator, so a market we don't recognise is still worth showing, and
several of these exist to keep that true.

The fixtures below are the shape the MLB feed actually has, with NFL market
names substituted. That makes them a fair test of the logic and no test at all
of the vocabulary — the live vocabulary is what `probe()` is for, and nothing
in this file can stand in for running it.
"""
from __future__ import annotations

import pytest

from thebeast.data.sources.sleeper_nfl import (
    SleeperNFLSource, _as_american, _label,
)


def line(player_id="4046", market="pass_yards", value=274.5, sport="nfl",
         over=1.91, under=1.87, subject_type="player",
         outcome_type="over_under", status="active", game_status="pre_game"):
    return {
        "sport": sport, "subject_type": subject_type, "subject_id": player_id,
        "wager_type": market, "outcome_type": outcome_type, "status": status,
        "game_status": game_status,
        "options": [
            {"outcome": "over", "outcome_value": value,
             "payout_multiplier": over, "status": "active",
             "subject_team": "KC"},
            {"outcome": "under", "outcome_value": value,
             "payout_multiplier": under, "status": "active",
             "subject_team": "KC"},
        ],
    }


DIRECTORY = {
    "4046": {"full_name": "Patrick Mahomes", "team": "KC", "position": "QB"},
    "6794": {"first_name": "Ja'Marr", "last_name": "Chase", "team": "CIN",
             "position": "WR"},
}


@pytest.fixture
def src(monkeypatch):
    SleeperNFLSource.clear()

    def install(items, directory=DIRECTORY):
        def fake_get(self, url, params=None, timeout=None):
            if "players" in url:
                return directory
            return items
        monkeypatch.setattr(SleeperNFLSource, "_get", fake_get)
        return SleeperNFLSource()

    yield install
    SleeperNFLSource.clear()


class TestOdds:
    def test_a_decimal_multiplier_becomes_american(self):
        """Sleeper quotes some markets as a payout multiplier. Read raw it
        gives +2 where +100 was meant, which looks plausible on a page."""
        assert _as_american(1.91) == -110
        assert _as_american(2.5) == 150

    def test_american_odds_pass_through(self):
        assert _as_american(-110) == -110
        assert _as_american("+130") == 130

    def test_nonsense_is_none_not_zero(self):
        assert _as_american(None) is None
        assert _as_american("even money") is None
        assert _as_american(True) is None, "a bool is not a price"


class TestParsing:
    def test_it_reads_a_prop(self, src):
        p = src([line()]).fetch_props()[0]
        assert p.player_name == "Patrick Mahomes"
        assert p.market == "pass_yards" and p.line == 274.5
        assert (p.over_price, p.under_price) == (-110, -115)
        assert p.team == "KC" and p.position == "QB"

    def test_every_market_survives_including_unknown_ones(self, src):
        """The point of the whole page. There's no NFL model to map onto, so a
        market we've never seen is shown rather than dropped — dropping it
        would hide the thing the user came to look at."""
        items = [line(market=m) for m in
                 ("pass_yards", "some_new_market_2027", "anytime_td")]
        got = {p.market for p in src(items).fetch_props()}
        assert got == {"pass_yards", "some_new_market_2027", "anytime_td"}

    def test_a_name_is_built_from_parts_when_there_is_no_full_name(self, src):
        p = src([line(player_id="6794")]).fetch_props()[0]
        assert p.player_name == "Ja'Marr Chase"

    def test_the_sport_field_is_trusted_not_the_parameter(self, src):
        """Asking for nfl returns every sport Sleeper runs, so each item is
        checked against its own sport rather than the request."""
        items = [line(), line(market="strike_outs", sport="mlb"),
                 line(market="map_1_kills", sport="cs2")]
        props = src(items).fetch_props()
        assert len(props) == 1 and props[0].market == "pass_yards"

    def test_team_markets_are_not_player_props(self, src):
        assert src([line(subject_type="team")]).fetch_props() == []

    def test_suspended_lines_are_skipped(self, src):
        assert src([line(status="suspended")]).fetch_props() == []

    def test_other_outcome_shapes_are_skipped(self, src):
        assert src([line(outcome_type="moneyline")]).fetch_props() == []

    def test_a_line_with_no_price_either_side_is_skipped(self, src):
        assert src([line(over=None, under=None)]).fetch_props() == []

    def test_a_live_line_is_kept_but_tagged(self, src):
        """Kept because it's real, tagged because it prices the rest of the
        game rather than the whole one."""
        p = src([line(game_status="in_game")]).fetch_props()[0]
        assert p.is_live and p.game_status == "in_game"

    def test_an_unreachable_feed_yields_nothing(self, monkeypatch):
        SleeperNFLSource.clear()
        monkeypatch.setattr(
            SleeperNFLSource, "_get",
            lambda self, url, params=None, timeout=None: (_ for _ in ()).throw(
                ConnectionError("down")))
        assert SleeperNFLSource().fetch_props() == []

    def test_a_missing_directory_does_not_lose_the_prop(self, src):
        """The name is the only thing the directory is needed for, and the
        line payload sometimes carries one anyway."""
        items = [dict(line(), player_name="Some Rookie")]
        props = src(items, directory={}).fetch_props()
        assert len(props) == 1 and props[0].player_name == "Some Rookie"


class TestSearch:
    def test_it_finds_a_player_by_surname(self, src):
        assert len(src([line()]).search("mahomes")) == 1

    def test_punctuation_and_case_do_not_have_to_match(self, src):
        """"ja'marr", "JaMarr" and "Ja'Marr Chase Jr." are one player, and
        nobody types the apostrophe."""
        s = src([line(player_id="6794", market="rec_yards")])
        assert len(s.search("jamarr")) == 1
        assert len(s.search("Ja'Marr Chase")) == 1

    def test_an_empty_query_returns_nothing(self, src):
        """An empty box is not a search for everything."""
        s = src([line()])
        assert s.search("") == [] and s.search("   ") == []

    def test_a_name_nobody_posted_returns_nothing(self, src):
        assert src([line()]).search("zzzz") == []

    def test_one_players_markets_arrive_together_and_ordered(self, src):
        items = [line(market="rush_yards", value=8.5),
                 line(market="pass_tds", value=1.5),
                 line(market="pass_yards", value=274.5)]
        got = [p.market for p in src(items).search("mahomes")]
        assert got == sorted(got), "stable order, not the feed's order"

    def test_the_feed_is_fetched_once_across_searches(self, src, monkeypatch):
        calls = {"n": 0}
        s = src([line()])
        real = s._raw

        def counting():
            calls["n"] += 1
            return real()
        monkeypatch.setattr(s, "_raw", counting)
        for _ in range(5):
            s.search("mahomes")
        assert calls["n"] == 1, "a search page must not be a call per keystroke"


class TestProbe:
    def test_it_reports_what_arrived(self, src):
        d = src([line(), line(market="rec_yards", sport="mlb")]).probe()
        assert d["reachable"] and d["total_items"] == 2 and d["nfl_items"] == 1
        assert d["markets"] == {"pass_yards": 1}
        assert d["parsed"] == 1 and d["players"] == 1

    def test_an_out_of_season_feed_says_which_problem_it_is(self, src):
        d = src([line(sport="mlb")]).probe()
        assert d["nfl_items"] == 0 and "none were NFL" in d["note"]

    def test_lines_that_arrive_but_do_not_parse_are_flagged(self, src):
        d = src([line(outcome_type="moneyline")]).probe()
        assert d["nfl_items"] == 1 and d["parsed"] == 0
        assert "none parsed" in d["note"]

    def test_an_unreachable_feed_reports_the_error(self, monkeypatch):
        SleeperNFLSource.clear()
        monkeypatch.setattr(
            SleeperNFLSource, "_get",
            lambda self, url, params=None, timeout=None: (_ for _ in ()).throw(
                ConnectionError("refused")))
        d = SleeperNFLSource().probe()
        assert d["reachable"] is False and "ConnectionError" in d["error"]


class TestLabels:
    def test_a_market_id_is_made_readable_without_being_reinterpreted(self):
        assert _label("pass_yards") == "Pass yards"
        assert _label("some_new_market_2027") == "Some new market 2027"

    def test_an_empty_market_still_renders(self):
        assert _label(None) == "—"


class TestUnreachableIsNotEmpty:
    """"Sleeper is down" and "nobody offers a line on him" are both an empty
    list, and telling a reader the second when it was the first states a fact
    about a player that is really a fact about the network."""

    def test_a_failed_fetch_records_why(self, monkeypatch):
        SleeperNFLSource.clear()
        monkeypatch.setattr(
            SleeperNFLSource, "_get",
            lambda self, url, params=None, timeout=None: (_ for _ in ()).throw(
                ConnectionError("refused")))
        s = SleeperNFLSource()
        assert s.search("mahomes") == []
        assert s.last_error and "ConnectionError" in s.last_error

    def test_a_genuine_miss_records_nothing(self, src):
        s = src([line()])
        assert s.search("nobody") == []
        assert s.last_error is None, "the feed answered; the name just wasn't in it"


class TestTheDirectoryOutage:
    """The failure that made a real player vanish from a working search.

    A prop whose player can't be named is dropped, and the directory is what
    names them — so a directory that fails takes the entire board with it. It
    used to cache that failure permanently, turning one slow fetch into "every
    search returns nothing until the container restarts", and it did it in
    silence: the lines arrived fine, so nothing looked broken.
    """

    def _flaky_directory(self, monkeypatch, fail_times: list):
        """Directory raises while fail_times says so; lines always work."""
        calls = {"directory": 0}

        def fake_get(self, url, params=None, timeout=None):
            if "players" in url:
                calls["directory"] += 1
                if fail_times and calls["directory"] <= fail_times[0]:
                    raise ConnectionError("timed out")
                return DIRECTORY
            return [line()]

        monkeypatch.setattr(SleeperNFLSource, "_get", fake_get)
        return calls

    def test_a_failed_directory_is_not_cached_forever(self, monkeypatch):
        """The whole bug in one test. First fetch fails, second succeeds, and
        the second has to actually be attempted."""
        SleeperNFLSource.clear()
        monkeypatch.setattr(
            "thebeast.data.sources.sleeper_nfl.DIRECTORY_RETRY_SECONDS", 0.0)
        calls = self._flaky_directory(monkeypatch, [1])

        assert SleeperNFLSource().search("mahomes") == [], "first attempt fails"
        SleeperNFLSource._props_cache = None          # let the lines refetch
        assert len(SleeperNFLSource().search("mahomes")) == 1, "and then recovers"
        assert calls["directory"] == 2

    def test_a_failed_directory_is_not_retried_on_every_request(self, monkeypatch):
        """Not caching the failure must not mean hammering a struggling
        upstream once per keystroke."""
        SleeperNFLSource.clear()
        calls = self._flaky_directory(monkeypatch, [99])
        for _ in range(5):
            SleeperNFLSource._props_cache = None
            SleeperNFLSource().search("mahomes")
        assert calls["directory"] == 1, "one attempt, then the cooldown holds"

    def test_a_naming_outage_is_reported_as_one(self, monkeypatch):
        """Not as "no prop on offer for that name", which is a statement about
        a player when the truth is a statement about our directory."""
        SleeperNFLSource.clear()
        self._flaky_directory(monkeypatch, [99])
        s = SleeperNFLSource()
        assert s.search("mahomes") == []
        assert s.last_error and "player directory is unavailable" in s.last_error

    def test_the_probe_counts_what_each_filter_threw_away(self, src):
        """Every drop looks identical from the page. The counts are the only
        thing that separates a parser bug from an empty board."""
        items = [line(),
                 line(status="suspended"),
                 line(outcome_type="moneyline"),
                 line(subject_type="team"),
                 line(player_id="unknown-id-9999")]
        d = src(items).probe()
        assert d["parsed"] == 1
        assert d["dropped"]["status=suspended"] == 1
        assert d["dropped"]["outcome_type=moneyline"] == 1
        assert d["dropped"]["not_a_player_subject"] == 1
        assert d["dropped"]["no_name_resolved"] == 1

    def test_the_probe_names_the_directory_when_that_is_the_problem(self, monkeypatch):
        SleeperNFLSource.clear()
        self._flaky_directory(monkeypatch, [99])
        d = SleeperNFLSource().probe()
        assert d["nfl_items"] == 1 and d["parsed"] == 0
        assert d["dropped"]["no_name_resolved"] == 1
        assert "nothing could name the player" in d["note"]
        assert d["directory_error"] and "ConnectionError" in d["directory_error"]
