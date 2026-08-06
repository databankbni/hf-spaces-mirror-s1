"""Bulk Statcast → statline ingestion.

The per-player StatcastSource issues one network call per player; for a whole
season that is thousands of round-trips. This module instead processes a single
season-wide PA DataFrame (one `pybaseball.statcast(start, end)` pull) and builds
a statline for every batter and pitcher in one vectorized pass — the efficient
path that populates the Repository for backtesting and calibration.

Network is isolated in `fetch_statcast_range`; the builders are pure and tested
against a synthetic DataFrame.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from .models import BatterStatline, PitcherStatline
from .repository import GameRepository
from .sources.statcast import _EVENT_MAP

_BUCKETS = ("single", "double", "triple", "hr", "bb", "hbp", "k", "ipo")


def _bucket(event: object) -> str:
    return _EVENT_MAP.get(str(event), "ipo")


def _rates_from_counts(counts: pd.Series, total: int) -> dict[str, float]:
    return {f"{b}_rate": float(counts.get(b, 0)) / total for b in _BUCKETS}


def _platoon_from_group(group: pd.DataFrame, opp_hand_col: str) -> dict:
    overall = group["woba_value"].mean() if "woba_value" in group else 0.0
    if not overall:
        return {"vL": 1.0, "vR": 1.0}
    out = {}
    for hand in ("L", "R"):
        sub = group[group[opp_hand_col] == hand]
        if len(sub) < 10:
            out[f"v{hand}"] = 1.0
        else:
            out[f"v{hand}"] = float(min(max(sub["woba_value"].mean() / overall, 0.5), 2.0))
    return out


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    df = df[df["events"].notna()].copy()
    df["bucket"] = df["events"].map(_bucket)
    return df


def build_batter_statlines(
    df: pd.DataFrame, season: int, min_pa: int = 50
) -> list[BatterStatline]:
    """One BatterStatline per batter meeting `min_pa`."""
    df = _prepare(df)
    out: list[BatterStatline] = []
    for batter_id, group in df.groupby("batter"):
        total = len(group)
        if total < min_pa:
            continue
        rates = _rates_from_counts(group["bucket"].value_counts(), total)
        hand = str(group["stand"].mode().iloc[0]) if "stand" in group and len(group) else "R"
        iso = rates["hr_rate"] * 3 + rates["triple_rate"] * 2 + rates["double_rate"]
        out.append(BatterStatline(
            player_id=int(batter_id), name="", season=season, team_id="",
            hand=hand,  # type: ignore[arg-type]
            pa=total,
            single_rate=rates["single_rate"], double_rate=rates["double_rate"],
            triple_rate=rates["triple_rate"], hr_rate=rates["hr_rate"],
            bb_rate=rates["bb_rate"], hbp_rate=rates["hbp_rate"],
            k_rate=rates["k_rate"], ipo_rate=rates["ipo_rate"],
            woba=float(group["woba_value"].mean()) if "woba_value" in group else 0.0,
            xwoba=float(group["estimated_woba_using_speedangle"].mean())
                  if "estimated_woba_using_speedangle" in group else 0.0,
            iso=iso, babip=0.300,
            platoon_split=_platoon_from_group(group, "p_throws"),
        ))
    return out


def build_pitcher_statlines(
    df: pd.DataFrame, season: int, min_bf: int = 50
) -> list[PitcherStatline]:
    """One PitcherStatline per pitcher meeting `min_bf`."""
    df = _prepare(df)
    out: list[PitcherStatline] = []
    for pitcher_id, group in df.groupby("pitcher"):
        total = len(group)
        if total < min_bf:
            continue
        rates = _rates_from_counts(group["bucket"].value_counts(), total)
        hand = str(group["p_throws"].mode().iloc[0]) if "p_throws" in group and len(group) else "R"
        # Heuristic role: many batters faced ⇒ likely a starter.
        role = "starter" if total >= 400 else "reliever"
        out.append(PitcherStatline(
            player_id=int(pitcher_id), name="", season=season, team_id="",
            hand=hand,  # type: ignore[arg-type]
            role=role,  # type: ignore[arg-type]
            bf=total,
            single_allowed=rates["single_rate"], double_allowed=rates["double_rate"],
            triple_allowed=rates["triple_rate"], hr_allowed=rates["hr_rate"],
            bb_allowed=rates["bb_rate"], hbp_allowed=rates["hbp_rate"],
            k_rate=rates["k_rate"], ipo_rate=rates["ipo_rate"],
            xfip=0.0,
            platoon_split=_platoon_from_group(group, "stand"),
        ))
    return out


def ingest_dataframe(
    df: pd.DataFrame,
    season: int,
    repo: GameRepository,
    min_pa: int = 50,
    min_bf: int = 50,
) -> tuple[int, int]:
    """Build and persist all statlines from a season DataFrame. Returns counts."""
    batters = build_batter_statlines(df, season, min_pa)
    pitchers = build_pitcher_statlines(df, season, min_bf)
    for b in batters:
        repo.save_batter(b)
    for p in pitchers:
        repo.save_pitcher(p)
    return len(batters), len(pitchers)


import zlib

from .models import LineupCard

ROSTER_GAME_ID = "__roster__"


def build_team_rosters(df: pd.DataFrame, season: int, top: int = 9) -> list[LineupCard]:
    """Each team's `top` most-used batters in `season` — a representative lineup
    for upcoming games whose batting order has not been posted yet.

    Stored as a LineupCard keyed by game_id f'{ROSTER_GAME_ID}-{season}'.
    """
    df = _prepare(df)
    needed = {"batter", "inning_topbot", "home_team", "away_team"}
    if not needed.issubset(df.columns):
        return []
    bat_team = df["away_team"].where(
        df["inning_topbot"].str.lower().str.startswith("top"), df["home_team"]
    )
    out: list[LineupCard] = []
    for team, idx in df.groupby(bat_team).groups.items():
        sub = df.loc[idx]
        order = sub["batter"].value_counts().head(top).index.tolist()
        if len(order) < top:
            continue
        out.append(LineupCard(
            game_id=f"{ROSTER_GAME_ID}-{season}", team_id=str(team),
            batting_order=[int(b) for b in order], starter_id=0,
            bullpen_ids=[], confirmed=False, confirmed_at=None,
        ))
    return out


def team_bullpen_pid(team: str) -> int:
    """Stable synthetic pitcher id for a team's aggregate bullpen."""
    return -(2_000_000 + zlib.crc32(team.encode()))


