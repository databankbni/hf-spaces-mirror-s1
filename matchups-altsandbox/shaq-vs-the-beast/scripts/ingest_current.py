"""Ingest current-season (2026) statlines + bullpens with player names.

Powers upcoming-game predictions in the live demo: current players, real names.
Park factors are stable year to year, so the pipeline reuses 2023 (park_season).

  uv run python scripts/ingest_current.py
"""
from __future__ import annotations

import sys
import warnings
from datetime import date

warnings.filterwarnings("ignore")

from thebeast.data.ingest import (
    build_batter_statlines,
    build_pitcher_statlines,
    build_team_bullpens,
    build_team_rosters,
    fetch_statcast_range,
)
from thebeast.data.repository import SQLiteRepository

DB = "local_data/thebeast.db"
SEASON = 2026
SPAN = ("2026-03-20", date.today().isoformat())
MIN_PA = 30
MIN_BF = 30


_VOWELS = set("aeiou")


def _fmt_name_part(part: str) -> str:
    part = part.strip()
    # Uppercase short vowel-less first names / initials (CJ, JD, AJ, TJ).
    if 1 < len(part) <= 3 and part.isalpha() and not (set(part.lower()) & _VOWELS):
        return part.upper()
    return part.title()


def _names(ids: list[int]) -> dict[int, str]:
    from pybaseball import playerid_reverse_lookup
    if not ids:
        return {}
    df = playerid_reverse_lookup(list(ids), key_type="mlbam")
    out: dict[int, str] = {}
    for _, r in df.iterrows():
        first = _fmt_name_part(str(r.get("name_first", "") or ""))
        last = _fmt_name_part(str(r.get("name_last", "") or ""))
        out[int(r["key_mlbam"])] = f"{first} {last}".strip()
    return out


def main() -> int:
    repo = SQLiteRepository(DB)
    print(f"fetching {SEASON} statcast {SPAN[0]}..{SPAN[1]} …", flush=True)
    df = fetch_statcast_range(*SPAN)
    print(f"  rows: {len(df)}", flush=True)

    batters = build_batter_statlines(df, SEASON, min_pa=MIN_PA)
    pitchers = build_pitcher_statlines(df, SEASON, min_bf=MIN_BF)
    bullpens = build_team_bullpens(df, SEASON, min_bf=100)

    ids = [b.player_id for b in batters] + [p.player_id for p in pitchers]
    print(f"looking up {len(ids)} player names …", flush=True)
    names = _names(ids)
    for s in batters + pitchers:
        s.name = names.get(s.player_id, "")

    for b in batters:
        repo.save_batter(b)
    for p in pitchers:
        repo.save_pitcher(p)
    for pen in bullpens:
        repo.save_pitcher(pen)
    rosters = build_team_rosters(df, SEASON)
    for lc in rosters:
        repo.save_lineup(lc)
    print(f"stored {len(batters)} batters, {len(pitchers)} pitchers, "
          f"{len(bullpens)} bullpens, {len(rosters)} rosters for {SEASON}", flush=True)
    sample = sorted(batters, key=lambda b: -b.woba)[:3]
    print("  top wOBA:", [(b.name, round(b.woba, 3)) for b in sample])
    return 0


if __name__ == "__main__":
    sys.exit(main())
