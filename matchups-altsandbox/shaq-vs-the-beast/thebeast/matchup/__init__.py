"""thebeast.matchup — Bayesian Log5 matchup model + DNA fingerprints (F-003)."""
from __future__ import annotations

from .context import GameContext
from .dna import (
    BatterDNA,
    LeagueAverages,
    PitcherDNA,
    build_batter_dna,
    build_pitcher_dna,
    synthetic_batter,
    synthetic_pitcher,
)
from .log5 import league_averages_default, pa_distribution

__all__ = [
    "BatterDNA",
    "PitcherDNA",
    "LeagueAverages",
    "GameContext",
    "build_batter_dna",
    "build_pitcher_dna",
    "synthetic_batter",
    "synthetic_pitcher",
    "pa_distribution",
    "league_averages_default",
]