def build_team_bullpens(
    df: pd.DataFrame, season: int, starter_bf: int = 400, min_bf: int = 200
) -> list[PitcherStatline]:
    """Aggregate each team's relievers into one bullpen statline.

    A pitcher is a reliever if their season batters-faced is below `starter_bf`.
    Each PA is attributed to the pitching team via inning_topbot (the home team
    pitches in the top half). Captures team bullpen quality — an asymmetric,
    win-probability-relevant signal the league-average fallback ignores.
    """
    df = _prepare(df)
    needed = {"pitcher", "inning_topbot", "home_team", "away_team"}
    if not needed.issubset(df.columns):
        return []

    bf_per_pitcher = df["pitcher"].value_counts()
    relievers = set(bf_per_pitcher[bf_per_pitcher < starter_bf].index)
    pen = df[df["pitcher"].isin(relievers)].copy()
    pen["pitch_team"] = pen["home_team"].where(
        pen["inning_topbot"].str.lower().str.startswith("top"), pen["away_team"]
    )

    out: list[PitcherStatline] = []
    for team, group in pen.groupby("pitch_team"):
        total = len(group)
        if total < min_bf:
            continue
        rates = _rates_from_counts(group["bucket"].value_counts(), total)
        out.append(PitcherStatline(
            player_id=team_bullpen_pid(str(team)), name=f"{team} bullpen",
            season=season, team_id=str(team), hand="R", role="reliever", bf=total,
            single_allowed=rates["single_rate"], double_allowed=rates["double_rate"],
            triple_allowed=rates["triple_rate"], hr_allowed=rates["hr_rate"],
            bb_allowed=rates["bb_rate"], hbp_allowed=rates["hbp_rate"],
            k_rate=rates["k_rate"], ipo_rate=rates["ipo_rate"],
            xfip=0.0, platoon_split=_platoon_from_group(group, "stand"),
        ))
    return out


def enrich_sprint_speeds(
    speed_map: dict[int, float],
    season: int,
    repo: "SQLiteRepository",  # type: ignore[name-defined]
) -> int:
    """Stamp sprint_speed_ft_s onto every batter in the repo for `season`.

    Only batters whose MLBAM id appears in `speed_map` are updated. Returns the
    number of statlines updated.
    """
    from dataclasses import replace as dc_replace
    batters = repo.get_batters_for_season(season)
    updated = 0
    for b in batters:
        spd = speed_map.get(b.player_id)
        if spd is not None and b.sprint_speed_ft_s != spd:
            repo.save_batter(dc_replace(b, sprint_speed_ft_s=spd))
            updated += 1
    return updated


def enrich_pitcher_fip(season: int, repo: "SQLiteRepository") -> int:  # type: ignore[name-defined]
    """Compute FIP from stored Statcast rates and write it to PitcherStatline.xfip.

    Operates entirely on data already in the repo — no extra network calls.
    Returns the number of statlines updated.
    """
    from dataclasses import replace as dc_replace
    from .sources.fangraphs import compute_fip
    pitchers = repo.get_pitchers_for_season(season)
    updated = 0
    for p in pitchers:
        fip = compute_fip(p)
        if fip != p.xfip:
            repo.save_pitcher(dc_replace(p, xfip=fip))
            updated += 1
    return updated


def fetch_statcast_range(start: str, end: str) -> pd.DataFrame:
    """Fetch all PA-level Statcast rows in [start, end] (isolated network call)."""
    try:
        import pybaseball as pb
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ImportError("pybaseball is required: pip install pybaseball") from exc
    pb.cache.enable()
    return pb.statcast(start_dt=start, end_dt=end)
