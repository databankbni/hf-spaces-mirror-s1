"""GameContext — per-game adjustments applied to DNA before simulation.

Mirrors mrsim's context.py: a small struct carrying park-factor and weather
multipliers that the matchup model folds into the PA distribution.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass
class GameContext:
    """Per-game context applied to the matchup before simulation."""
    game_id: str
    venue_id: str
    temperature_f: Optional[float] = None
    wind_mph: Optional[float] = None
    wind_direction_deg: Optional[float] = None
    roof: Optional[Literal["dome", "open", "outdoors"]] = None
    # Filled from a ParkFactor lookup (multiplicative; 1.0 = league average).
    hr_factor: float = 1.0
    runs_factor: float = 1.0
    # OAA-derived fielding quality for each team (> 1.0 = converts more BIP to outs).
    home_fielding_factor: float = 1.0
    away_fielding_factor: float = 1.0
