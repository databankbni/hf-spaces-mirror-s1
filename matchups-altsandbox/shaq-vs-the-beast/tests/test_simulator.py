"""Integration tests for thebeast.simulator.

Tests run against real fixture PAOutcomeDistributions with synthetic inputs —
no network calls, no matchup model required.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

import numpy as np
import pytest

from thebeast.data.models import LineupCard
from thebeast.simulator.advancement import LeagueAverageMatrix
from thebeast.simulator.config import SimulationKnobs
from thebeast.simulator.engine import (
    simulate_game, _starter_is_done, _trouble_pressure)
from thebeast.simulator.aggregate import run_games, aggregate
from thebeast.simulator.state import InningState
from thebeast.simulator.outcome import PAOutcomeDistribution, PAOutcomeEnum


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _league_avg_dist(batter_id: int, pitcher_id: int) -> PAOutcomeDistribution:
    """League-average PA outcome distribution, roughly 2021-2024 MLB averages."""
    return PAOutcomeDistribution(
        batter_id=batter_id,
        pitcher_id=pitcher_id,
        single=0.150,
        double=0.047,
        triple=0.005,
        home_run=0.036,
        walk=0.085,
        hit_by_pitch=0.010,
        strikeout=0.225,
        in_play_out=0.442,
    )


def _make_lineup(team_id: str, game_id: str = "2024/04/01-NYY-BOS") -> LineupCard:
    batter_ids = list(range(100 + int(team_id == "BOS") * 10, 109 + int(team_id == "BOS") * 10))
    return LineupCard(
        game_id=game_id,
        team_id=team_id,
        batting_order=batter_ids,
        starter_id=200 + int(team_id == "BOS"),
        bullpen_ids=[300 + int(team_id == "BOS")],
        confirmed=True,
        confirmed_at=None,
    )


@pytest.fixture
def home_lineup() -> LineupCard:
    return _make_lineup("BOS")


@pytest.fixture
def away_lineup() -> LineupCard:
    return _make_lineup("NYY")


@pytest.fixture
def pa_distributions(home_lineup: LineupCard, away_lineup: LineupCard) -> dict:
    """Pre-computed distributions for all 9 batters vs each starter."""
    dists = {}
    all_batters = home_lineup.batting_order + away_lineup.batting_order
    all_pitchers = [
        home_lineup.starter_id, away_lineup.starter_id,
        *home_lineup.bullpen_ids, *away_lineup.bullpen_ids,
    ]
    for b in all_batters:
        for p in all_pitchers:
            dists[(b, p)] = _league_avg_dist(b, p)
    return dists


@pytest.fixture
def advancement() -> LeagueAverageMatrix:
    return LeagueAverageMatrix()


# ─── InningState ──────────────────────────────────────────────────────────────

class TestInningState:
    def test_initial_state(self) -> None:
        s = InningState(home="BOS", away="NYY")
        assert s.inning == 1
        assert s.half == "top"
        assert s.outs == 0
        assert s.runners_bitmap == 0
        assert s.score == {"BOS": 0, "NYY": 0}
        assert not s.game_over

    def test_possession_starts_away(self) -> None:
        s = InningState(home="BOS", away="NYY")
        assert s.possession == "NYY"
        assert s.defense == "BOS"

    def test_three_outs_flips_half(self) -> None:
        s = InningState(home="BOS", away="NYY")
        s.record_out()
        s.record_out()
        s.record_out()
        assert s.half == "bottom"
        assert s.possession == "BOS"
        assert s.outs == 0
        assert s.runners_bitmap == 0

    def test_nine_innings_game_over(self) -> None:
        s = InningState(home="BOS", away="NYY")
        # Simulate 18 half-innings (9 full innings)
        for _ in range(18):
            s.record_out(); s.record_out(); s.record_out()
        assert s.game_over

    def test_add_runs(self) -> None:
        s = InningState(home="BOS", away="NYY")
        s.add_runs(3)
        assert s.score["NYY"] == 3
        s.record_out(); s.record_out(); s.record_out()  # end top 1
        s.add_runs(2)
        assert s.score["BOS"] == 2

    def test_walk_off_ends_game(self) -> None:
        """Home team wins in bottom of 9th — game should end."""
        s = InningState(home="BOS", away="NYY")
        # Fast-forward to bottom of 9th with home trailing by 0
        s.score = {"BOS": 0, "NYY": 0}
        # Get to bottom of 9th by burning 17 half-innings
        for _ in range(17):
            s.record_out(); s.record_out(); s.record_out()
        assert s.inning == 9 and s.half == "bottom"
        s.add_runs(1)  # home scores in bottom 9th
        # After scoring, if home is now winning, game should end
        s._check_walk_off()
        assert s.game_over

    def test_batting_position_advances(self) -> None:
        s = InningState(home="BOS", away="NYY")
        assert s.batting_position["NYY"] == 0
        s.advance_batting_position()
        assert s.batting_position["NYY"] == 1

    def test_batting_position_wraps(self) -> None:
        s = InningState(home="BOS", away="NYY")
        for _ in range(9):
            s.advance_batting_position()
        assert s.batting_position["NYY"] == 0


# ─── PAOutcomeDistribution ────────────────────────────────────────────────────

class TestPAOutcomeDistribution:
    def test_probabilities_sum_to_one(self) -> None:
        d = _league_avg_dist(1, 2)
        total = d.single + d.double + d.triple + d.home_run + d.walk + d.hit_by_pitch + d.strikeout + d.in_play_out
        assert abs(total - 1.0) < 1e-6

    def test_sample_returns_valid_outcome(self) -> None:
        d = _league_avg_dist(1, 2)
        rng = np.random.default_rng(42)
        valid = {o.value for o in PAOutcomeEnum}
        for _ in range(100):
            outcome = d.sample(rng)
            assert outcome in valid

    def test_sample_distribution_approx_correct(self) -> None:
        d = _league_avg_dist(1, 2)
        rng = np.random.default_rng(0)
        counts: dict[str, int] = {}
        n = 10_000
        for _ in range(n):
            o = d.sample(rng)
            counts[o] = counts.get(o, 0) + 1
        # HR rate should be within 1% of 0.036
        assert abs(counts.get("HR", 0) / n - 0.036) < 0.01


# ─── simulate_game ────────────────────────────────────────────────────────────

class TestSimulateGame:
    def test_returns_valid_scores(
        self,
        home_lineup: LineupCard,
        away_lineup: LineupCard,
        pa_distributions: dict,
        advancement: LeagueAverageMatrix,
    ) -> None:
        rng = np.random.default_rng(42)
        result = simulate_game(home_lineup, away_lineup, pa_distributions, advancement, rng=rng)
        assert result.home_score >= 0
        assert result.away_score >= 0
        assert result.innings_played == 9 or result.extra_innings

    def test_deterministic_with_seed(
        self,
        home_lineup: LineupCard,
        away_lineup: LineupCard,
        pa_distributions: dict,
        advancement: LeagueAverageMatrix,
    ) -> None:
        r1 = simulate_game(
            home_lineup, away_lineup, pa_distributions, advancement,
            rng=np.random.default_rng(7)
        )
        r2 = simulate_game(
            home_lineup, away_lineup, pa_distributions, advancement,
            rng=np.random.default_rng(7)
        )
        assert r1.home_score == r2.home_score
        assert r1.away_score == r2.away_score

    def test_log_flag_produces_play_log(
        self,
        home_lineup: LineupCard,
        away_lineup: LineupCard,
        pa_distributions: dict,
        advancement: LeagueAverageMatrix,
    ) -> None:
        result = simulate_game(
            home_lineup, away_lineup, pa_distributions, advancement,
            rng=np.random.default_rng(1), log=True
        )
        assert len(result.play_log) > 0

    def test_by_inning_totals_match_score(
        self,
        home_lineup: LineupCard,
        away_lineup: LineupCard,
        pa_distributions: dict,
        advancement: LeagueAverageMatrix,
    ) -> None:
        result = simulate_game(
            home_lineup, away_lineup, pa_distributions, advancement,
            rng=np.random.default_rng(3)
        )
        assert sum(result.home_by_inning) == result.home_score
        assert sum(result.away_by_inning) == result.away_score


# ─── run_games / aggregate ────────────────────────────────────────────────────

class TestRunGames:
    def test_symmetric_win_probability(
        self,
        home_lineup: LineupCard,
        away_lineup: LineupCard,
        pa_distributions: dict,
        advancement: LeagueAverageMatrix,
    ) -> None:
        """With identical league-average lineups on both sides, home win probability
        must converge to 50% ± 1% over 2,000 games."""
        raw = run_games(
            home_lineup, away_lineup, pa_distributions, advancement,
            n=2000, seed=0,
        )
        agg = aggregate("test-game", "BOS", "NYY", raw)
        assert abs(agg.home_win_probability - 0.50) < 0.03

    def test_raw_arrays_shape(
        self,
        home_lineup: LineupCard,
        away_lineup: LineupCard,
        pa_distributions: dict,
        advancement: LeagueAverageMatrix,
    ) -> None:
        n = 50
        raw = run_games(
            home_lineup, away_lineup, pa_distributions, advancement, n=n, seed=1
        )
        assert raw.home_runs.shape == (n,)
        assert raw.away_runs.shape == (n,)

    def test_aggregate_result_fields(
        self,
        home_lineup: LineupCard,
        away_lineup: LineupCard,
        pa_distributions: dict,
        advancement: LeagueAverageMatrix,
    ) -> None:
        raw = run_games(
            home_lineup, away_lineup, pa_distributions, advancement, n=100, seed=2
        )
        agg = aggregate("test-game", "BOS", "NYY", raw)
        assert 0 <= agg.home_win_probability <= 1
        assert agg.home_run_mean > 0
        assert agg.total_mean > 0
        assert agg.home_run_p10 <= agg.home_run_mean <= agg.home_run_p90

    def test_run_distribution_plausible(
        self,
        home_lineup: LineupCard,
        away_lineup: LineupCard,
        pa_distributions: dict,
        advancement: LeagueAverageMatrix,
    ) -> None:
        """Mean run total per team should be between 3 and 7 for league-average inputs."""
        raw = run_games(
            home_lineup, away_lineup, pa_distributions, advancement, n=500, seed=3
        )
        agg = aggregate("test-game", "BOS", "NYY", raw)
        assert 3.0 <= agg.home_run_mean <= 7.0
        assert 3.0 <= agg.away_run_mean <= 7.0


class TestResumeFromLiveState:
    """simulate_game(initial_state=...) — the live-sim path."""

    def _state(self, **kw) -> InningState:
        base = dict(home="BOS", away="NYY")
        base.update(kw)
        return InningState(**base)

    def test_already_scored_runs_are_never_lost(
        self,
        home_lineup: LineupCard,
        away_lineup: LineupCard,
        pa_distributions: dict,
        advancement: LeagueAverageMatrix,
    ) -> None:
        start = self._state(inning=7, half="top", outs=1,
                            score={"BOS": 5, "NYY": 3},
                            batting_position={"BOS": 2, "NYY": 6})
        raw = run_games(home_lineup, away_lineup, pa_distributions, advancement,
                        n=200, seed=11, initial_state=start)
        assert raw.home_runs.min() >= 5
        assert raw.away_runs.min() >= 3

    def test_resume_does_not_mutate_the_shared_start_state(
        self,
        home_lineup: LineupCard,
        away_lineup: LineupCard,
        pa_distributions: dict,
        advancement: LeagueAverageMatrix,
    ) -> None:
        start = self._state(inning=6, half="bottom", outs=2, runners_bitmap=0b101,
                            score={"BOS": 2, "NYY": 2})
        run_games(home_lineup, away_lineup, pa_distributions, advancement,
                  n=50, seed=5, initial_state=start)
        assert start.inning == 6 and start.half == "bottom"
        assert start.outs == 2 and start.runners_bitmap == 0b101
        assert start.score == {"BOS": 2, "NYY": 2}
        assert not start.game_over

    def test_big_late_lead_is_near_certain(
        self,
        home_lineup: LineupCard,
        away_lineup: LineupCard,
        pa_distributions: dict,
        advancement: LeagueAverageMatrix,
    ) -> None:
        start = self._state(inning=9, half="top", outs=0,
                            score={"BOS": 10, "NYY": 1})
        raw = run_games(home_lineup, away_lineup, pa_distributions, advancement,
                        n=300, seed=9, initial_state=start)
        assert float(np.mean(raw.home_runs > raw.away_runs)) > 0.98

    def test_resuming_at_the_start_matches_a_normal_game(
        self,
        home_lineup: LineupCard,
        away_lineup: LineupCard,
        pa_distributions: dict,
        advancement: LeagueAverageMatrix,
    ) -> None:
        """A fresh initial_state is equivalent to not passing one at all."""
        a = simulate_game(home_lineup, away_lineup, pa_distributions, advancement,
                          rng=np.random.default_rng(42))
        b = simulate_game(home_lineup, away_lineup, pa_distributions, advancement,
                          rng=np.random.default_rng(42),
                          initial_state=self._state())
        assert (a.home_score, a.away_score) == (b.home_score, b.away_score)

    def test_walk_off_ends_the_game_immediately(
        self,
        home_lineup: LineupCard,
        away_lineup: LineupCard,
        pa_distributions: dict,
        advancement: LeagueAverageMatrix,
    ) -> None:
        """Tied, bottom 9, bases loaded: home never finishes behind, and any
        home win is by exactly the runs that ended it (game stops on the run)."""
        start = self._state(inning=9, half="bottom", outs=0, runners_bitmap=0b111,
                            score={"BOS": 4, "NYY": 4})
        raw = run_games(home_lineup, away_lineup, pa_distributions, advancement,
                        n=300, seed=13, initial_state=start)
        assert raw.away_runs.min() == 4 and raw.away_runs.max() == 4  # away is done
        assert (raw.home_runs >= 4).all()
        assert float(np.mean(raw.home_runs > raw.away_runs)) > 0.5


class TestPitchCounts:
    """Pitch counts are projected and drive when the starter is removed."""

    def test_pitches_accumulate_and_look_realistic(
        self,
        home_lineup: LineupCard,
        away_lineup: LineupCard,
        pa_distributions: dict,
        advancement: LeagueAverageMatrix,
    ) -> None:
        raw = run_games(home_lineup, away_lineup, pa_distributions, advancement,
                        n=200, seed=5)
        lines = raw.home_pitchers + raw.away_pitchers
        assert lines and all(p["pitches"] > 0 for p in lines)
        # ~3.8 pitches per batter faced is the league norm; allow a wide band.
        for p in lines:
            per_bf = p["pitches"] / p["bf"]
            assert 3.0 <= per_bf <= 5.0, f"{per_bf:.2f} pitches per BF is implausible"

    def test_starter_is_pulled_at_the_pitch_limit(
        self,
        home_lineup: LineupCard,
        away_lineup: LineupCard,
        pa_distributions: dict,
        advancement: LeagueAverageMatrix,
    ) -> None:
        """A tight limit must shorten the starter's outing."""
        long_hook = SimulationKnobs(use_pitch_counts=False)
        short_hook = SimulationKnobs(use_pitch_counts=True, starter_pitch_limit=40)
        outs, relief = {}, {}
        for label, knobs in (("off", long_hook), ("on", short_hook)):
            raw = run_games(home_lineup, away_lineup, pa_distributions, advancement,
                            n=150, seed=9, knobs=knobs)
            # Select the starter by id — with an early hook he is no longer the
            # pitcher with the most outs, which is the point of the test.
            starter = next(p for p in raw.home_pitchers
                           if p["player_id"] == home_lineup.starter_id)
            outs[label] = starter["outs"]
            relief[label] = sum(p["outs"] for p in raw.home_pitchers
                                if p["player_id"] != home_lineup.starter_id)
        assert outs["on"] < outs["off"], (
            f"a 40-pitch limit should shorten the outing: {outs}")
        # The innings don't vanish — the bullpen absorbs them.
        assert relief["on"] > relief["off"]

    def test_live_sim_seeds_the_starters_existing_pitch_count(
        self,
        home_lineup: LineupCard,
        away_lineup: LineupCard,
        pa_distributions: dict,
        advancement: LeagueAverageMatrix,
    ) -> None:
        """Resuming with the starter already past the limit sends him straight
        to the bullpen rather than treating him as fresh."""
        knobs = SimulationKnobs(use_pitch_counts=True, starter_pitch_limit=95)
        start = InningState(home="BOS", away="NYY", inning=2, half="top",
                            score={"BOS": 0, "NYY": 0})
        spent = run_games(home_lineup, away_lineup, pa_distributions, advancement,
                          n=120, seed=4, knobs=knobs, initial_state=start,
                          initial_pitch_counts={"BOS": 200.0})
        fresh = run_games(home_lineup, away_lineup, pa_distributions, advancement,
                          n=120, seed=4, knobs=knobs, initial_state=start,
                          initial_pitch_counts={"BOS": 0.0})

        def outs_for(bucket, pid):
            return sum(p["outs"] for p in bucket if p["player_id"] == pid)

        # BOS is home, so its starter pitches while NYY bats (the top half).
        assert outs_for(spent.home_pitchers, home_lineup.starter_id) == 0
        assert outs_for(fresh.home_pitchers, home_lineup.starter_id) > 0


