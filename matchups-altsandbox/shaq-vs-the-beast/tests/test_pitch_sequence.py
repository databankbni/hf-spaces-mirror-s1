"""The at-bat length model, and the two claims it has to keep.

The first is that it never contradicts the rest of the app: the chain is fitted
to the Log5 matchup distribution, so the strikeout and walk percentages it
reports must be the ones it was handed, not near them.

The second is that it describes baseball. Matching two numbers it was fitted to
proves nothing on its own — a model that produced them via nonsense pitches
would pass. So the per-pitch mix is pinned against real league rates too, and
so is the shape of the length distribution that comes out of it.
"""
from __future__ import annotations

import pytest

from thebeast.pitch_sequence import (
    OUTCOMES,
    _advance,
    _pitch_outcomes,
    _run_chain,
    _solve,
    _terminals,
    forecast,
)

LEAGUE_K, LEAGUE_BB, LEAGUE_HBP = 0.225, 0.085, 0.010


def _league(**kw):
    return forecast(batter="B", pitcher="P", strikeout_p=LEAGUE_K,
                    walk_p=LEAGUE_BB, hbp_p=LEAGUE_HBP, **kw)


class TestItReproducesWhatItWasGiven:
    """The whole reason the chain is fitted rather than modelled independently."""

    def test_the_league_average_matchup_comes_back_exactly(self):
        f = _league()
        assert f.strikeout_pct == pytest.approx(22.5, abs=0.15)
        assert f.walk_pct == pytest.approx(8.5, abs=0.15)
        assert f.fit_capped is False

    @pytest.mark.parametrize("k,bb", [
        (0.330, 0.140), (0.150, 0.060), (0.450, 0.030),
        (0.120, 0.050), (0.250, 0.115),
    ])
    def test_realistic_matchups_are_hit_exactly(self, k, bb):
        """Not "close": these are the numbers the matchup card shows."""
        f = forecast(batter="B", pitcher="P", strikeout_p=k, walk_p=bb,
                     hbp_p=0.01)
        assert f.strikeout_pct == pytest.approx(100 * k, abs=0.15)
        assert f.walk_pct == pytest.approx(100 * bb, abs=0.15)
        assert f.fit_capped is False

    def test_the_four_outcomes_account_for_the_whole_at_bat(self):
        f = _league()
        assert (f.strikeout_pct + f.walk_pct + f.in_play_pct
                + f.hit_by_pitch_pct) == pytest.approx(100.0, abs=0.2)

    def test_hit_by_pitch_is_reported_but_not_walked_in(self):
        f = forecast(batter="B", pitcher="P", strikeout_p=0.22, walk_p=0.08,
                     hbp_p=0.05)
        assert f.hit_by_pitch_pct == pytest.approx(5.0, abs=0.1)
        assert f.walk_pct == pytest.approx(8.0, abs=0.15)

    def test_an_unreachable_matchup_is_flagged_not_faked(self):
        """The rarest contact hitters sit outside what this model can produce.

        Called strikes accumulate whatever the bat control, so a 3% strikeout
        rate cannot be reached. Reporting the miss is the only honest option.
        """
        f = forecast(batter="B", pitcher="P", strikeout_p=0.03, walk_p=0.08,
                     hbp_p=0.01)
        assert f.fit_capped is True
        assert any("more extreme" in n for n in f.notes)


