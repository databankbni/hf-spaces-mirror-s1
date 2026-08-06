"""Injury filtering: keeping unavailable players out of projected lineups.

The bug: projected batting orders are the season's nine most-used hitters,
which says who bats and nothing about who is available. A player who went on
the IL in July stayed in the lineup, kept being simulated, and kept being
quoted in the ranked plays — Aaron Judge was getting a home-run probability
while on the injured list.

The test is active-roster membership rather than status-code parsing. The
active roster is the complete list of players eligible to appear tonight, so a
projected hitter missing from it cannot play — whatever the reason, and whatever
new status codes MLB invents. The reason is fetched separately and only for
display, so a change upstream costs a nice string rather than a right answer.

Everything here runs against recorded response shapes rather than the network.
"""
from __future__ import annotations

from thebeast.data.sources.availability import (
    MIN_ROSTER, MLBAvailabilitySource, TeamRoster)
from thebeast.pipeline import (available_order, resolve_lineups,
                               _drop_unavailable, _season_of)


def entry(pid: int, code: str = "A", description: str = "Active") -> dict:
    return {"person": {"id": pid, "fullName": f"player {pid}"},
            "status": {"code": code, "description": description}}


def full_roster(ids) -> dict:
    return {"roster": [entry(i) for i in ids]}


ACTIVE = list(range(700000, 700030))    # 30 ids — a plausible active roster
PROJ = list(range(600001, 600010))      # a projected nine
SUB_A, SUB_B = 610001, 610002           # bench candidates


class TestRosterFetch:
    def _patch(self, monkeypatch, roster_payload, teams=None, full=None):
        MLBAvailabilitySource.clear()

        def fake_get(self, url, params):
            if url.endswith("/teams"):
                return teams if teams is not None else {
                    "teams": [{"abbreviation": "NYY", "id": 147}]}
            if params.get("rosterType") == "fullRoster":
                if full is None:
                    raise ConnectionError("no full roster in this test")
                return full
            return roster_payload

        monkeypatch.setattr(MLBAvailabilitySource, "_get", fake_get)
        return MLBAvailabilitySource()

    def test_the_active_roster_is_who_can_play(self, monkeypatch):
        src = self._patch(monkeypatch, full_roster(ACTIVE))
        r = src.roster("NYY")
        assert r.usable
        assert r.can_play(ACTIVE[0]) and not r.can_play(999999)

    def test_an_unreachable_source_is_unknown_not_empty(self, monkeypatch):
        """The distinction the whole design rests on. Treating a failure as
        'nobody can play' would empty every lineup on the slate."""
        MLBAvailabilitySource.clear()

        def boom(self, url, params):
            raise ConnectionError("statsapi is down")

        monkeypatch.setattr(MLBAvailabilitySource, "_get", boom)
        assert MLBAvailabilitySource().roster("NYY").usable is False

    def test_an_implausibly_short_roster_is_not_trusted(self, monkeypatch):
        """An active roster is 26. Eight is a broken response, not a decimated
        club, and acting on it would strip real hitters out of every lineup."""
        src = self._patch(monkeypatch, full_roster(range(100, 108)))
        assert src.roster("NYY").usable is False

    def test_a_roster_at_the_threshold_is_trusted(self, monkeypatch):
        src = self._patch(monkeypatch, full_roster(range(100, 100 + MIN_ROSTER)))
        assert src.roster("NYY").usable is True

    def test_a_malformed_entry_is_skipped_not_fatal(self, monkeypatch):
        payload = full_roster(ACTIVE)
        payload["roster"] += [{"person": {}}, {"nonsense": True}]
        src = self._patch(monkeypatch, payload)
        assert src.roster("NYY").usable

    def test_a_team_it_cannot_identify_is_unknown(self, monkeypatch):
        src = self._patch(monkeypatch, full_roster(ACTIVE), teams={"teams": []})
        assert src.roster("NYY").usable is False

    def test_the_roster_is_cached_per_team(self, monkeypatch):
        calls = {"n": 0}
        MLBAvailabilitySource.clear()

        def counting(self, url, params):
            calls["n"] += 1
            if url.endswith("/teams"):
                return {"teams": [{"abbreviation": "NYY", "id": 147}]}
            return full_roster(ACTIVE)

        monkeypatch.setattr(MLBAvailabilitySource, "_get", counting)
        src = MLBAvailabilitySource()
        for _ in range(5):
            src.roster("NYY")
        assert calls["n"] == 2, "teams once, roster once — the rest are cached"


