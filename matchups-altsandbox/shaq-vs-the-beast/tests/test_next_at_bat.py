"""Turning a live game into a forecastable matchup.

Most of what this layer does is fail politely. A live panel that shows nothing
is the most likely thing a viewer will ever see from it — the game hasn't
started, the feed is down, the reliever who just came in isn't in our database —
and those are three different facts that an empty box renders identically. So
the reasons are what most of these pin.
"""
from __future__ import annotations

from datetime import date

import pytest

from thebeast import next_at_bat
from thebeast.data.models import BatterStatline, GameSchedule, PitcherStatline
from thebeast.data.sources.linescore import GameLinescore, GameSituation

DAY = date(2026, 8, 15)
GAME = "2026-08-15-STL-CHC"


def _batter(name, pid=1, hand="R", team="CHC"):
    return BatterStatline(
        player_id=pid, name=name, season=2026, team_id=team, hand=hand, pa=500,
        single_rate=0.150, double_rate=0.047, triple_rate=0.005, hr_rate=0.036,
        bb_rate=0.085, hbp_rate=0.010, k_rate=0.225, ipo_rate=0.442,
        woba=0.320, xwoba=0.320, iso=0.170, babip=0.300,
        platoon_split={"vL": 1.0, "vR": 1.0})


def _pitcher(name, pid=99, hand="R", team="STL"):
    return PitcherStatline(
        player_id=pid, name=name, season=2026, team_id=team, hand=hand,
        role="starter", bf=600,
        single_allowed=0.150, double_allowed=0.047, triple_allowed=0.005,
        hr_allowed=0.036, bb_allowed=0.085, hbp_allowed=0.010,
        k_rate=0.225, ipo_rate=0.442, xfip=4.00,
        platoon_split={"vL": 1.0, "vR": 1.0})


class FakeRepo:
    """Just enough repository for the join under test."""

    def __init__(self, batters=(), pitchers=(), scheduled=True):
        self._b, self._p = list(batters), list(pitchers)
        self._scheduled = scheduled

    def get_schedule(self, d):
        if not self._scheduled:
            return []
        return [GameSchedule(game_id=GAME, date=d, home_team_id="CHC",
                             away_team_id="STL", venue_id="CHC",
                             first_pitch=None, game_pk=776655)]

    def get_batters_for_season(self, season):
        return self._b if season == 2026 else []

    def get_pitchers_for_season(self, season):
        return self._p if season == 2026 else []

    def get_park_factor(self, venue_id, season):
        return None

    def get_weather(self, game_id):
        return None


def _live(**kw):
    sit = GameSituation(**kw)
    return GameLinescore(game_id=GAME, current_inning=4, is_top_inning=False,
                         situation=sit)


def _repo():
    return FakeRepo([_batter("Pete Crow-Armstrong"), _batter("Nico Hoerner", 2)],
                    [_pitcher("Sonny Gray")])


