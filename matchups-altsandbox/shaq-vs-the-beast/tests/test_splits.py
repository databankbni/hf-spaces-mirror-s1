"""Reading a book's published splits, and what they add over line movement.

The parser is header-driven on purpose, so the tests are mostly about the two
ways this can go wrong quietly: reading a column that isn't what we think it
is, and pinning a split on the wrong game. Both produce a confident wrong
answer, which is worse than the blank panel we get from bailing out.

The fixture below is my assumption about the page's shape, not a capture of it
— the live page couldn't be reached from where this was written. So these tests
prove the logic is right given that shape; `diagnose()` is what proves the
shape. Both matter, and only one of them can be a unit test.
"""
from __future__ import annotations

from datetime import date

import pytest

from thebeast.data.repository import SQLiteRepository
from thebeast.data.sources import splits as splits_mod
from thebeast.data.sources.splits import GameSplits, VSiNSplitsSource, team_of

DAY = date(2026, 8, 8)
GAMES = [f"{DAY.isoformat()}-CWS-BAL", f"{DAY.isoformat()}-NYM-PHI"]


def page(rows: str, headers: str = None) -> str:
    headers = headers or (
        "<tr><th>Team</th><th>ML Handle</th><th>ML Bets</th>"
        "<th>Total Handle</th><th>Total Bets</th></tr>")
    return f"<html><body><table>{headers}{rows}</table></body></html>"


def row(team: str, *cells: str) -> str:
    return "<tr><td>" + team + "</td>" + "".join(
        f"<td>{c}</td>" for c in cells) + "</tr>"


@pytest.fixture
def source(monkeypatch):
    VSiNSplitsSource.clear()

    def install(html):
        monkeypatch.setattr(VSiNSplitsSource, "_get", lambda self: html)
        return VSiNSplitsSource()
    return install


@pytest.fixture
def repo(tmp_path):
    return SQLiteRepository(str(tmp_path / "s.db"))


class TestTeamResolution:
    """Where a wrong answer would be silent and total."""

    def test_it_reads_the_forms_a_page_actually_uses(self):
        for token in ("BAL", "Orioles", "Baltimore", "baltimore orioles"):
            assert team_of(token) == "BAL", token

    def test_it_keeps_the_two_new_york_clubs_apart(self):
        assert team_of("NY Yankees") == "NYY"
        assert team_of("NY Mets") == "NYM"
        assert team_of("New York") is None, "ambiguous is not a guess"

    def test_it_keeps_the_two_chicago_clubs_apart(self):
        assert team_of("Chi White Sox") == "CWS"
        assert team_of("Cubs") == "CHC"

    def test_it_maps_the_abbreviations_that_differ_from_ours(self):
        assert team_of("CHW") == "CWS"
        assert team_of("ARI") == "AZ"
        assert team_of("OAK") == "ATH"

    def test_an_unknown_token_is_none_rather_than_a_near_match(self):
        assert team_of("Highlanders") is None
        assert team_of("") is None

    def test_the_slate_narrows_the_field(self):
        """Only teams playing can match, so a stray row can't land on a game."""
        assert team_of("Cubs", allowed={"BAL", "CWS"}) is None
        assert team_of("Cubs", allowed={"CHC"}) == "CHC"