class TestReasons:
    """Labels are for display only. Availability never depends on them."""

    def _patch(self, monkeypatch, full):
        MLBAvailabilitySource.clear()

        def fake_get(self, url, params):
            if url.endswith("/teams"):
                return {"teams": [{"abbreviation": "NYY", "id": 147}]}
            if params.get("rosterType") == "fullRoster":
                return full
            return full_roster(ACTIVE)

        monkeypatch.setattr(MLBAvailabilitySource, "_get", fake_get)
        return MLBAvailabilitySource()

    def test_a_known_code_becomes_readable_words(self, monkeypatch):
        src = self._patch(monkeypatch, {"roster": [
            entry(592450, "D10", "10-Day Injured List")]})
        assert src.label_absences("NYY", [592450]) == {592450: "10-day injured list"}

    def test_an_unknown_code_falls_back_to_its_description(self, monkeypatch):
        src = self._patch(monkeypatch, {"roster": [
            entry(592450, "ZZ", "Some New Status")]})
        assert src.label_absences("NYY", [592450]) == {592450: "Some New Status"}

    def test_a_failed_lookup_costs_the_label_not_the_answer(self, monkeypatch):
        MLBAvailabilitySource.clear()

        def fake_get(self, url, params):
            if url.endswith("/teams"):
                return {"teams": [{"abbreviation": "NYY", "id": 147}]}
            if params.get("rosterType") == "fullRoster":
                raise ConnectionError("down")
            return full_roster(ACTIVE)

        monkeypatch.setattr(MLBAvailabilitySource, "_get", fake_get)
        src = MLBAvailabilitySource()
        assert src.label_absences("NYY", [592450]) == {}
        # The player is out regardless — membership already settled it.
        assert src.roster("NYY").can_play(592450) is False

    def test_asking_about_nobody_makes_no_call(self, monkeypatch):
        src = self._patch(monkeypatch, {"roster": []})
        assert src.label_absences("NYY", []) == {}


class FakeBatter:
    def __init__(self, pa, name):
        self.pa = pa
        self.name = name


class FakeRepo:
    """Ids are realistic six-digit ones on purpose: anything under 100,000 is a
    placeholder to this code now, and a test using 1..9 would be exercising the
    placeholder path while claiming to test the filter."""

    def __init__(self, pa_by_id, lineups=None, unnamed=()):
        self._pa = pa_by_id
        self._lineups = lineups or {}
        self._unnamed = set(unnamed)

    def get_batter(self, pid, season):
        pa = self._pa.get(pid)
        if pa is None:
            return None
        return FakeBatter(pa, None if pid in self._unnamed else f"Player {pid}")

    def get_pitcher(self, pid, season):
        return None

    def get_lineup(self, game_id, team):
        return self._lineups.get((game_id, team))


def source_with(active):
    class Src:
        def roster(self, team):
            return TeamRoster(set(active))
    return Src()


