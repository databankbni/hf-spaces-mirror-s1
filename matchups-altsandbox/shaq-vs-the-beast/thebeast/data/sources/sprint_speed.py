"""Sprint speed data from Baseball Savant.

Baseball Savant publishes MLBAM-keyed sprint speed (ft/s) for all qualified
players. The CSV endpoint returns one row per player with their mean sprint
speed for the selected season.

Offline ingestion: download and pass to `ingest_sprint_speeds()` in ingest.py.
"""
from __future__ import annotations

import csv
import io
import urllib.request
from typing import Optional

LEAGUE_AVG_FT_S = 27.0  # approximate MLB 2021-2024 average

_URL = (
    "https://baseballsavant.mlb.com/leaderboard/sprint_speed"
    "?min_opp=0&position=&team=&csv=true&year={season}"
)


def fetch_sprint_speeds(season: int) -> dict[int, float]:
    """Download sprint speed leaderboard → {mlbam_id: ft_per_second}."""
    url = _URL.format(season=season)
    with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
        text = resp.read().decode("utf-8")
    return _parse_csv(text)


def load_sprint_speeds(path: str) -> dict[int, float]:
    """Load a previously-downloaded sprint speed CSV from disk."""
    with open(path, encoding="utf-8") as f:
        return _parse_csv(f.read())


def _parse_csv(text: str) -> dict[int, float]:
    reader = csv.DictReader(io.StringIO(text))
    result: dict[int, float] = {}
    for row in reader:
        try:
            pid = int(row["player_id"])
            speed = float(row["sprint_speed"])
            result[pid] = speed
        except (KeyError, ValueError):
            continue
    return result


def speed_factor(speed_map: dict[int, float], player_ids: list[int]) -> float:
    """Return mean sprint speed of player_ids relative to league average.

    Players missing from speed_map default to LEAGUE_AVG_FT_S. A value > 1.0
    means the group is faster than average; the PersonalizedAdvancementMatrix
    uses this to scale advancement probabilities proportionally.
    """
    speeds = [speed_map.get(pid, LEAGUE_AVG_FT_S) for pid in player_ids]
    if not speeds:
        return 1.0
    return sum(speeds) / len(speeds) / LEAGUE_AVG_FT_S
