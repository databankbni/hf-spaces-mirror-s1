"""Data transfer objects for thebeast.data.

All rates in BatterStatline and PitcherStatline are PA/BF-level frequencies
(not percentages). Outcome rates on BatterStatline sum to 1.0.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, Optional


@dataclass
class BatterStatline:
    """Per-season Statcast-derived batting profile.

    Outcome rates (single through ipo) must sum to 1.0 within ±1e-6.
    Platoon splits are stored as multipliers relative to the batter's overall
    rate: apply as `rate_vL = rate_overall × platoon_split["vL"]`.
    """
    player_id: int
    name: str
    season: int
    team_id: str
    hand: Literal["L", "R", "S"]   # switch hitter = "S"
    pa: int

    # Eight PA outcome rates (must sum to 1.0)
    single_rate: float
    double_rate: float
    triple_rate: float
    hr_rate: float
    bb_rate: float
    hbp_rate: float
    k_rate: float
    ipo_rate: float

    # Sabermetric descriptors (not used in Log5 directly; calibration + filtering)
    woba: float
    xwoba: float
    iso: float
    babip: float

    # Platoon multipliers; keys "vL" (vs. LHP) and "vR" (vs. RHP)
    platoon_split: dict[str, float] = field(default_factory=lambda: {"vL": 1.0, "vR": 1.0})
    # Baseball Savant sprint speed (ft/s); None when not ingested. League avg ≈ 27 ft/s.
    sprint_speed_ft_s: Optional[float] = None


@dataclass
class PitcherStatline:
    """Per-season Statcast-derived pitching profile.

    Allowed-outcome rates mirror BatterStatline's layout and must sum to 1.0.
    """
    player_id: int
    name: str
    season: int
    team_id: str
    hand: Literal["L", "R"]
    role: Literal["starter", "reliever"]
    bf: int   # batters faced (sample size)

    # Eight outcome rates for balls put in play / walks / strikeouts
    single_allowed: float
    double_allowed: float
    triple_allowed: float
    hr_allowed: float
    bb_allowed: float
    hbp_allowed: float
    k_rate: float
    ipo_rate: float

    # Quality descriptors
    xfip: float

    # Platoon multipliers; keys "vL" (vs. LHB) and "vR" (vs. RHB)
    platoon_split: dict[str, float] = field(default_factory=lambda: {"vL": 1.0, "vR": 1.0})


@dataclass
class GameSchedule:
    """MLB game schedule entry.

    The live-tracking fields (status through inning_half) are populated from
    the same schedule fetch — MLB's API reports current score/inning right on
    the schedule payload once a game has started — so refetching the day's
    schedule is enough to pick up updates; no separate live-feed call needed.
    """
    game_id: str
    date: date
    home_team_id: str
    away_team_id: str
    venue_id: str
    first_pitch: Optional[datetime] = None
    game_pk: Optional[int] = None
    status: Optional[str] = None           # MLB "abstractGameState": Preview | Live | Final
    detailed_state: Optional[str] = None   # e.g. "In Progress", "Final", "Pre-Game"
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    inning: Optional[int] = None
    inning_half: Optional[str] = None      # "Top" | "Bottom"


@dataclass
class LineupCard:
    """Confirmed or projected game lineup for one team."""
    game_id: str
    team_id: str
    batting_order: list[int]     # player_ids, 9 entries, position 0 = leadoff
    starter_id: int
    bullpen_ids: list[int]
    confirmed: bool
    confirmed_at: Optional[datetime] = None


@dataclass
class ParkFactor:
    """Venue-level run environment adjustment.

    All factors are multiplicative: 1.0 = league average.
    > 1.0 means the park boosts that outcome relative to league average.
    """
    venue_id: str
    season: int
    runs_factor: float = 1.0
    hr_factor: float = 1.0
    hits_factor: float = 1.0


@dataclass
class WeatherConditions:
    """Game-time weather at the venue."""
    game_id: str
    temperature_f: float
    wind_mph: float
    wind_direction_deg: float    # 0 = N, 90 = E, 180 = S, 270 = W
    humidity_pct: float