class TestFilteringTheOrder:
    PROJECTED = list(range(600001, 600010))   # nine real-looking ids

    def test_an_injured_player_is_replaced(self):
        """The reported bug, in one test. 3 is off the active roster."""
        repo = FakeRepo({i: 500 for i in PROJ} | {SUB_A: 300})
        active = [p for p in PROJ if p != 600003] + [SUB_A] + list(range(700000, 700025))
        order = available_order(repo, "NYY", self.PROJECTED, 2026,
                                source=source_with(active))
        assert 600003 not in order and SUB_A in order and len(order) == 9

    def test_the_replacement_is_the_best_hitter_available(self):
        repo = FakeRepo({i: 500 for i in PROJ} | {SUB_A: 100, SUB_B: 400})
        active = [p for p in PROJ if p != 600003] + [SUB_A, SUB_B] + list(range(700000, 700025))
        order = available_order(repo, "NYY", self.PROJECTED, 2026,
                                source=source_with(active))
        assert SUB_B in order and SUB_A not in order

    def test_a_replacement_with_no_statline_is_not_promoted(self):
        """The simulator falls back to league-average rates for a player it has
        nothing on, which would quietly invent a hitter. With nobody eligible,
        the slot keeps its occupant — a lineup that simulates with a doubtful
        name beats a game that doesn't simulate at all."""
        repo = FakeRepo({i: 500 for i in PROJ})     # SUB_A has no statline
        active = [p for p in PROJ if p != 600003] + [SUB_A] + list(range(700000, 700025))
        order = available_order(repo, "NYY", self.PROJECTED, 2026,
                                source=source_with(active))
        assert SUB_A not in order
        assert order == self.PROJECTED and len(order) == 9

    def test_a_healthy_lineup_is_untouched(self):
        repo = FakeRepo({i: 500 for i in PROJ})
        active = list(PROJ) + list(range(700000, 700025))
        order = available_order(repo, "NYY", self.PROJECTED, 2026,
                                source=source_with(active))
        assert order == self.PROJECTED

    def test_an_unknown_roster_leaves_the_lineup_alone(self):
        """No network, no change — the behaviour before this check existed."""
        order = available_order(FakeRepo({}), "NYY", self.PROJECTED, 2026,
                                source=source_with([]))
        assert order == self.PROJECTED

    def test_a_raising_source_leaves_the_lineup_alone(self):
        class Angry:
            def roster(self, team):
                raise RuntimeError("boom")
        order = available_order(FakeRepo({}), "NYY", self.PROJECTED, 2026,
                                source=Angry())
        assert order == self.PROJECTED

    def test_several_out_at_once(self):
        repo = FakeRepo({i: 500 for i in PROJ} | {SUB_A: 200, SUB_B: 250})
        active = [p for p in PROJ if p not in (600002, 600005)] + [SUB_A, SUB_B] + list(range(700000, 700025))
        order = available_order(repo, "NYY", self.PROJECTED, 2026,
                                source=source_with(active))
        assert 600002 not in order and 600005 not in order
        assert {SUB_A, SUB_B} <= set(order) and len(order) == 9