class TestItForecastsTheHitterInTheBox:
    def test_the_batter_at_the_plate_is_the_subject(self):
        """Who anybody watching actually cares about."""
        r = next_at_bat.build(_repo(), GAME, 2026, boxscore=None, linescore=_live(
            batter="Nico Hoerner", pitcher="Sonny Gray",
            on_deck="Pete Crow-Armstrong", in_hole="Somebody Else",
            balls=2, strikes=1, outs=1))
        assert r.available is True
        assert r.subject == "at_plate"
        assert r.batter == "Nico Hoerner"
        assert r.on_deck == "Pete Crow-Armstrong"
        assert r.pitcher == "Sonny Gray"

    def test_it_starts_from_the_live_count(self):
        """The half that makes forecasting the current hitter honest.

        A batter down 1-2 is a different proposition from the one who stepped
        in, and a forecast that quietly restarted at 0-0 would be describing a
        plate appearance that stopped existing three pitches ago.
        """
        r = next_at_bat.build(_repo(), GAME, 2026, boxscore=None, linescore=_live(
            batter="Nico Hoerner", pitcher="Sonny Gray", balls=1, strikes=2))
        assert (r.balls, r.strikes) == (1, 2)
        assert r.forecast["start_count"] == "1-2"

    def test_two_strikes_raises_the_strikeout_and_the_panel_shows_both(self):
        """The contrast is the point of a live panel.

        Showing only the current number hides how much the count has already
        done to the at-bat, so what it looked like at 0-0 rides along.
        """
        fresh = next_at_bat.build(_repo(), GAME, 2026, boxscore=None, linescore=_live(
            batter="Nico Hoerner", pitcher="Sonny Gray", balls=0, strikes=0))
        deep = next_at_bat.build(_repo(), GAME, 2026, boxscore=None, linescore=_live(
            batter="Nico Hoerner", pitcher="Sonny Gray", balls=0, strikes=2))
        assert deep.forecast["strikeout_pct"] > fresh.forecast["strikeout_pct"] + 10
        assert deep.forecast["started_strikeout_pct"] == pytest.approx(
            fresh.forecast["strikeout_pct"], abs=0.2)
        # A fresh count has nothing to contrast against, so it carries none.
        assert fresh.forecast["started_strikeout_pct"] is None

    def test_three_balls_raises_the_walk(self):
        r = next_at_bat.build(_repo(), GAME, 2026, boxscore=None, linescore=_live(
            batter="Nico Hoerner", pitcher="Sonny Gray", balls=3, strikes=1))
        assert r.forecast["walk_pct"] > 30.0

    def test_fewer_pitches_are_left_deeper_into_the_count(self):
        fresh = next_at_bat.build(_repo(), GAME, 2026, boxscore=None, linescore=_live(
            batter="Nico Hoerner", pitcher="Sonny Gray", balls=0, strikes=0))
        deep = next_at_bat.build(_repo(), GAME, 2026, boxscore=None, linescore=_live(
            batter="Nico Hoerner", pitcher="Sonny Gray", balls=3, strikes=2))
        assert deep.forecast["expected_pitches"] < fresh.forecast["expected_pitches"]

    def test_a_nonsense_count_falls_back_to_a_fresh_one(self):
        """The feed is the feed. A 5-7 count must not index into nothing."""
        r = next_at_bat.build(_repo(), GAME, 2026, boxscore=None, linescore=_live(
            batter="Nico Hoerner", pitcher="Sonny Gray", balls=9, strikes=9))
        assert r.available is True
        assert r.forecast["start_count"] == "0-0"

    def test_between_innings_it_uses_the_on_deck_hitter_and_says_so(self):
        """Nobody is batting, so the next hitter up is the next thing to happen.

        For him a fresh count is right, which is exactly why it has to be
        labelled — the same 0-0 would be wrong for a man already in the box.
        """
        r = next_at_bat.build(_repo(), GAME, 2026, boxscore=None, linescore=_live(
            pitcher="Sonny Gray", on_deck="Pete Crow-Armstrong", outs=0))
        assert r.available is True
        assert r.subject == "on_deck"
        assert r.batter == "Pete Crow-Armstrong"
        assert r.forecast["start_count"] == "0-0"
        assert any("Nobody is at the plate" in n for n in r.notes)

    def test_the_forecast_carries_the_matchup_numbers(self):
        r = next_at_bat.build(_repo(), GAME, 2026, boxscore=None, linescore=_live(
            batter="Nico Hoerner", pitcher="Sonny Gray"))
        f = r.forecast
        assert f is not None
        total = (f["strikeout_pct"] + f["walk_pct"] + f["in_play_pct"]
                 + f["hit_by_pitch_pct"])
        assert abs(total - 100.0) < 0.3
        assert f["start_count"] == "0-0"
        assert f["distribution"] and f["likely_pitches"] >= 1

    def test_the_live_situation_travels_with_it(self):
        r = next_at_bat.build(_repo(), GAME, 2026, boxscore=None, linescore=_live(
            batter="Nico Hoerner", pitcher="Sonny Gray", outs=2))
        assert (r.inning, r.is_top_inning, r.outs) == (4, False, 2)