class TestParsing:
    def test_it_reads_handle_and_tickets_for_both_markets(self, source):
        src = source(page(row("Baltimore", "68%", "55%", "61%", "58%")))
        out = src.fetch(DAY, GAMES)
        assert len(out) == 1
        s = out[0]
        assert s.game_id == f"{DAY.isoformat()}-CWS-BAL"
        assert (s.ml_home_handle, s.ml_home_bets) == (68.0, 55.0)
        assert (s.total_over_handle, s.total_over_bets) == (61.0, 58.0)

    def test_an_away_row_is_flipped_to_the_home_share(self, source):
        """Stored home-relative so one number is the whole split. A row for the
        road team says 30% and that is 70% home, not 30%."""
        src = source(page(row("Chi White Sox", "30%", "45%", "61%", "58%")))
        s = src.fetch(DAY, GAMES)[0]
        assert s.ml_home_handle == 70.0 and s.ml_home_bets == 55.0
        assert s.total_over_handle == 61.0, "the total is over-relative either way"

    def test_columns_come_from_the_header_not_the_position(self, source):
        """The whole point of the design: swap the columns round and the
        numbers still land in the right fields."""
        src = source(page(
            row("Baltimore", "55%", "68%", "58%", "61%"),
            headers=("<tr><th>Team</th><th>ML Bets</th><th>ML Handle</th>"
                     "<th>Total Tickets</th><th>Total Money</th></tr>")))
        s = src.fetch(DAY, GAMES)[0]
        assert s.ml_home_handle == 68.0 and s.ml_home_bets == 55.0
        assert s.total_over_handle == 61.0 and s.total_over_bets == 58.0

    def test_a_table_we_cannot_read_the_headers_of_is_declined(self, source):
        """Bailing out gives an empty panel. Guessing at positions would give a
        wrong one, and nothing downstream could tell."""
        src = source(page(row("Baltimore", "68%", "55%"),
                          headers="<tr><th>Team</th><th>A</th><th>B</th></tr>"))
        assert src.fetch(DAY, GAMES) == []

    def test_a_team_not_on_the_slate_is_skipped(self, source):
        src = source(page(row("Cubs", "68%", "55%", "61%", "58%")))
        assert src.fetch(DAY, GAMES) == []

    def test_several_games_parse_independently(self, source):
        src = source(page(row("Baltimore", "68%", "55%", "61%", "58%")
                          + row("Philadelphia", "40%", "42%", "55%", "51%")))
        got = {s.game_id: s for s in src.fetch(DAY, GAMES)}
        assert len(got) == 2
        assert got[f"{DAY.isoformat()}-NYM-PHI"].ml_home_handle == 40.0

    def test_a_row_with_no_percentages_yields_nothing(self, source):
        src = source(page(row("Baltimore", "—", "—", "—", "—")))
        assert src.fetch(DAY, GAMES) == []

    def test_a_nonsense_percentage_is_dropped_not_stored(self, source):
        src = source(page(row("Baltimore", "680%", "55%", "61%", "58%")))
        s = src.fetch(DAY, GAMES)[0]
        assert s.ml_home_handle is None, "out of range is not a reading"
        assert s.ml_home_bets == 55.0, "the rest of the row still counts"

    def test_an_unreachable_page_yields_nothing(self, monkeypatch):
        VSiNSplitsSource.clear()
        monkeypatch.setattr(
            VSiNSplitsSource, "_get",
            lambda self: (_ for _ in ()).throw(ConnectionError("down")))
        assert VSiNSplitsSource().fetch(DAY, GAMES) == []

    def test_an_empty_slate_parses_nothing(self, source):
        src = source(page(row("Baltimore", "68%", "55%", "61%", "58%")))
        assert src.fetch(DAY, []) == []

    def test_it_is_cached_per_day(self, monkeypatch):
        VSiNSplitsSource.clear()
        calls = {"n": 0}
        html = page(row("Baltimore", "68%", "55%", "61%", "58%"))

        def counting(self):
            calls["n"] += 1
            return html

        monkeypatch.setattr(VSiNSplitsSource, "_get", counting)
        src = VSiNSplitsSource()
        for _ in range(5):
            src.fetch(DAY, GAMES)
        assert calls["n"] == 1


class TestDiagnose:
    """The part that makes an unverifiable scraper fixable."""

    def test_it_reports_the_headers_it_matched(self, source):
        src = source(page(row("Baltimore", "68%", "55%", "61%", "58%")))
        d = src.diagnose(DAY, GAMES)
        assert d["reachable"] and d["headers_found"]
        assert d["parsed"][0]["ml_home_handle"] == 68.0

    def test_unmatched_headers_come_back_with_the_rows_to_fix_them_from(self, source):
        src = source(page(row("Baltimore", "68%", "55%"),
                          headers="<tr><th>Team</th><th>A</th><th>B</th></tr>"))
        d = src.diagnose(DAY, GAMES)
        assert not d["headers_found"]
        assert d["sample_rows"], "the evidence needed to correct the keywords"
        assert "_MARKET_WORDS" in d["note"]

    def test_a_readable_page_with_no_matching_teams_says_which_problem_it_is(self, source):
        src = source(page(row("Cubs", "68%", "55%", "61%", "58%")))
        d = src.diagnose(DAY, GAMES)
        assert d["headers_found"] and not d["parsed"]
        assert "_TEAM_FORMS" in d["note"]

    def test_an_unreachable_page_reports_the_error(self, monkeypatch):
        VSiNSplitsSource.clear()
        monkeypatch.setattr(
            VSiNSplitsSource, "_get",
            lambda self: (_ for _ in ()).throw(ConnectionError("refused")))
        d = VSiNSplitsSource().diagnose(DAY, GAMES)
        assert d["reachable"] is False and "ConnectionError" in d["error"]


