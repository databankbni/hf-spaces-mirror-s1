"""Statcast data source — wraps pybaseball to fetch PA-level data.

External network calls are isolated in `_fetch_statcast_df` so tests can
patch that single method without touching any internal logic.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import numpy as np
import pandas as pd

from ..models import BatterStatline, PitcherStatline
from ..repository import SQLiteRepository

if TYPE_CHECKING:
    pass

_EVENT_MAP = {
    "single":       "single",
    "double":       "double",
    "triple":       "triple",
    "home_run":     "hr",
    "walk":         "bb",
    "hit_by_pitch": "hbp",
    "intent_walk":  "bb",
    "strikeout":    "k",
    "strikeout_double_play": "k",
    # all other events → ipo
}

_IPO_EVENTS = {
    "field_out", "grounded_into_double_play", "double_play", "triple_play",
    "force_out", "sac_fly", "sac_fly_double_play", "sac_bunt",
    "fielders_choice", "fielders_choice_out", "field_error",
    "other_out", "caught_stealing_2b", "caught_stealing_3b",
    "caught_stealing_home", "pickoff_1b", "pickoff_2b", "pickoff_3b",
    "runner_double_play",
}


def _classify_event(event: str) -> str:
    if event in _EVENT_MAP:
        return _EVENT_MAP[event]
    return "ipo"


def _outcome_rates(pa_df: pd.DataFrame, id_col: str, player_id: int) -> dict[str, float]:
    """Return eight outcome rates for `player_id` summing to 1.0."""
    rows = pa_df[pa_df[id_col] == player_id].copy()
    rows = rows[rows["events"].notna()]
    total = len(rows)
    if total == 0:
        raise ValueError(f"no plate appearances found for player_id={player_id}")

    buckets: dict[str, int] = {k: 0 for k in ["single", "double", "triple", "hr", "bb", "hbp", "k", "ipo"]}
    for evt in rows["events"]:
        buckets[_classify_event(str(evt))] += 1

    return {
        "single_rate": buckets["single"] / total,
        "double_rate": buckets["double"] / total,
        "triple_rate": buckets["triple"] / total,
        "hr_rate": buckets["hr"] / total,
        "bb_rate": buckets["bb"] / total,
        "hbp_rate": buckets["hbp"] / total,
        "k_rate": buckets["k"] / total,
        "ipo_rate": buckets["ipo"] / total,
    }


def _platoon_splits(pa_df: pd.DataFrame, id_col: str, player_id: int,
                    opp_hand_col: str) -> dict[str, float]:
    """Return {vL: mult, vR: mult} platoon multipliers relative to overall rate."""
    rows = pa_df[(pa_df[id_col] == player_id) & pa_df["events"].notna()]
    overall_woba = rows["woba_value"].mean() if len(rows) > 0 else 0.0
    if overall_woba == 0:
        return {"vL": 1.0, "vR": 1.0}
    result = {}
    for hand in ("L", "R"):
        sub = rows[rows[opp_hand_col] == hand]
        if len(sub) < 10:
            result[f"v{hand}"] = 1.0
        else:
            result[f"v{hand}"] = float(np.clip(sub["woba_value"].mean() / overall_woba, 0.5, 2.0))
    return result


class StatcastSource:
    """Fetches Statcast PA-level data and writes BatterStatline / PitcherStatline
    to the repository."""

    def __init__(self, repo: SQLiteRepository) -> None:
        self._repo = repo

    def _fetch_statcast_df(self, player_id: int, season: int, player_type: str) -> pd.DataFrame:
        """Fetch from pybaseball — isolated for test patching."""
        try:
            import pybaseball as pb
        except ImportError as e:
            raise ImportError("pybaseball is required for data fetching: pip install pybaseball") from e
        pb.cache.enable()
        return pb.statcast_batter(
            f"{season}-03-01", f"{season}-11-30", player_id=player_id
        ) if player_type == "batter" else pb.statcast_pitcher(
            f"{season}-03-01", f"{season}-11-30", player_id=player_id
        )

    def fetch_batter(self, player_id: int, season: int) -> BatterStatline:
        df = self._fetch_statcast_df(player_id, season, "batter")
        df = df[df["events"].notna()].copy()
        pa = len(df)

        rates = _outcome_rates(df, "batter", player_id)
        platoon = _platoon_splits(df, "batter", player_id, "p_throws")

        woba = float(df["woba_value"].mean()) if "woba_value" in df else 0.0
        xwoba = float(df["estimated_woba_using_speedangle"].mean()) if "estimated_woba_using_speedangle" in df else 0.0

        # Derive ISO from HR+2B+3B rates (simplified)
        iso = rates["hr_rate"] * 3 + rates["triple_rate"] * 2 + rates["double_rate"]
        babip_events = df[df["events"].isin(["single", "double", "triple",
                                              "field_out", "grounded_into_double_play",
                                              "double_play", "force_out"])]
        hits = len(babip_events[babip_events["events"].isin(["single", "double", "triple"])])
        babip = hits / len(babip_events) if len(babip_events) > 0 else 0.300

        # Infer hand from stand column (most frequent)
        hand = "R"
        if "stand" in df.columns and len(df) > 0:
            h = df["stand"].mode()
            if len(h) > 0:
                hand = str(h.iloc[0])

        b = BatterStatline(
            player_id=player_id,
            name="",
            season=season,
            team_id="",
            hand=hand,  # type: ignore[arg-type]
            pa=pa,
            woba=woba,
            xwoba=xwoba,
            iso=iso,
            babip=babip,
            platoon_split=platoon,
            **rates,
        )
        self._repo.save_batter(b)
        return b

    def fetch_pitcher(
        self,
        player_id: int,
        season: int,
        role: Literal["starter", "reliever"] = "starter",
    ) -> PitcherStatline:
        df = self._fetch_statcast_df(player_id, season, "pitcher")
        df = df[df["events"].notna()].copy()
        bf = len(df)

        rates = _outcome_rates(df, "pitcher", player_id)
        platoon = _platoon_splits(df, "pitcher", player_id, "stand")

        xfip = 0.0  # FanGraphs lookup required; placeholder

        hand = "R"
        if "p_throws" in df.columns and len(df) > 0:
            h = df["p_throws"].mode()
            if len(h) > 0:
                hand = str(h.iloc[0])

        p = PitcherStatline(
            player_id=player_id,
            name="",
            season=season,
            team_id="",
            hand=hand,  # type: ignore[arg-type]
            role=role,
            bf=bf,
            single_allowed=rates["single_rate"],
            double_allowed=rates["double_rate"],
            triple_allowed=rates["triple_rate"],
            hr_allowed=rates["hr_rate"],
            bb_allowed=rates["bb_rate"],
            hbp_allowed=rates["hbp_rate"],
            k_rate=rates["k_rate"],
            ipo_rate=rates["ipo_rate"],
            xfip=xfip,
            platoon_split=platoon,
        )
        self._repo.save_pitcher(p)
        return p