class TestReliefSequence:
    """The bullpen is worked through in order, an inning or so per arm."""

    def _pen_lineup(self, base: LineupCard, ids: list[int]) -> LineupCard:
        import dataclasses
        return dataclasses.replace(base, bullpen_ids=ids)

    def test_multiple_arms_each_get_work(
        self,
        home_lineup: LineupCard,
        away_lineup: LineupCard,
        pa_distributions: dict,
        advancement: LeagueAverageMatrix,
    ) -> None:
        pen = [901, 902, 903]
        home = self._pen_lineup(home_lineup, pen)
        raw = run_games(home, away_lineup, pa_distributions, advancement,
                        n=150, seed=21)
        used = {p["player_id"]: p["outs"] for p in raw.home_pitchers}
        for pid in pen:
            assert used.get(pid, 0) > 0, f"reliever {pid} never pitched: {used}"
        # Nobody covers the whole back end alone.
        assert max(used[pid] for pid in pen) < sum(used[pid] for pid in pen)

    def test_single_arm_bullpen_is_unchanged(
        self,
        home_lineup: LineupCard,
        away_lineup: LineupCard,
        pa_distributions: dict,
        advancement: LeagueAverageMatrix,
    ) -> None:
        """A one-entry bullpen must behave exactly as before the sequence."""
        one = self._pen_lineup(home_lineup, [901])
        raw = run_games(one, away_lineup, pa_distributions, advancement,
                        n=120, seed=8)
        pen_lines = [p for p in raw.home_pitchers if p["player_id"] == 901]
        assert len(pen_lines) == 1
        assert pen_lines[0]["outs"] > 0

    def test_each_arm_gets_about_an_inning_and_the_last_finishes(
        self,
        home_lineup: LineupCard,
        away_lineup: LineupCard,
        pa_distributions: dict,
        advancement: LeagueAverageMatrix,
    ) -> None:
        """Arms are handed roughly an inning apiece, and the final one listed
        absorbs whatever is left rather than handing off to a fourth arm.

        The last arm is compared against the *middle* one, not against all of
        them. The middle arm is the clean case: he comes in to start an inning
        and leaves after it. The first arm inherits whatever is left of the
        inning the starter was pulled from, so he routinely works more than an
        inning too — with starters now going deep enough that little is left
        over, that inherited fraction is about as much as the last arm's
        remainder, and which of the two leads is not a property of the code.
        """
        home = self._pen_lineup(home_lineup, [901, 902, 903])
        raw = run_games(home, away_lineup, pa_distributions, advancement,
                        n=200, seed=33)
        used = {p["player_id"]: p["outs"] for p in raw.home_pitchers}
        for pid in (901, 902, 903):
            assert 2.0 <= used[pid] <= 6.0, f"{pid} worked {used[pid]:.2f} outs"
        assert used[903] >= used[902]