class TestFilteringOnRead:
    """Where the filter lives, and why it lives there.

    Filtering at write time meant doing it in every writer, and there was more
    than one — `_fill_roster` on the upcoming route wrote a raw projection
    straight past the check, so injured players kept appearing however carefully
    `ensure_lineups` was patched. `resolve_lineups` is the single door every
    consumer already comes through.
    """

    def _card(self, order, confirmed=False, team="NYY"):
        from thebeast.data.models import LineupCard
        return LineupCard(game_id="2026-08-03-BOS-NYY", team_id=team,
                          batting_order=list(order), starter_id=0,
                          bullpen_ids=[], confirmed=confirmed, confirmed_at=None)

    def _patch_roster(self, monkeypatch, active):
        monkeypatch.setattr(
            "thebeast.data.sources.availability.MLBAvailabilitySource.roster",
            lambda self, team: TeamRoster(set(active)))

    def test_a_projected_card_is_filtered(self, monkeypatch):
        repo = FakeRepo({i: 500 for i in PROJ} | {SUB_A: 300})
        self._patch_roster(
            monkeypatch, [p for p in PROJ if p != 600003] + [SUB_A] + list(range(700000, 700025)))
        out = _drop_unavailable(repo, self._card(PROJ), 2026)
        assert 600003 not in out.batting_order and SUB_A in out.batting_order

    def test_a_confirmed_card_is_never_touched(self, monkeypatch):
        """The team has posted who is playing. No roster endpoint improves on
        that, and second-guessing it would be strictly worse."""
        repo = FakeRepo({i: 500 for i in PROJ})
        self._patch_roster(monkeypatch, range(700000, 700030))
        card = self._card(PROJ, confirmed=True)
        assert _drop_unavailable(repo, card, 2026) is card

    def test_synthetic_placeholders_are_left_alone(self, monkeypatch):
        """Not people — there is nothing to look up, and stripping them would
        empty the lineup entirely."""
        called = {"n": 0}

        def counting(self, team):
            called["n"] += 1
            return TeamRoster(set(range(700000, 700030)))

        monkeypatch.setattr(
            "thebeast.data.sources.availability.MLBAvailabilitySource.roster",
            counting)
        card = self._card(range(9_000_001, 9_000_010))
        assert _drop_unavailable(FakeRepo({}), card, 2026) is card
        assert called["n"] == 0

    def test_the_stored_projection_is_not_rewritten(self, monkeypatch):
        """Read-time filtering keeps the record honest: the stored card stays
        'who usually bats', and availability is applied fresh each time."""
        repo = FakeRepo({i: 500 for i in PROJ} | {SUB_A: 300})
        self._patch_roster(
            monkeypatch, [p for p in PROJ if p != 600003] + [SUB_A] + list(range(700000, 700025)))
        card = self._card(PROJ)
        out = _drop_unavailable(repo, card, 2026)
        assert out is not card
        assert card.batting_order == list(PROJ), "original untouched"

    def test_resolve_lineups_applies_it(self, monkeypatch):
        cards = {("2026-08-03-BOS-NYY", "NYY"): self._card(PROJ),
                 ("2026-08-03-BOS-NYY", "BOS"): self._card(PROJ, team="BOS")}
        repo = FakeRepo({i: 500 for i in PROJ} | {SUB_A: 300}, cards)
        self._patch_roster(
            monkeypatch, [p for p in PROJ if p != 600003] + [SUB_A] + list(range(700000, 700025)))
        home, away = resolve_lineups("2026-08-03-BOS-NYY", repo, "NYY", "BOS")
        assert 600003 not in home.batting_order
        assert 600003 not in away.batting_order

    def test_it_can_be_switched_off(self, monkeypatch):
        """For callers that must not make a network call, and for tests."""
        def boom(self, team):
            raise AssertionError("must not be consulted")

        monkeypatch.setattr(
            "thebeast.data.sources.availability.MLBAvailabilitySource.roster",
            boom)
        cards = {("2026-08-03-BOS-NYY", "NYY"): self._card(PROJ)}
        repo = FakeRepo({}, cards)
        home, _ = resolve_lineups("2026-08-03-BOS-NYY", repo, "NYY", "BOS",
                                  check_availability=False)
        assert home.batting_order == list(PROJ)


class TestSeasonFromGameId:
    def test_it_reads_the_year(self):
        assert _season_of("2026-08-03-BOS-NYY") == 2026

    def test_a_malformed_id_falls_back_to_now(self):
        from datetime import date
        assert _season_of("nonsense") == date.today().year


class TestBackoff:
    def test_a_failing_source_is_not_retried_on_every_simulation(self, monkeypatch):
        """Fifteen games, thirty teams, one host that's down. Without a
        circuit-breaker the slate wears the connect timeout thirty times over."""
        calls = {"n": 0}
        MLBAvailabilitySource.clear()

        def boom(self, url, params):
            calls["n"] += 1
            raise ConnectionError("down")

        monkeypatch.setattr(MLBAvailabilitySource, "_get", boom)
        src = MLBAvailabilitySource()
        for _ in range(20):
            assert src.roster("NYY").usable is False
        assert calls["n"] == 1

    def test_one_team_failing_does_not_suppress_another(self, monkeypatch):
        MLBAvailabilitySource.clear()

        def selective(self, url, params):
            if url.endswith("/teams"):
                return {"teams": [{"abbreviation": "NYY", "id": 147},
                                  {"abbreviation": "BOS", "id": 111}]}
            if "/147/" in url:
                raise ConnectionError("just this one")
            return full_roster(ACTIVE)

        monkeypatch.setattr(MLBAvailabilitySource, "_get", selective)
        src = MLBAvailabilitySource()
        assert src.roster("NYY").usable is False
        assert src.roster("BOS").usable is True