class TestItSaysWhyWhenItCant:
    def test_a_game_that_hasnt_started(self):
        """No pitcher named means no game in progress, not a failure."""
        r = next_at_bat.build(_repo(), GAME, 2026, boxscore=None, linescore=_live())
        assert r.available is False
        assert "hasn't started" in r.reason or "No at-bat is in progress" in r.reason

    def test_a_pitcher_we_have_no_profile_for_gets_a_stand_in(self):
        """The common one: a reliever who came up this week.

        He used to empty the panel. A league baseline is not him, but it is a
        far better answer than nothing — and it has to be labelled, which is
        what `pitcher_profile` is for.
        """
        r = next_at_bat.build(_repo(), GAME, 2026, boxscore=None, linescore=_live(
            batter="Nico Hoerner", pitcher="Some Rookie"))
        assert r.available is True
        assert r.pitcher_profile == "league"
        assert r.batter_profile == "season"
        assert any("Some Rookie" in n for n in r.notes)

    def test_a_batter_we_have_no_profile_for_gets_a_stand_in(self):
        """About a fifth of lineup slots on a night are this.

        Measured against stored lineups: 482 of 2,304. Refusing them turned
        one hitter in five into an error message.
        """
        r = next_at_bat.build(_repo(), GAME, 2026, boxscore=None, linescore=_live(
            batter="Unknown Callup", pitcher="Sonny Gray",
            on_deck="Pete Crow-Armstrong"))
        assert r.available is True
        assert r.batter_profile == "league"
        assert r.forecast["expected_pitches"] > 0
        assert any("Unknown Callup" in n for n in r.notes)

    def test_a_game_we_dont_hold(self):
        r = next_at_bat.build(FakeRepo(scheduled=False), GAME, 2026,
                              boxscore=None, linescore=_live(batter="a", pitcher="b"))
        assert r.available is False
        assert "schedule" in r.reason

    def test_an_unparseable_game_id(self):
        r = next_at_bat.build(_repo(), "not-a-game", 2026)
        assert r.available is False
        assert "parse" in r.reason

    def test_a_dead_feed_is_not_an_empty_forecast(self):
        r = next_at_bat.build(_repo(), GAME, 2026, boxscore=None, linescore=None)
        assert r.available is False
        assert r.reason


class TestNameResolution:
    def test_accents_and_punctuation_dont_block_a_match(self):
        """The feed and our statlines disagree about accents constantly."""
        repo = FakeRepo([_batter("José Ramírez")], [_pitcher("Sonny Gray")])
        r = next_at_bat.build(repo, GAME, 2026, boxscore=None, linescore=_live(
            batter="Jose Ramirez", pitcher="Sonny Gray"))
        assert r.available is True

    def test_a_pitcher_is_not_matched_to_a_batting_line(self):
        """Two-way players and name collisions.

        Building a pitching forecast out of somebody's batting line would
        produce a confident number from entirely the wrong half of a season.
        """
        repo = FakeRepo([_batter("Shohei Ohtani"), _batter("Nico Hoerner", 2)],
                        [])
        r = next_at_bat.build(repo, GAME, 2026, boxscore=None, linescore=_live(
            batter="Nico Hoerner", pitcher="Shohei Ohtani"))
        # The guard still holds: his batting line must not be read as pitching.
        # It now falls through to a labelled baseline instead of refusing.
        assert r.pitcher_profile == "league"
        assert r.batter_profile == "season"

    def test_it_serialises(self):
        r = next_at_bat.build(_repo(), GAME, 2026, boxscore=None, linescore=_live(
            batter="Nico Hoerner", pitcher="Sonny Gray"))
        d = r.as_dict()
        assert d["available"] is True
        assert d["forecast"]["distribution"][0]["n"] == 1