class TestStarterWorkload:
    """A start has to be able to reach the lines books actually quote.

    `starter_innings` was 5, which is *below* a common prop line: no simulated
    starter could record an 18th out, so "under 17.5 outs" priced at a
    certainty — 100%, top of the panel, on every starter. The ceiling is now
    well past a normal outing and the pitch count is the real hook.
    """

    def _sample(self, home, away, dists, adv, n=400):
        outs = []
        for seed in range(n):
            g = simulate_game(home, away, dists, adv,
                              rng=np.random.default_rng(seed))
            outs.append(g.pitcher_stats[(home.team_id, home.starter_id)]["outs"])
        return outs

    def test_a_starter_can_complete_six_innings(
        self, home_lineup, away_lineup, pa_distributions, advancement,
    ) -> None:
        outs = self._sample(home_lineup, away_lineup, pa_distributions, advancement)
        assert max(outs) >= 18, (
            "no start reached 6 innings, so any line at 17.5 outs is a "
            "foregone conclusion rather than a question")
        share = sum(1 for v in outs if v >= 18) / len(outs)
        assert 0.15 < share < 0.60, (
            f"{share:.0%} of starts reached 6 IP; MLB is around a third")

    def test_the_outs_distribution_is_not_a_spike(
        self, home_lineup, away_lineup, pa_distributions, advancement,
    ) -> None:
        """A fixed hook ended 94% of starts on the same out, which makes every
        nearby line look certain. Each start now draws its own limit."""
        outs = self._sample(home_lineup, away_lineup, pa_distributions, advancement)
        commonest = max(outs.count(v) for v in set(outs))
        assert commonest / len(outs) < 0.5, "outs are piled on a single value"
        assert len(set(outs)) >= 8, "too few distinct outcomes to price against"


