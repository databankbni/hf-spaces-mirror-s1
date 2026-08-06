"""Batter/Pitcher DNA — statistical fingerprints driving the matchup model.

The baseball analog of mrsim's TeamDNA (see ~/src/mrsim/mrsim/team.py):
  - TeamDNA              → BatterDNA / PitcherDNA
  - build_team_dna       → build_batter_dna / build_pitcher_dna
  - synthetic_team       → synthetic_batter / synthetic_pitcher

A DNA holds the eight PA-outcome rates (summing to ~1.0), platoon multipliers
keyed by the opponent's handedness ("vL"/"vR"), and a sample size used to shrink
low-volume players toward league average (Bayesian Log5 prior, U-001).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

import pandas as pd


# The eight mutually-exclusive PA outcome buckets, in canonical order.
OUTCOMES = ("single", "double", "triple", "hr", "bb", "hbp", "k", "ipo")


@dataclass
class LeagueAverages:
    """League-average outcome rates — the Log5 denominator for one season."""
    season: int
    single_rate: float
    double_rate: float
    triple_rate: float
    hr_rate: float
    bb_rate: float
    hbp_rate: float
    k_rate: float
    ipo_rate: float

    def as_tuple(self) -> tuple[float, ...]:
        return (self.single_rate, self.double_rate, self.triple_rate,
                self.hr_rate, self.bb_rate, self.hbp_rate,
                self.k_rate, self.ipo_rate)


@dataclass
class BatterDNA:
    """Statistical fingerprint built from a batter's PA-level Statcast data."""
    player_id: int
    season: int
    hand: Literal["L", "R", "S"]
    pa: int
    single_rate: float
    double_rate: float
    triple_rate: float
    hr_rate: float
    bb_rate: float
    hbp_rate: float
    k_rate: float
    ipo_rate: float
    # Platoon multipliers relative to overall rate, keyed by pitcher hand.
    platoon_mult: dict = field(default_factory=lambda: {"vL": 1.0, "vR": 1.0})
    xwoba: float = 0.320
    exit_velo_mean: float = 88.0

    def as_tuple(self) -> tuple[float, ...]:
        return (self.single_rate, self.double_rate, self.triple_rate,
                self.hr_rate, self.bb_rate, self.hbp_rate,
                self.k_rate, self.ipo_rate)


@dataclass
class PitcherDNA:
    """Statistical fingerprint for a pitcher (starter or reliever)."""
    player_id: int
    season: int
    hand: Literal["L", "R"]
    bf: int
    role: Literal["starter", "reliever"]
    single_allowed: float
    double_allowed: float
    triple_allowed: float
    hr_allowed: float
    bb_allowed: float
    hbp_allowed: float
    k_rate: float
    ipo_rate: float
    platoon_mult: dict = field(default_factory=lambda: {"vL": 1.0, "vR": 1.0})
    xfip: float = 4.00

    def as_tuple(self) -> tuple[float, ...]:
        return (self.single_allowed, self.double_allowed, self.triple_allowed,
                self.hr_allowed, self.bb_allowed, self.hbp_allowed,
                self.k_rate, self.ipo_rate)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _outcome_rates(df: pd.DataFrame, event_col: str = "event") -> dict:
    """Count each outcome bucket and return rates summing to 1.0."""
    n = len(df)
    if n == 0:
        raise ValueError("cannot build DNA from an empty frame")
    counts = df[event_col].value_counts()
    return {o: float(counts.get(o, 0)) / n for o in OUTCOMES}


def _shrink(rate: float, league_rate: float, sample: int, shrink: int) -> float:
    """Bayesian shrinkage toward league average (U-001).

    Equivalent to a Beta/Dirichlet prior with `shrink` pseudo-observations at
    the league rate: (rate·n + league·shrink) / (n + shrink).
    """
    return (rate * sample + league_rate * shrink) / (sample + shrink)


def _platoon_mult(df: pd.DataFrame, base: dict, hand_col: str = "opp_hand") -> dict:
    """Compute {vL, vR} multipliers from relative on-base+slug proxy by opp hand.

    Uses a simple "productive PA" proxy: hits + walks + hbp per PA, relative to
    the player's overall rate. Falls back to 1.0 when a split is empty.
    """
    if hand_col not in df.columns:
        return {"vL": 1.0, "vR": 1.0}
    productive = {"single", "double", "triple", "hr", "bb", "hbp"}
    overall = df["event"].isin(productive).mean()
    if overall <= 0:
        return {"vL": 1.0, "vR": 1.0}
    mult = {}
    for key, hand in (("vL", "L"), ("vR", "R")):
        sub = df[df[hand_col] == hand]
        if len(sub) == 0:
            mult[key] = 1.0
        else:
            split = sub["event"].isin(productive).mean()
            mult[key] = float(split / overall) if overall > 0 else 1.0
    return mult


# ── Builders ──────────────────────────────────────────────────────────────────

