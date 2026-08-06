"""Adapters: stored statlines → matchup DNA fingerprints.

The Repository stores BatterStatline / PitcherStatline (already-computed outcome
rates). These converters lift them into BatterDNA / PitcherDNA so stored data
flows straight into the Log5 matchup model without re-deriving from raw frames.
"""
from __future__ import annotations

from ..data.models import BatterStatline, PitcherStatline
from .dna import BatterDNA, PitcherDNA


def batter_dna_from_statline(s: BatterStatline) -> BatterDNA:
    return BatterDNA(
        player_id=s.player_id,
        season=s.season,
        hand=s.hand,
        pa=s.pa,
        single_rate=s.single_rate,
        double_rate=s.double_rate,
        triple_rate=s.triple_rate,
        hr_rate=s.hr_rate,
        bb_rate=s.bb_rate,
        hbp_rate=s.hbp_rate,
        k_rate=s.k_rate,
        ipo_rate=s.ipo_rate,
        platoon_mult=dict(s.platoon_split),
        xwoba=s.xwoba,
    )


def pitcher_dna_from_statline(s: PitcherStatline) -> PitcherDNA:
    return PitcherDNA(
        player_id=s.player_id,
        season=s.season,
        hand=s.hand,
        bf=s.bf,
        role=s.role,
        single_allowed=s.single_allowed,
        double_allowed=s.double_allowed,
        triple_allowed=s.triple_allowed,
        hr_allowed=s.hr_allowed,
        bb_allowed=s.bb_allowed,
        hbp_allowed=s.hbp_allowed,
        k_rate=s.k_rate,
        ipo_rate=s.ipo_rate,
        platoon_mult=dict(s.platoon_split),
        xfip=s.xfip,
    )