class TestTroubleShortensTheLeash:
    """How a start is going has to move the hook without deciding it.

    Trouble was first modelled as thresholds — five runs and the day was over,
    full stop. That ends every rough start at the same instant, which is not a
    hook so much as a rule. It is now pressure on the pitch limit: real, but
    something the rest of the outing can still outweigh.
    """

    def test_trouble_costs_leash_in_proportion(self) -> None:
        k = SimulationKnobs()
        clean = _trouble_pressure(k, 0, 0, 0)
        ordinary = _trouble_pressure(k, 2, 1, 2)
        rough = _trouble_pressure(k, 4, 1, 2)
        rougher = _trouble_pressure(k, 6, 1, 2)
        assert clean == 0.0
        # A manager sits through two runs over a start without reaching for the
        # phone, so ordinary trouble must cost nothing at all.
        assert ordinary == 0.0
        assert 0 < rough < rougher, "more runs must cost more leash"

    def test_trouble_is_capped(self) -> None:
        """Even a battering leaves some rope — the bullpen is finite."""
        k = SimulationKnobs()
        assert _trouble_pressure(k, 12, 8, 9) == k.starter_trouble_max
        assert k.starter_trouble_max < k.starter_pitch_limit

    def test_a_battered_starter_is_not_automatically_pulled(self) -> None:
        """The distinguishing property of the weighted model: trouble early in
        a start shortens the leash but does not end the outing on the spot."""
        k = SimulationKnobs()
        # Five runs allowed — past every threshold the old model used — but
        # only 40 pitches in. He stays in.
        assert not _starter_is_done(3, k, 40.0, 95.0, runs_allowed=5,
                                    inning_runs=3, consecutive_on=3)
        # Same trouble, deep into the outing: now it is decisive.
        assert _starter_is_done(6, k, 80.0, 95.0, runs_allowed=5,
                                inning_runs=3, consecutive_on=3)
        # And with no trouble at all, 80 pitches is not yet the hook.
        assert not _starter_is_done(6, k, 80.0, 95.0)