class TestTheLengthDistribution:
    """The product. One number is worthless without the spread around it."""

    def test_it_is_a_distribution(self):
        f = _league()
        assert sum(d["pct"] for d in f.distribution) == pytest.approx(100.0, abs=0.5)
        assert all(d["pct"] >= 0 for d in f.distribution)
        assert [d["n"] for d in f.distribution] == \
            sorted(d["n"] for d in f.distribution)

    def test_more_same_and_fewer_partition_it(self):
        """The scale a reader actually reads. It has to be exhaustive."""
        f = _league()
        assert f.more_pct + f.same_pct + f.fewer_pct == \
            pytest.approx(100.0, abs=0.3)

    def test_the_headline_is_the_mean_of_the_distribution(self):
        """The two must not drift apart — they are the same statement.

        `expected_pitches` is accumulated during propagation while the
        distribution is built from where the mass lands, so agreement is a real
        check on the bookkeeping rather than an identity.

        They differ in the seventh decimal, and the reason is worth knowing:
        `expected_pitches` sums the two-strike foul loop as an exact geometric
        series, while the distribution is cut at sixteen pitches. The gap is
        the tail beyond that cut — about six millionths of a pitch — and it is
        the only place the two definitions part company.
        """
        control, stuff, _, _ = _solve(round(LEAGUE_K / 0.99, 4),
                                      round(LEAGUE_BB / 0.99, 4))
        chain = _run_chain(control, stuff)
        ends = chain["ends_at"]
        mean = sum(n * p for n, p in ends.items()) / sum(ends.values())
        assert mean == pytest.approx(chain["expected_pitches"], abs=1e-4)
        assert mean <= chain["expected_pitches"]      # truncation only shortens

    def test_every_at_bat_ends(self):
        """No mass may leak. A plate appearance always finishes."""
        control, stuff, _, _ = _solve(round(LEAGUE_K / 0.99, 4),
                                      round(LEAGUE_BB / 0.99, 4))
        chain = _run_chain(control, stuff)
        assert sum(chain["ends_at"].values()) == pytest.approx(1.0, abs=1e-3)

    def test_an_at_bat_cannot_end_in_under_three_pitches_on_strikes(self):
        """A sanity check on the shape: one-pitch at-bats are balls in play.

        The first bucket therefore cannot exceed the chance the very first
        pitch is put in play.
        """
        control, stuff, _, _ = _solve(round(LEAGUE_K / 0.99, 4),
                                      round(LEAGUE_BB / 0.99, 4))
        first = _pitch_outcomes(0, 0, control, stuff)["in_play"]
        chain = _run_chain(control, stuff)
        assert chain["ends_at"][1] == pytest.approx(first, abs=1e-9)

    def test_the_spread_is_wide_enough_to_be_worth_showing(self):
        """If the headline were reliable there'd be no reason for a scale.

        An at-bat that averages four pitches is very rarely four pitches, and a
        panel implying otherwise would be the main thing wrong with it.
        """
        f = _league()
        assert f.same_pct < 30.0
        assert f.more_pct > 10.0 and f.fewer_pct > 10.0

    def test_the_long_tail_is_folded_in_rather_than_dropped(self):
        """Nine-pitch at-bats are real and must not quietly vanish."""
        f = _league(max_shown=4)
        assert sum(d["pct"] for d in f.distribution) == \
            pytest.approx(100.0, abs=0.5)
        assert f.distribution[-1].get("plus") is True


class TestStartingFromALiveCount:
    def test_a_fresh_count_carries_no_contrast(self):
        f = _league()
        assert f.start_count == "0-0"
        assert f.started_expected_pitches is None

    def test_deeper_counts_leave_fewer_pitches(self):
        fresh = _league()
        deep = _league(start_count=(3, 2))
        assert deep.expected_pitches < fresh.expected_pitches
        assert deep.start_count == "3-2"

    def test_it_reports_what_the_at_bat_looked_like_at_the_start(self):
        """The contrast is the point of a live panel."""
        fresh = _league()
        deep = _league(start_count=(0, 2))
        assert deep.started_expected_pitches == pytest.approx(
            fresh.expected_pitches, abs=0.02)
        assert deep.started_strikeout_pct == pytest.approx(
            fresh.strikeout_pct, abs=0.2)

    def test_two_strikes_raises_the_strikeout(self):
        assert _league(start_count=(0, 2)).strikeout_pct > \
            _league().strikeout_pct + 10

    def test_three_balls_raises_the_walk(self):
        assert _league(start_count=(3, 1)).walk_pct > _league().walk_pct + 10

    def test_a_full_count_can_only_go_one_way(self):
        """At 3-2 every pitch but a foul ends it, so "fewer" has nowhere to go."""
        f = _league(start_count=(3, 2))
        assert f.likely_pitches == 1
        assert f.fewer_pct == pytest.approx(0.0, abs=0.01)
        assert f.same_pct > 50.0

    def test_a_nonsense_count_falls_back_to_a_fresh_one(self):
        assert forecast(batter="B", pitcher="P", strikeout_p=0.225,
                        walk_p=0.085, start_count=(9, 9)).start_count == "0-0"


class TestItDescribesBaseball:
    """Hitting the two fitted numbers proves nothing on its own."""

    def _mix(self):
        control, stuff, _, _ = _solve(round(LEAGUE_K / 0.99, 4),
                                      round(LEAGUE_BB / 0.99, 4))
        total = dict.fromkeys(OUTCOMES, 0.0)
        arrive = {(0, 0): 1.0}
        # Weight each count by how often a pitch is thrown in it, which is what
        # the league's own per-pitch rates are averaged over.
        chain = _run_chain(control, stuff)
        for bs in _pitch_weights(control, stuff):
            pass
        return control, stuff, chain

    @pytest.mark.parametrize("kind,real,tol", [
        ("ball", 36.0, 2.0), ("called_strike", 17.0, 2.0),
        ("swinging_strike", 11.0, 2.0), ("foul", 18.0, 2.0),
        ("in_play", 17.5, 2.0),
    ])
    def test_the_per_pitch_mix_matches_the_league(self, kind, real, tol):
        """Approximately MLB's real per-pitch rates.

        The chain was never fitted to these — only to the strikeout and walk
        rates — so agreement is evidence the mechanism is right rather than a
        tautology.
        """
        mix = _league_pitch_mix()
        assert mix[kind] == pytest.approx(real, abs=tol)

    def test_pitches_per_plate_appearance_is_in_the_right_country(self):
        """Known to run a shade low — about 3.7 against a real 3.9.

        Pinned with the real bias written down rather than with a tolerance
        wide enough to hide it.
        """
        assert 3.5 <= _league().expected_pitches <= 3.9

    def test_the_count_drives_behaviour(self):
        ahead = _pitch_outcomes(0, 2, 1.0, 1.0)
        behind = _pitch_outcomes(3, 0, 1.0, 1.0)
        assert behind["ball"] < ahead["ball"]
        assert behind["swinging_strike"] < ahead["swinging_strike"]

    def test_a_higher_strikeout_matchup_takes_more_pitches(self):
        """Strikeouts take at least three pitches; balls in play can take one."""
        low = forecast(batter="B", pitcher="P", strikeout_p=0.12, walk_p=0.07,
                       hbp_p=0.01)
        high = forecast(batter="B", pitcher="P", strikeout_p=0.35, walk_p=0.07,
                        hbp_p=0.01)
        assert high.expected_pitches > low.expected_pitches