class TestTheTeamPitchCountdown:
    """Expected pitches left for each staff, from first pitch to last out."""

    def test_a_full_game_matches_the_real_league_figure(self):
        """The check that the constants are right rather than plausible.

        MLB teams throw about 146 pitches per nine innings. The rate here is
        derived from that and from outs per plate appearance, and the three
        have to reconcile — if they didn't, the countdown would drift further
        from reality the earlier in the game you looked at it.
        """
        home, away, extras = next_at_bat._outs_left(1, True, "Top", 0)
        assert (home, away, extras) == (27, 27, False)
        remaining, total = next_at_bat._team_pitches(27, None)
        assert remaining == pytest.approx(146, abs=2)
        assert total == pytest.approx(146, abs=2)

    def test_the_two_staffs_are_at_different_points_in_the_game(self):
        """Home pitchers work the tops, away pitchers the bottoms.

        During a top the away staff still has that inning's bottom ahead of
        it, so it is always a half-inning behind. Collapsing the two would put
        one team's countdown three outs wrong for half of every inning.
        """
        home, away, _ = next_at_bat._outs_left(5, True, "Top", 1)
        assert away == home + 1                      # 14 vs 15
        home, away, _ = next_at_bat._outs_left(5, False, "Bottom", 1)
        assert away == home + 2                      # 12 vs 14

    def test_middle_and_end_are_not_the_same_half_inning(self):
        """MLB's own labels carry a distinction `is_top` cannot.

        "Middle" means the top is done and the bottom hasn't started; "End"
        means the whole inning is over. Reading only `is_top` there leaves a
        half-inning either double-counted or missed.
        """
        mid = next_at_bat._outs_left(3, False, "Middle", 0)
        end = next_at_bat._outs_left(3, False, "End", 0)
        assert mid[1] == end[1] + 3                  # the bottom still to come
        assert mid[0] == end[0]                      # tops unaffected

    def test_it_reaches_zero_at_the_last_out(self):
        assert next_at_bat._outs_left(9, False, "End", 0)[:2] == (0, 0)
        assert next_at_bat._team_pitches(0, None)[0] == 0

    def test_extra_innings_are_flagged_rather_than_guessed(self):
        """Past the ninth the remaining length is genuinely unknowable.

        Counting the half being played and the one that must follow is the
        most that can honestly be said, so the payload says which it is.
        """
        home, away, extras = next_at_bat._outs_left(11, True, "Top", 1)
        assert extras is True
        assert (home, away) == (2, 3)

    def test_the_current_at_bat_makes_it_move_between_outs(self):
        """Otherwise the counter steps five at a time and looks frozen."""
        flat, _ = next_at_bat._team_pitches(20, None)
        deep, _ = next_at_bat._team_pitches(20, 1.2)     # batter down 1-2
        fresh, _ = next_at_bat._team_pitches(20, 4.5)    # fresh count
        assert deep < fresh
        assert abs(flat - fresh) < 5

    def test_it_survives_a_player_we_have_no_profile_for(self):
        """The countdown needs the inning, not the names.

        Losing it because one reliever isn't in our database would be a poor
        trade — and that reliever is exactly when a viewer wants the number.
        """
        r = next_at_bat.build(_repo(), GAME, 2026, boxscore=None, linescore=_live(
            batter="Nico Hoerner", pitcher="Some Rookie", outs=1))
        assert r.team_pitches
        assert {t["side"] for t in r.team_pitches} == {"home", "away"}

    def test_exactly_one_staff_is_marked_as_pitching(self):
        r = next_at_bat.build(_repo(), GAME, 2026, boxscore=None, linescore=_live(
            batter="Nico Hoerner", pitcher="Sonny Gray", outs=1))
        pitching = [t for t in r.team_pitches if t["is_pitching"]]
        assert len(pitching) == 1
        # `_live` builds a bottom-of-the-4th, so the away staff is on.
        assert pitching[0]["side"] == "away"

    def test_it_counts_down_as_the_game_goes_on(self):
        early = next_at_bat.build(_repo(), GAME, 2026, boxscore=None, linescore=GameLinescore(
            game_id=GAME, current_inning=2, is_top_inning=True,
            inning_state="Top",
            situation=GameSituation(batter="Nico Hoerner",
                                    pitcher="Sonny Gray", outs=0)))
        late = next_at_bat.build(_repo(), GAME, 2026, boxscore=None, linescore=GameLinescore(
            game_id=GAME, current_inning=8, is_top_inning=True,
            inning_state="Top",
            situation=GameSituation(batter="Nico Hoerner",
                                    pitcher="Sonny Gray", outs=0)))
        e = next(t for t in early.team_pitches if t["side"] == "home")
        l = next(t for t in late.team_pitches if t["side"] == "home")
        assert l["expected_remaining"] < e["expected_remaining"]
        assert l["pct_remaining"] < e["pct_remaining"]