class TestDiagnose:
    """The probe. Filtering is invisible when it works and invisible when it
    doesn't, and this app can't reach statsapi from every environment it's
    developed in — so the difference has to be inspectable from where it runs."""

    def test_it_reports_a_working_source(self, monkeypatch):
        MLBAvailabilitySource.clear()

        def ok(self, url, params):
            if url.endswith("/teams"):
                return {"teams": [{"abbreviation": "NYY", "id": 147}]}
            return full_roster(ACTIVE)

        monkeypatch.setattr(MLBAvailabilitySource, "_get", ok)
        out = MLBAvailabilitySource().diagnose("NYY")
        assert out["usable"] is True
        assert out["active_roster_size"] == len(ACTIVE)
        assert out["effect"] == "filtering active"

    def test_it_says_when_nothing_is_being_filtered(self, monkeypatch):
        MLBAvailabilitySource.clear()

        def boom(self, url, params):
            raise ConnectionError("down")

        monkeypatch.setattr(MLBAvailabilitySource, "_get", boom)
        out = MLBAvailabilitySource().diagnose("NYY")
        assert out["usable"] is False
        assert "no filtering" in out["effect"]
        assert out["teams_endpoint"] == "unreachable"


class TestTheAssistantIsTold:
    """The screenshot that started this: the assistant recommending an over on
    Aaron Judge's home runs while he was on the injured list. Filtering the
    lineup stops him being simulated; the tool payload has to say he's out, or
    a question answered from names can still land on him."""

    def _repo(self, order):
        class Repo:
            def get_lineup(self, game_id, team):
                class Card:
                    batting_order = order
                return Card()
        return Repo()

    def _patch(self, monkeypatch, active, reasons=None):
        monkeypatch.setattr(
            "thebeast.data.sources.availability.MLBAvailabilitySource.roster",
            lambda self, team: TeamRoster(set(active)))
        monkeypatch.setattr(
            "thebeast.data.sources.availability.MLBAvailabilitySource"
            ".label_absences",
            lambda self, team, ids: dict(reasons or {}))

    def test_a_missing_regular_is_reported_with_the_reason(self, monkeypatch):
        from thebeast import chat

        self._patch(monkeypatch, [1, 2] + list(range(200, 225)),
                    {3: "10-day injured list"})
        monkeypatch.setattr("thebeast.data.names.player_names",
                            lambda repo, ids, season: {3: "Aaron Judge"})
        out = chat._unavailable(self._repo([1, 2, 3]), ["NYY"], 2026)
        assert out["NYY"] == [{"name": "Aaron Judge",
                               "reason": "10-day injured list"}]

    def test_a_missing_reason_still_reports_the_absence(self, monkeypatch):
        from thebeast import chat

        self._patch(monkeypatch, [1, 2] + list(range(200, 225)))
        monkeypatch.setattr("thebeast.data.names.player_names",
                            lambda repo, ids, season: {3: "Aaron Judge"})
        out = chat._unavailable(self._repo([1, 2, 3]), ["NYY"], 2026)
        assert out["NYY"][0]["reason"] == "not on the active roster"

    def test_an_unusable_roster_reports_nothing(self, monkeypatch):
        """Rather than reporting the whole lineup as unavailable."""
        from thebeast import chat

        self._patch(monkeypatch, [])
        assert chat._unavailable(self._repo([1, 2, 3]), ["NYY"], 2026) == {}

    def test_a_broken_lookup_costs_the_note_not_the_projection(self, monkeypatch):
        from thebeast import chat

        monkeypatch.setattr(
            "thebeast.data.sources.availability.MLBAvailabilitySource.roster",
            lambda self, team: (_ for _ in ()).throw(RuntimeError("down")))
        assert chat._unavailable(self._repo([1, 2, 3]), ["NYY"], 2026) == {}

    def test_a_fully_fit_team_says_nothing(self, monkeypatch):
        from thebeast import chat

        self._patch(monkeypatch, [1, 2, 3] + list(range(200, 225)))
        assert chat._unavailable(self._repo([1, 2, 3]), ["NYY"], 2026) == {}

    def test_the_prompt_forbids_recommending_an_unavailable_player(self):
        from thebeast import chat

        assert "unavailable" in chat.SYSTEM
        assert "Never recommend" in chat.SYSTEM


