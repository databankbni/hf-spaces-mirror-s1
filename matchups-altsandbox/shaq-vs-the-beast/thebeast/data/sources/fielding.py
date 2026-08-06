"""Team fielding quality from Baseball Savant Outs Above Average (OAA).

OAA is a statcast-based metric counting how many outs a team converts above
the average given the same opportunities. Positive OAA = better defense.

The CSV endpoint returns one row per team with cumulative season OAA.
Normalization to a multiplicative `fielding_factor`:
    fielding_factor = 1.0 + oaa / TEAM_BIP_PER_SEASON

where TEAM_BIP_PER_SEASON ≈ 1933 (league-avg BIP for a 162-game team-season).
A +50 OAA team gets ~1.026, meaning their opponents see ~2.6% more IPOs.
"""
from __future__ import annotations

import csv
import io
import urllib.request

TEAM_BIP_PER_SEASON = 1933.0  # approx balls-in-play per team per 162-game season

_URL = (
    "https://baseballsavant.mlb.com/leaderboard/outs_above_average"
    "?type=Fielding_Team&startYear={season}&endYear={season}"
    "&min=0&pos=all&team=0&csv=true"
)


def fetch_team_oaa(season: int) -> dict[str, float]:
    """Download team OAA leaderboard → {team_abbr: fielding_factor}."""
    url = _URL.format(season=season)
    with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
        text = resp.read().decode("utf-8")
    return _parse_csv(text)


def load_team_oaa(path: str) -> dict[str, float]:
    """Load a previously-downloaded team OAA CSV from disk."""
    with open(path, encoding="utf-8") as f:
        return _parse_csv(f.read())


def _parse_csv(text: str) -> dict[str, float]:
    reader = csv.DictReader(io.StringIO(text))
    result: dict[str, float] = {}
    for row in reader:
        # Baseball Savant uses 'team_name_alt' for the 3-letter abbreviation
        team = (row.get("team_name_alt") or row.get("team_abbrev") or "").strip().upper()
        oaa_str = row.get("outs_above_average") or row.get("oaa") or ""
        if not team or not oaa_str:
            continue
        try:
            oaa = float(oaa_str)
            result[team] = oaa_to_fielding_factor(oaa)
        except ValueError:
            continue
    return result


def oaa_to_fielding_factor(oaa: float) -> float:
    """Convert a raw OAA value to a multiplicative fielding factor."""
    return 1.0 + oaa / TEAM_BIP_PER_SEASON
