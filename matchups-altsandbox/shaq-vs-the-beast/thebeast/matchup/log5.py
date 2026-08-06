"""Log5 matchup model — combine BatterDNA + PitcherDNA → PAOutcomeDistribution.

Implements the Bayesian Hierarchical Log5 specified in SPEC.md F-003. The same
multiplicative rate-blending structure mrsim uses for offense-vs-defense, here
applied per outcome class:

    b_adj_o = b_o × batter.platoon_mult[pitcher_hand]
    p_adj_o = p_o × pitcher.platoon_mult[batter_hand]
    raw_o   = b_adj_o × p_adj_o / L_o
    P(o)    = raw_o / Σ_k raw_k

Park/weather: P(hr) ×= context.hr_factor, then renormalize.
"""
from __future__ import annotations

from typing import Optional

from ..simulator.outcome import PAOutcomeDistribution
from .context import GameContext
from .dna import BatterDNA, LeagueAverages, OUTCOMES, PitcherDNA


def league_averages_default(season: int) -> LeagueAverages:
    """Approximate 2021-2024 MLB league-average PA outcome rates."""
    return LeagueAverages(
        season=season,
        single_rate=0.150,
        double_rate=0.047,
        triple_rate=0.005,
        hr_rate=0.036,
        bb_rate=0.085,
        hbp_rate=0.010,
        k_rate=0.225,
        ipo_rate=0.442,
    )


def _platoon_key(opp_hand: str) -> str:
    """Map an opponent handedness to a platoon_mult dict key."""
    return "vL" if opp_hand == "L" else "vR"


# Productive outcome buckets the platoon multiplier scales. A single scalar
# applied to ALL eight buckets cancels under Log5 normalization, so the split
# only shifts mass from outs (k, ipo) toward production (hits, walks, HBP) —
# consistent with how platoon_mult is derived (productive-PA rate ratio).
_PLATOON_MASK = (True, True, True, True, True, True, False, False)


def pa_distribution(
    batter: BatterDNA,
    pitcher: PitcherDNA,
    league: LeagueAverages,
    context: Optional[GameContext] = None,
    use_platoon: bool = True,
    fielding_factor: float = 1.0,
) -> PAOutcomeDistribution:
    """Combine batter & pitcher DNA via Log5 into a normalized PA distribution."""
    b_rates = batter.as_tuple()
    p_rates = pitcher.as_tuple()
    l_rates = league.as_tuple()

    if use_platoon:
        b_mult = batter.platoon_mult.get(_platoon_key(pitcher.hand), 1.0)
        p_mult = pitcher.platoon_mult.get(_platoon_key(batter.hand), 1.0)
    else:
        b_mult = p_mult = 1.0

    raw = []
    for b_o, p_o, l_o, productive in zip(b_rates, p_rates, l_rates, _PLATOON_MASK):
        if l_o <= 0:
            raw.append(0.0)
            continue
        bm = b_mult if productive else 1.0
        pm = p_mult if productive else 1.0
        raw.append((b_o * bm) * (p_o * pm) / l_o)

    # Park/weather context (applied before normalizing):
    #   runs_factor scales every hit bucket (1B/2B/3B/HR) — a hitter's park lifts
    #     all offense, shifting mass off the out buckets → more runs.
    #   hr_factor scales the HR bucket additionally (weather / wind HR tilt).
    # Both teams bat in the same park, so this moves TOTAL runs, not win prob.
    if context is not None:
        if context.runs_factor != 1.0:
            for i in (0, 1, 2, 3):
                raw[i] *= context.runs_factor
        if context.hr_factor != 1.0:
            raw[3] *= context.hr_factor

    # Fielding quality: OAA-derived factor scales the IPO rate before normalization.
    # Better fielding → more batted balls become outs → higher effective IPO rate.
    if fielding_factor != 1.0:
        raw[7] *= fielding_factor

    total = sum(raw)
    if total <= 0:
        # Degenerate inputs — fall back to league average.
        probs = list(l_rates)
        total = sum(probs)
    else:
        probs = raw
    probs = [v / total for v in probs]

    return PAOutcomeDistribution(
        batter_id=batter.player_id,
        pitcher_id=pitcher.player_id,
        single=probs[0],
        double=probs[1],
        triple=probs[2],
        home_run=probs[3],
        walk=probs[4],
        hit_by_pitch=probs[5],
        strikeout=probs[6],
        in_play_out=probs[7],
    )