class TestTheOverEstimateCounter:
    """What the countdown does once the estimate runs out.

    Two different zeros, and conflating them would be the whole bug: a home
    staff is legitimately finished the moment the top of the ninth ends, while
    a staff that has thrown 160 pitches by the seventh is late rather than done.
    """

    class _Box:
        def __init__(self, home, away):
            self.home = type("T", (), {"pitchers": home})()
            self.away = type("T", (), {"pitchers": away})()

    @staticmethod
    def _arms(*counts):
        return [type("P", (), {"pitches": c})() for c in counts]

    def _built(self, box, **sit):
        s = {"batter": "Nico Hoerner", "pitcher": "Sonny Gray", "outs": 1}
        s.update(sit)
        return next_at_bat.build(_repo(), GAME, 2026, boxscore=box,
                                 linescore=GameLinescore(
                                     game_id=GAME, current_inning=s.pop("inning", 7),
                                     is_top_inning=True, inning_state="Top",
                                     situation=GameSituation(**s)))

    def test_it_counts_up_once_the_estimate_is_passed(self):
        """A staff can blow through 146 well before the ninth.

        An outs-derived over-run could never show this — it would just be the
        league rate again. Only the real count knows the bullpen had a night.
        """
        r = self._built(self._Box(self._arms(120, 60), self._arms(80)))
        home = next(t for t in r.team_pitches if t["side"] == "home")
        assert home["thrown"] == 180
        assert home["over_estimate"] == 180 - home["expected_total"]
        assert home["over_estimate"] > 0

    def test_a_staff_inside_the_estimate_is_not_marked_over(self):
        r = self._built(self._Box(self._arms(70), self._arms(65)))
        for t in r.team_pitches:
            assert t["over_estimate"] == 0
            assert t["thrown"] in (70, 65)

    def test_finishing_is_not_the_same_as_running_over(self):
        """The home staff is done once the top of the ninth ends.

        Its countdown reads zero, and that zero means finished — marking it as
        an over-run would call every completed outing late.
        """
        r = self._built(self._Box(self._arms(100), self._arms(100)),
                        inning=9, batter=None, pitcher="Sonny Gray")
        home = next(t for t in r.team_pitches if t["side"] == "home")
        assert home["outs_remaining"] > 0        # still in the top of the 9th
        assert home["complete"] is False

    def test_a_staff_with_no_outs_left_is_complete(self):
        r = next_at_bat.build(_repo(), GAME, 2026, boxscore=None, linescore=GameLinescore(
            game_id=GAME, current_inning=9, is_top_inning=False,
            inning_state="Bottom",
            situation=GameSituation(batter="Nico Hoerner",
                                    pitcher="Sonny Gray", outs=1)))
        home = next(t for t in r.team_pitches if t["side"] == "home")
        assert home["outs_remaining"] == 0
        assert home["complete"] is True

    def test_a_missing_box_score_costs_the_over_run_and_nothing_else(self):
        """The countdown is estimated off the innings and doesn't need it."""
        r = self._built(None)
        for t in r.team_pitches:
            assert t["thrown"] is None
            assert t["over_estimate"] == 0
            assert t["expected_remaining"] > 0

    def test_an_unreported_pitch_count_does_not_read_as_zero(self):
        """MLB posts a reliever's count late.

        Summing him as zero would make a staff look fresher than it is, which
        is the one direction this number must not err in.
        """
        r = self._built(self._Box(self._arms(90, None, 40), self._arms(50)))
        home = next(t for t in r.team_pitches if t["side"] == "home")
        assert home["thrown"] == 130          # the None is skipped, not zeroed

    def test_saying_there_is_no_box_score_does_not_go_looking_for_one(self):
        """`boxscore=None` means "there isn't one", not "fetch it".

        The two used to be the same value, which had these unit tests making
        real calls to MLB — the file ran five times slower and its timing was
        at the mercy of a network it should never have touched.
        """
        import thebeast.data.sources.boxscore as box_mod

        calls = []

        def boom(self, *a, **k):
            calls.append(1)
            raise AssertionError("should not fetch")

        original = box_mod.MLBBoxscoreSource.fetch_boxscore
        box_mod.MLBBoxscoreSource.fetch_boxscore = boom
        try:
            r = next_at_bat.build(_repo(), GAME, 2026, boxscore=None,
                                  linescore=_live(batter="Nico Hoerner",
                                                  pitcher="Sonny Gray"))
        finally:
            box_mod.MLBBoxscoreSource.fetch_boxscore = original
        assert calls == []
        assert r.team_pitches and r.team_pitches[0]["thrown"] is None

    def test_the_projection_follows_the_staffs_own_pace(self):
        """The complaint this answers: an estimate that was only outs × a rate.

        Two staffs at the same point in the game with very different nights
        behind them must not project the same number of pitches left.
        """
        quick = self._built(self._Box(self._arms(55), self._arms(80)))
        long_ = self._built(self._Box(self._arms(125), self._arms(80)))
        q = next(t for t in quick.team_pitches if t["side"] == "home")
        l = next(t for t in long_.team_pitches if t["side"] == "home")
        assert q["outs_remaining"] == l["outs_remaining"]      # same innings
        assert l["expected_remaining"] > q["expected_remaining"]
        assert l["pace"] > q["pace"]

    def test_the_pace_is_shrunk_towards_the_league(self):
        """Three outs is one inning, and one inning is not a night.

        Believing a raw rate off three outs would project a staff that threw
        thirty in the first for two hundred and seventy.
        """
        r = self._built(self._Box(self._arms(30), self._arms(30)), inning=2,
                        outs=0)
        home = next(t for t in r.team_pitches if t["side"] == "home")
        raw = home["thrown"] / home["outs_recorded"]
        assert raw > 9                                          # 30 in 3 outs
        assert home["pace"] < raw                                # not believed
        assert home["pace"] > next_at_bat.LEAGUE_PITCHES_PER_OUT  # but heard

    def test_outs_recorded_and_outs_left_always_account_for_the_game(self):
        """The two halves of the same arithmetic must never disagree."""
        for inning in range(1, 10):
            for state in ("Top", "Middle", "Bottom", "End"):
                for outs in (0, 1, 2):
                    rec = next_at_bat._outs_recorded(
                        inning, state == "Top", state, outs)
                    left = next_at_bat._outs_left(
                        inning, state == "Top", state, outs)
                    assert rec[0] + left[0] == 27, (inning, state, outs)
                    assert rec[1] + left[1] == 27, (inning, state, outs)

    def test_a_projected_total_needs_a_real_count(self):
        """Without the box score there is no pace and nothing to project."""
        r = self._built(None)
        for t in r.team_pitches:
            assert t["projected_total"] is None
            assert t["pace"] == next_at_bat.LEAGUE_PITCHES_PER_OUT