class TestNothingUnnamedGetsIn:
    """The regression from the first attempt at this.

    Substitutes had to have a statline and nothing more, so ids that nothing
    could resolve went into lineups and rendered as bare integers on the card.
    A row of numbers is worse than the injured player it replaced — if we can't
    say who someone is, he does not go in the lineup.
    """

    def test_a_nameless_candidate_is_not_promoted(self):
        # SUB_A has the most plate appearances and no name; SUB_B is nameable.
        repo = FakeRepo({i: 500 for i in PROJ} | {SUB_A: 900, SUB_B: 100},
                        unnamed=[SUB_A])
        active = ([p for p in PROJ if p != 600003] + [SUB_A, SUB_B]
                  + list(range(700000, 700025)))
        order = available_order(repo, "NYY", PROJ, 2026,
                                source=source_with(active))
        assert SUB_A not in order, "no bare ids in a lineup"
        assert SUB_B in order

    def test_an_unnameable_candidate_leaves_the_slot_as_it_was(self):
        """Not a bare integer, and not a short lineup either — a short one
        doesn't simulate at all, which loses the whole game rather than one
        name. The original occupant stays."""
        repo = FakeRepo({i: 500 for i in PROJ} | {SUB_A: 900}, unnamed=[SUB_A])
        active = ([p for p in PROJ if p != 600003] + [SUB_A]
                  + list(range(700000, 700025)))
        order = available_order(repo, "NYY", PROJ, 2026,
                                source=source_with(active))
        assert SUB_A not in order, "no bare ids"
        assert order == PROJ and len(order) == 9, "and no short lineup"


class TestPlaceholders:
    """Two conventions, and both have to be recognised together. Checking only
    the 9,000,000 block left the synthetic 1000/2000 nine to be 'filtered' —
    every id dropped as not-on-the-roster, then nine strangers promoted in."""

    def test_both_placeholder_blocks_are_recognised(self):
        from thebeast.pipeline import is_placeholder

        assert is_placeholder(9_000_100)      # MLB pre-lineup filler
        assert is_placeholder(1000)           # _synthetic_lineup home
        assert is_placeholder(2008)           # _synthetic_lineup away

    def test_a_real_player_id_is_not_a_placeholder(self):
        from thebeast.pipeline import is_placeholder

        # The real range in this database is 457705..823550.
        assert not is_placeholder(457705)
        assert not is_placeholder(592450)
        assert not is_placeholder(823550)

    def test_a_synthetic_lineup_is_left_alone(self, monkeypatch):
        from thebeast.data.models import LineupCard

        def boom(self, team):
            raise AssertionError("a placeholder nine has nobody to look up")

        monkeypatch.setattr(
            "thebeast.data.sources.availability.MLBAvailabilitySource.roster",
            boom)
        card = LineupCard(game_id="2026-08-03-BOS-NYY", team_id="NYY",
                          batting_order=list(range(1000, 1009)), starter_id=0,
                          bullpen_ids=[], confirmed=False, confirmed_at=None)
        assert _drop_unavailable(FakeRepo({}), card, 2026) is card


class TestInjuryReport:
    def test_it_lists_everyone_off_the_active_roster(self, monkeypatch):
        MLBAvailabilitySource.clear()

        def fake_get(self, url, params):
            if url.endswith("/teams"):
                return {"teams": [{"abbreviation": "NYY", "id": 147}]}
            if params.get("rosterType") == "fullRoster":
                return {"roster": [
                    entry(592450, "D10", "10-Day Injured List"),
                    entry(660271, "D60", "60-Day Injured List"),
                    entry(ACTIVE[0], "A", "Active"),
                ]}
            return full_roster(ACTIVE)

        monkeypatch.setattr(MLBAvailabilitySource, "_get", fake_get)
        report = MLBAvailabilitySource().injury_report("NYY")
        ids = {r["player_id"] for r in report}
        assert ids == {592450, 660271}, "actives excluded"
        assert {r["reason"] for r in report} == {"10-day injured list",
                                                 "60-day injured list"}

    def test_an_unreachable_source_reports_nothing(self, monkeypatch):
        MLBAvailabilitySource.clear()

        def boom(self, url, params):
            raise ConnectionError("down")

        monkeypatch.setattr(MLBAvailabilitySource, "_get", boom)
        assert MLBAvailabilitySource().injury_report("NYY") == []