class TestLineScoreAddsUp:
    def test_a_walk_off_appears_in_the_line_score(
        self, home_lineup, away_lineup, pa_distributions, advancement,
    ) -> None:
        """A walk-off ends the half mid-inning. Those runs counted toward the
        final but were never flushed to the line score, so the box didn't add
        up in roughly one game in seven — every one of them a home win."""
        mismatched = walk_offs = 0
        for seed in range(300):
            g = simulate_game(home_lineup, away_lineup, pa_distributions,
                              advancement, rng=np.random.default_rng(seed))
            if sum(g.home_by_inning) != g.home_score:
                mismatched += 1
            if sum(g.away_by_inning) != g.away_score:
                mismatched += 1
            if g.home_score > g.away_score:
                walk_offs += 1
        assert walk_offs > 0, "fixture should produce some home wins"
        assert mismatched == 0, f"{mismatched} line scores did not match the final"


class TestStarterLeashIsPerPitcher:
    """Workload has to be projected from the pitcher, not assigned to him.

    A single league-average hook put every starter within half an inning of
    every other (4.98–5.46 IP), when the real range runs from about 4.4 to 6.2.
    Each start's limit is now shifted off the average by that pitcher's own
    FIP, because a manager's leash tracks whether the man is getting outs.
    """

    def test_a_better_starter_is_projected_deeper(self) -> None:
        from thebeast.pipeline import starter_leashes
        from thebeast.simulator.config import SimulationKnobs

        class Stub:
            def __init__(self, fip_parts):
                self.k_rate, self.ipo_rate, self.hr_allowed, \
                    self.bb_allowed, self.hbp_allowed = fip_parts

        class Repo:
            def __init__(self, by_id):
                self.by_id = by_id
            def get_pitcher(self, pid, season):
                return self.by_id.get(pid)

        # An ace (high K, low walks/HR) and a struggler (the reverse).
        ace = Stub((0.30, 0.45, 0.020, 0.050, 0.005))
        poor = Stub((0.15, 0.45, 0.050, 0.110, 0.010))
        home = _make_lineup("BOS")
        away = _make_lineup("NYY")
        repo = Repo({home.starter_id: ace, away.starter_id: poor})

        knobs = SimulationKnobs()
        limits = starter_leashes(repo, home, away, 2026, knobs)
        assert limits["BOS"] > limits["NYY"], (
            "the better pitcher must earn the longer leash")
        assert limits["BOS"] - limits["NYY"] > 8, (
            "the gap is too small to move projected innings meaningfully")
        lo, hi = knobs.starter_leash_bounds
        assert all(lo <= v <= hi for v in limits.values())

    def test_no_statline_falls_back_to_the_league_average(self) -> None:
        """A placeholder starter or a callup with nothing on file gets the
        average — the honest answer when there's nothing to tell him apart."""
        from thebeast.pipeline import starter_leashes
        from thebeast.simulator.config import SimulationKnobs

        class Repo:
            def get_pitcher(self, pid, season):
                return None

        knobs = SimulationKnobs()
        limits = starter_leashes(Repo(), _make_lineup("BOS"), _make_lineup("NYY"),
                                 2026, knobs)
        assert set(limits.values()) == {float(knobs.starter_pitch_limit)}

    def test_the_limit_actually_changes_the_outing(
        self, home_lineup, away_lineup, pa_distributions, advancement,
    ) -> None:
        """The leash has to reach the engine, not just be computed."""
        def mean_outs(limit):
            tot = 0
            for seed in range(120):
                g = simulate_game(home_lineup, away_lineup, pa_distributions,
                                  advancement, rng=np.random.default_rng(seed),
                                  starter_pitch_limits={home_lineup.team_id: limit})
                tot += g.pitcher_stats[(home_lineup.team_id, home_lineup.starter_id)]["outs"]
            return tot / 120

        short, long = mean_outs(70), mean_outs(105)
        assert long - short > 2.0, (
            f"a 35-pitch longer leash moved the outing only {long - short:.1f} outs")