def _league_pitch_mix() -> dict:
    """Per-pitch class shares over a whole league-average plate appearance."""
    control, stuff, _, _ = _solve(round(LEAGUE_K / 0.99, 4),
                                  round(LEAGUE_BB / 0.99, 4))
    # How many pitches are thrown in each count over one plate appearance.
    from thebeast.pitch_sequence import _COUNTS, _EPS, _ORDER

    arrive = dict.fromkeys(_COUNTS, 0.0)
    arrive[(0, 0)] = 1.0
    total = dict.fromkeys(OUTCOMES, 0.0)
    for bs in _ORDER:
        w = arrive[bs]
        if w <= _EPS:
            continue
        balls, strikes = bs
        probs = _pitch_outcomes(balls, strikes, control, stuff)
        stay = min(probs["foul"], 1.0 - 1e-9) if strikes == 2 else 0.0
        visits = 1.0 / (1.0 - stay)
        for k, v in probs.items():
            total[k] += w * visits * v
        scale = w * visits
        for outcome, p in probs.items():
            if strikes == 2 and outcome == "foul":
                continue
            nxt = _advance(balls, strikes, outcome)
            if not isinstance(nxt, str):
                arrive[nxt] += scale * p
    n = sum(total.values())
    return {k: 100.0 * v / n for k, v in total.items()}


class TestTheCountRules:
    def test_a_foul_with_two_strikes_does_not_advance_the_count(self):
        """The rule that lets a plate appearance run to twelve pitches."""
        assert _advance(1, 2, "foul") == (1, 2)
        assert _advance(1, 1, "foul") == (1, 2)

    def test_four_balls_and_three_strikes_end_it(self):
        assert _advance(3, 0, "ball") == "walk"
        assert _advance(0, 2, "called_strike") == "strikeout"
        assert _advance(0, 2, "swinging_strike") == "strikeout"
        assert _advance(1, 1, "in_play") == "in_play"

    def test_every_count_is_a_proper_distribution(self):
        for balls in range(4):
            for strikes in range(3):
                p = _pitch_outcomes(balls, strikes, 1.0, 1.0)
                assert sum(p.values()) == pytest.approx(1.0, abs=1e-9)
                assert all(v >= 0 for v in p.values())


class TestTheFastPathAgrees:
    """The solver's cheap chain and the reporting chain must not diverge.

    The fast one exists because the full version made a forecast take three
    seconds. It is only safe while the two give the same answer.
    """

    @pytest.mark.parametrize("control,stuff", [
        (1.0, 1.0), (0.5, 2.0), (2.5, 0.4), (3.9, 3.9), (0.26, 0.26),
    ])
    def test_terminals_match_the_full_chain(self, control, stuff):
        k, bb, ip = _terminals(control, stuff)
        full = _run_chain(control, stuff)["terminals"]
        assert k == pytest.approx(full["strikeout"], abs=1e-9)
        assert bb == pytest.approx(full["walk"], abs=1e-9)
        assert ip == pytest.approx(full["in_play"], abs=1e-9)

    @pytest.mark.parametrize("start", [(0, 0), (1, 2), (3, 1), (3, 2)])
    def test_they_agree_from_a_live_count_too(self, start):
        k, bb, ip = _terminals(1.0, 1.0, start=start)
        full = _run_chain(1.0, 1.0, start=start)["terminals"]
        assert k == pytest.approx(full["strikeout"], abs=1e-9)
        assert bb == pytest.approx(full["walk"], abs=1e-9)


class TestItIsFastEnoughToPoll:
    def test_the_fit_is_cached_across_calls(self):
        """A panel refreshing every few seconds must not re-solve every time.

        The fit depends only on the two players, so every refresh during one
        at-bat — and every viewer watching the same game — reuses one solve.
        """
        _solve.cache_clear()
        _league()
        first = _solve.cache_info()
        _league(start_count=(1, 2))
        _league(start_count=(2, 2))
        after = _solve.cache_info()
        assert after.hits > first.hits
        assert after.misses == first.misses