class TestFilteringNeverCostsTheGame:
    """The bug behind '1 of 8 games couldn't be simulated after 3 attempts'.

    When the filter dropped players and had nobody to bring in, it returned a
    short lineup. A lineup of fewer than nine raises `IndexError` in the
    simulator, so the game failed all three attempts and vanished from the
    cards, the ranked plays and the assistant at once — a far worse outcome
    than the injured player it was avoiding.
    """

    def test_the_order_is_never_shorter_than_it_came_in(self):
        # Everyone unavailable and a bench with no statlines: the worst case.
        repo = FakeRepo({i: 500 for i in PROJ})
        order = available_order(repo, "NYY", PROJ, 2026,
                                source=source_with(range(700000, 700026)))
        assert len(order) == len(PROJ)

    def test_a_slot_with_nobody_to_fill_it_keeps_its_occupant(self):
        """A doubtful name in a lineup that simulates beats a game that
        doesn't."""
        repo = FakeRepo({i: 500 for i in PROJ})
        active = [p for p in PROJ if p != 600003] + list(range(700000, 700026))
        order = available_order(repo, "NYY", PROJ, 2026,
                                source=source_with(active))
        assert order == PROJ, "600003 stayed — there was nobody to replace him"

    def test_a_real_substitute_still_takes_the_slot(self, ):
        """The fallback must not swallow the feature: when there is somebody to
        bring in, he comes in."""
        repo = FakeRepo({i: 500 for i in PROJ} | {SUB_A: 400})
        active = ([p for p in PROJ if p != 600003] + [SUB_A]
                  + list(range(700000, 700026)))
        order = available_order(repo, "NYY", PROJ, 2026,
                                source=source_with(active))
        assert SUB_A in order and 600003 not in order
        assert len(order) == len(PROJ)

    def test_the_batting_order_keeps_its_shape(self):
        """A substitution goes into the slot it vacated, not onto the end."""
        repo = FakeRepo({i: 500 for i in PROJ} | {SUB_A: 400})
        active = ([p for p in PROJ if p != 600001] + [SUB_A]
                  + list(range(700000, 700026)))
        order = available_order(repo, "NYY", PROJ, 2026,
                                source=source_with(active))
        assert order[0] == SUB_A, "leadoff slot filled by the substitute"
        assert order[1:] == PROJ[1:], "everyone else stayed put"

    def test_partial_substitution_fills_what_it_can(self):
        repo = FakeRepo({i: 500 for i in PROJ} | {SUB_A: 400})
        # Three out, one usable replacement.
        active = ([p for p in PROJ if p not in PROJ[:3]] + [SUB_A]
                  + list(range(700000, 700026)))
        order = available_order(repo, "NYY", PROJ, 2026,
                                source=source_with(active))
        assert len(order) == len(PROJ)
        assert SUB_A in order
        assert sum(1 for p in PROJ[:3] if p in order) == 2, "two had no cover"

    def test_a_short_order_is_refused_at_the_card(self, monkeypatch):
        """Belt and braces. `available_order` guarantees the length; this
        refuses a short one anyway, because the cost of getting it wrong is a
        game missing from the whole app."""
        from thebeast.data.models import LineupCard

        monkeypatch.setattr("thebeast.pipeline.available_order",
                            lambda *a, **k: list(PROJ[:5]))
        card = LineupCard(game_id="2026-08-03-BOS-NYY", team_id="NYY",
                          batting_order=list(PROJ), starter_id=0,
                          bullpen_ids=[], confirmed=False, confirmed_at=None)
        assert _drop_unavailable(FakeRepo({}), card, 2026) is card
