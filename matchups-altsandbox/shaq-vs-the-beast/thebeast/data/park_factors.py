"""Park factors from game scores + a weather HR heuristic.

Park RUNS factors use the classic home/road method on final scores (no Statcast,
so team abbreviations match the schedule exactly): for each team, the combined
runs both clubs score in that team's home games vs its road games. A factor of
1.10 means the park inflates scoring 10%. Single-season factors are noisy, so
the raw ratio is regressed halfway toward 1.0 and clamped.

Park factors are keyed by the home-team abbreviation (each club has one park),
stored as ``ParkFactor.venue_id``.

The weather heuristic turns temperature + wind into an HR multiplier: warm air
carries the ball, a tailwind to the outfield adds homers, a headwind kills them.
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import ParkFactor


@dataclass
class _Agg:
    home_runs: float = 0.0
    home_games: int = 0
    road_runs: float = 0.0
    road_games: int = 0


def compute_park_factors(
    games: list,
    season: int,
    regression: float = 0.5,
    clamp: tuple[float, float] = (0.85, 1.20),
) -> list[ParkFactor]:
    """Home/road runs park factors keyed by home-team abbreviation.

    `games` is any sequence with .home_team, .away_team, .home_score, .away_score
    (e.g. GameResultRecord). `regression` shrinks the raw ratio toward 1.0.
    """
    aggs: dict[str, _Agg] = {}
    for g in games:
        total = g.home_score + g.away_score
        home = aggs.setdefault(g.home_team, _Agg())
        home.home_runs += total
        home.home_games += 1
        away = aggs.setdefault(g.away_team, _Agg())
        away.road_runs += total
        away.road_games += 1

    lo, hi = clamp
    factors: list[ParkFactor] = []
    for team, a in aggs.items():
        if a.home_games == 0 or a.road_games == 0:
            continue
        home_rpg = a.home_runs / a.home_games
        road_rpg = a.road_runs / a.road_games
        if road_rpg <= 0:
            continue
        raw = home_rpg / road_rpg
        pf = 1.0 + (raw - 1.0) * regression
        pf = min(max(pf, lo), hi)
        factors.append(ParkFactor(
            venue_id=team, season=season,
            runs_factor=round(pf, 4), hr_factor=1.0, hits_factor=round(pf, 4),
        ))
    return factors


# ── Weather → HR multiplier ───────────────────────────────────────────────────

# Wind direction convention: 0° = blowing straight out to center field (a pure
# tailwind that helps home runs), 180° = straight in (headwind). The outfield
# component is cos(deg), so crosswinds (~90°) are neutral.
import math


def wind_description_to_deg(description: str | None) -> float:
    """Map an MLB game-feed wind string ('Out To CF', 'In From LF', 'L To R') to
    a direction in degrees (0 = out to center, 180 = in from center)."""
    if not description:
        return 90.0
    d = description.lower()
    if "out" in d:
        if "lf" in d or "rf" in d:
            return 30.0   # mostly out, angled
        return 0.0        # out to center
    if "in" in d:
        if "lf" in d or "rf" in d:
            return 150.0
        return 180.0      # in from center
    return 90.0           # 'L To R' / 'R To L' crosswind, or calm


def weather_hr_multiplier(
    temp_f: float | None,
    wind_mph: float | None,
    wind_dir_deg: float | None,
    *,
    temp_per_deg: float = 0.006,
    temp_baseline: float = 70.0,
    wind_per_mph: float = 0.007,
    clamp: tuple[float, float] = (0.80, 1.25),
) -> float:
    """HR multiplier from temperature and wind (1.0 = neutral).

    ~0.6% per °F above 70°F (warm air carries), and ~0.7% per mph times the
    outfield-ward wind component cos(deg) (negative for a headwind).
    """
    mult = 1.0
    if temp_f is not None:
        mult *= 1.0 + (temp_f - temp_baseline) * temp_per_deg
    if wind_mph is not None and wind_dir_deg is not None:
        out = math.cos(math.radians(wind_dir_deg))
        mult *= 1.0 + out * wind_mph * wind_per_mph
    lo, hi = clamp
    return min(max(mult, lo), hi)