class TestStorage:
    def _split(self, **kw):
        base = {"game_id": GAMES[0], "home": "BAL", "away": "CWS",
                "book": "draftkings", "ml_home_handle": 68.0,
                "ml_home_bets": 55.0, "total_over_handle": 61.0,
                "total_over_bets": 58.0}
        base.update(kw)
        return base

    def test_an_unchanged_split_is_not_stored_twice(self, repo):
        assert repo.save_splits_snapshot(GAMES[0], DAY, "T1", self._split())
        assert not repo.save_splits_snapshot(GAMES[0], DAY, "T2", self._split())
        assert len(repo.splits_history(GAMES[0])) == 1

    def test_a_moved_split_is_stored(self, repo):
        repo.save_splits_snapshot(GAMES[0], DAY, "T1", self._split())
        assert repo.save_splits_snapshot(GAMES[0], DAY, "T2",
                                         self._split(ml_home_handle=74.0))
        assert len(repo.splits_history(GAMES[0])) == 2

    def test_the_latest_is_the_one_that_closed(self, repo):
        repo.save_splits_snapshot(GAMES[0], DAY, "T1", self._split())
        repo.save_splits_snapshot(GAMES[0], DAY, "T2",
                                  self._split(ml_home_handle=74.0))
        assert repo.latest_splits(GAMES[0])["ml_home_handle"] == 74.0

    def test_a_game_with_no_splits_has_none(self, repo):
        assert repo.latest_splits(GAMES[0]) is None

    def test_record_splits_counts_what_it_wrote(self, repo):
        from thebeast.market import record_splits

        rows = [GameSplits(GAMES[0], "BAL", "CWS", ml_home_handle=68.0),
                GameSplits(GAMES[1], "PHI", "NYM", ml_home_handle=40.0)]
        assert record_splits(repo, DAY, rows) == 2
        assert record_splits(repo, DAY, rows) == 0, "unchanged, so nothing new"


class TestConfigurableUrl:
    def test_the_page_address_can_be_changed_without_a_deploy(self, monkeypatch):
        """A scraper's most likely breakage is the URL, and waiting on a code
        push to fix a URL is silly."""
        monkeypatch.setenv("VSIN_SPLITS_URL", "https://example.invalid/x")
        import importlib
        reloaded = importlib.reload(splits_mod)
        try:
            assert reloaded.SPLITS_URL == "https://example.invalid/x"
        finally:
            monkeypatch.delenv("VSIN_SPLITS_URL", raising=False)
            importlib.reload(splits_mod)


class TestTheBooksOwnPrice:
    """Taking the line from the same book that published the split.

    A share of DraftKings' handle read against a consensus price is two
    different markets described as one: the hold would be a hold nobody
    quoted, and the movement would be movement that money never reacted to.
    """

    def _page(self, rows):
        return page(rows, headers=(
            "<tr><th>Team</th><th>ML</th><th>ML Handle</th><th>ML Bets</th>"
            "<th>Total</th><th>Total Handle</th><th>Total Bets</th></tr>"))

    def test_a_bare_market_column_is_the_price(self, source):
        """"ML" is the moneyline; "ML Handle" is a share of it. A column headed
        by a market and nothing else is the market itself."""
        src = source(self._page(
            row("Baltimore", "-155", "68%", "55%", "8.5", "61%", "58%")
            + row("Chi White Sox", "+130", "32%", "45%", "8.5", "61%", "58%")))
        s = src.fetch(DAY, GAMES)[0]
        assert s.ml_home_price == -155 and s.ml_away_price == 130
        assert s.total_line == 8.5
        assert s.ml_home_handle == 68.0, "the shares still parse"

    def test_the_price_becomes_a_line_the_recorder_understands(self, source):
        src = source(self._page(
            row("Baltimore", "-155", "68%", "55%", "8.5", "61%", "58%")
            + row("Chi White Sox", "+130", "32%", "45%", "8.5", "61%", "58%")))
        line = src.fetch(DAY, GAMES)[0].as_line()
        assert line.book == "draftkings" and line.usable
        assert line.home_ml == -155 and line.total == 8.5

    def test_a_percentage_is_never_mistaken_for_a_price(self, source):
        src = source(self._page(
            row("Baltimore", "68%", "68%", "55%", "8.5", "61%", "58%")))
        assert src.fetch(DAY, GAMES)[0].ml_home_price is None

    def test_a_page_with_no_prices_still_gives_splits(self, source):
        src = source(page(row("Baltimore", "68%", "55%", "61%", "58%")))
        s = src.fetch(DAY, GAMES)[0]
        assert s.has_price is False and s.ml_home_handle == 68.0


class TestOneBookPerGame:
    def _line(self, gid, book, home_ml):
        from thebeast.data.sources.lines import GameLine

        return GameLine(game_id=gid, home="BAL", away="CWS", home_ml=home_ml,
                        away_ml=130, total=8.5, book=book)

    def test_a_second_book_cannot_write_into_the_first_ones_history(self, repo):
        """Two books rarely post the same number, so alternating between them
        would record a price change on every pass — and every one of those
        would read as money arriving. Movement across books isn't movement."""
        from thebeast.market import game_market, record

        gid = GAMES[0]
        assert record(repo, DAY, [self._line(gid, "draftkings", -155)]) == 1
        assert record(repo, DAY, [self._line(gid, "consensus", -150)]) == 0
        m = game_market(repo, gid)
        assert m.snapshots == 1 and m.closed["book"] == "draftkings"
        assert m.money_on == {}, "no invented movement"

    def test_the_same_book_still_records_its_moves(self, repo):
        from thebeast.market import game_market, record

        gid = GAMES[0]
        record(repo, DAY, [self._line(gid, "draftkings", -155)])
        record(repo, DAY, [self._line(gid, "draftkings", -185)])
        assert game_market(repo, gid).money_on["moneyline"]["side"] == "home"
