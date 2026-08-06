"""FanGraphs-derived pitching quality data.

Two paths are provided:
  1. `fetch_pitcher_xfip()` — offline ingestion using pybaseball (requires
     network + pybaseball install). Maps FanGraphs IDs → MLBAM IDs via the
     Chadwick bureau crosswalk bundled with pybaseball.
  2. `compute_fip()` — compute FIP directly from an existing PitcherStatline
     using only the Statcast rates already stored. This is the primary path
     used by `ingest.py` to populate `PitcherStatline.xfip` without an extra
     network round-trip.

FIP formula (Tango, 2000):
    FIP = (13·HR + 3·(BB + HBP) − 2·K) / IP + FIP_constant

where FIP_constant ≈ 3.10 (calibrated so FIP ≈ ERA for league-average pitchers).
Converting from rate-per-BF to IP:
    IP = BF · (k_rate + ipo_rate) / 3
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import PitcherStatline

FIP_CONSTANT = 3.10


def compute_fip(p: "PitcherStatline") -> float:
    """Return FIP for a PitcherStatline using its stored rate fields.

    Returns 0.0 when the denominator (outs recorded) is negligible.
    """
    outs_rate = p.k_rate + p.ipo_rate
    if outs_rate < 0.01:
        return 0.0
    numerator = 13 * p.hr_allowed + 3 * (p.bb_allowed + p.hbp_allowed) - 2 * p.k_rate
    # IP per BF = outs_rate / 3; dividing by (outs_rate/3) = multiply by 3/outs_rate
    fip = numerator * 3 / outs_rate + FIP_CONSTANT
    return round(float(fip), 3)


def fetch_pitcher_xfip(season: int) -> dict[int, float]:
    """Download xFIP from FanGraphs via pybaseball → {mlbam_id: xfip}.

    Requires `pybaseball` (offline ingestion only — not a runtime dependency).
    Returns an empty dict if pybaseball is unavailable or the crosswalk fails.
    """
    try:
        import pybaseball as pb
        import pandas as pd
    except ImportError:
        return {}

    try:
        df = pb.fg_pitching_data(season, season, qual=0)
        fg_ids = [int(x) for x in df["playerid"].dropna().tolist()]
        xwalk = pb.playerid_reverse_lookup(fg_ids, key_type="fangraphs")
        id_map: dict[int, int] = {
            int(row["key_fangraphs"]): int(row["key_mlbam"])
            for _, row in xwalk.iterrows()
            if pd.notna(row.get("key_fangraphs")) and pd.notna(row.get("key_mlbam"))
        }
    except Exception:  # network/parse failures are non-fatal
        return {}

    result: dict[int, float] = {}
    xfip_col = "xFIP" if "xFIP" in df.columns else None
    if xfip_col is None:
        return {}
    for _, row in df.iterrows():
        fg_id = row.get("playerid")
        val = row.get(xfip_col)
        if fg_id is None or val is None or pd.isna(val):
            continue
        mlbam = id_map.get(int(fg_id))
        if mlbam:
            result[mlbam] = float(val)
    return result