def build_batter_dna(
    player_id: int,
    season: int,
    statcast: pd.DataFrame,
    league: LeagueAverages,
    hand: str = "R",
    shrink_pa: int = 200,
) -> BatterDNA:
    """Build a BatterDNA from PA-level rows, shrinking rates toward league avg."""
    pa = len(statcast)
    rates = _outcome_rates(statcast)
    lg = dict(zip(OUTCOMES, league.as_tuple()))
    shrunk = {o: _shrink(rates[o], lg[o], pa, shrink_pa) for o in OUTCOMES}
    total = sum(shrunk.values())
    shrunk = {o: v / total for o, v in shrunk.items()}
    return BatterDNA(
        player_id=player_id,
        season=season,
        hand=hand,  # type: ignore[arg-type]
        pa=pa,
        single_rate=shrunk["single"],
        double_rate=shrunk["double"],
        triple_rate=shrunk["triple"],
        hr_rate=shrunk["hr"],
        bb_rate=shrunk["bb"],
        hbp_rate=shrunk["hbp"],
        k_rate=shrunk["k"],
        ipo_rate=shrunk["ipo"],
        platoon_mult=_platoon_mult(statcast, shrunk),
    )


def build_pitcher_dna(
    player_id: int,
    season: int,
    statcast: pd.DataFrame,
    league: LeagueAverages,
    hand: str = "R",
    role: str = "starter",
    shrink_bf: int = 300,
) -> PitcherDNA:
    """Build a PitcherDNA from PA-level rows, shrinking rates toward league avg."""
    bf = len(statcast)
    rates = _outcome_rates(statcast)
    lg = dict(zip(OUTCOMES, league.as_tuple()))
    shrunk = {o: _shrink(rates[o], lg[o], bf, shrink_bf) for o in OUTCOMES}
    total = sum(shrunk.values())
    shrunk = {o: v / total for o, v in shrunk.items()}
    return PitcherDNA(
        player_id=player_id,
        season=season,
        hand=hand,  # type: ignore[arg-type]
        bf=bf,
        role=role,  # type: ignore[arg-type]
        single_allowed=shrunk["single"],
        double_allowed=shrunk["double"],
        triple_allowed=shrunk["triple"],
        hr_allowed=shrunk["hr"],
        bb_allowed=shrunk["bb"],
        hbp_allowed=shrunk["hbp"],
        k_rate=shrunk["k"],
        ipo_rate=shrunk["ipo"],
        platoon_mult=_platoon_mult(statcast, shrunk),
    )


# ── Shrinkage of an existing DNA toward league average ────────────────────────

def _shrink_rates(rates: tuple[float, ...], league: "LeagueAverages",
                  sample: int, k: int) -> dict[str, float]:
    lg = dict(zip(OUTCOMES, league.as_tuple()))
    cur = dict(zip(OUTCOMES, rates))
    shrunk = {o: _shrink(cur[o], lg[o], sample, k) for o in OUTCOMES}
    total = sum(shrunk.values())
    return {o: v / total for o, v in shrunk.items()}


def shrink_batter_dna(dna: BatterDNA, league: "LeagueAverages", k: int = 200) -> BatterDNA:
    """Regress a batter's rates toward league average by its PA sample size.

    Stored statlines hold raw rates; low-PA players carry noisy extremes that
    compound into overconfident win probabilities. `k` is the prior strength in
    pseudo-PAs (a player with `k` PA is weighted 50/50 with the league mean).
    """
    s = _shrink_rates(dna.as_tuple(), league, dna.pa, k)
    return BatterDNA(
        player_id=dna.player_id, season=dna.season, hand=dna.hand, pa=dna.pa,
        single_rate=s["single"], double_rate=s["double"], triple_rate=s["triple"],
        hr_rate=s["hr"], bb_rate=s["bb"], hbp_rate=s["hbp"],
        k_rate=s["k"], ipo_rate=s["ipo"],
        platoon_mult=dict(dna.platoon_mult), xwoba=dna.xwoba,
        exit_velo_mean=dna.exit_velo_mean,
    )


def shrink_pitcher_dna(dna: PitcherDNA, league: "LeagueAverages", k: int = 300) -> PitcherDNA:
    """Regress a pitcher's allowed rates toward league average by its BF size."""
    s = _shrink_rates(dna.as_tuple(), league, dna.bf, k)
    return PitcherDNA(
        player_id=dna.player_id, season=dna.season, hand=dna.hand, bf=dna.bf,
        role=dna.role,
        single_allowed=s["single"], double_allowed=s["double"], triple_allowed=s["triple"],
        hr_allowed=s["hr"], bb_allowed=s["bb"], hbp_allowed=s["hbp"],
        k_rate=s["k"], ipo_rate=s["ipo"],
        platoon_mult=dict(dna.platoon_mult), xfip=dna.xfip,
    )


# ── Synthetic (league-average) fingerprints for tests ─────────────────────────

def synthetic_batter(hand: str = "R") -> BatterDNA:
    """A league-average synthetic batter — no database access required."""
    return BatterDNA(
        player_id=0,
        season=0,
        hand=hand,  # type: ignore[arg-type]
        pa=600,
        single_rate=0.150,
        double_rate=0.047,
        triple_rate=0.005,
        hr_rate=0.036,
        bb_rate=0.085,
        hbp_rate=0.010,
        k_rate=0.225,
        ipo_rate=0.442,
        platoon_mult={"vL": 1.0, "vR": 1.0},
    )


def synthetic_pitcher(role: str = "starter") -> PitcherDNA:
    """A league-average synthetic pitcher — no database access required."""
    return PitcherDNA(
        player_id=0,
        season=0,
        hand="R",
        bf=700,
        role=role,  # type: ignore[arg-type]
        single_allowed=0.150,
        double_allowed=0.047,
        triple_allowed=0.005,
        hr_allowed=0.036,
        bb_allowed=0.085,
        hbp_allowed=0.010,
        k_rate=0.225,
        ipo_rate=0.442,
        platoon_mult={"vL": 1.0, "vR": 1.0},
    )
