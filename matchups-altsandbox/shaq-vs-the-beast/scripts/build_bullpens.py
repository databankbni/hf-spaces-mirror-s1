"""Build per-team bullpen statlines from 2023 Statcast and store them.

  uv run python scripts/build_bullpens.py
"""
from __future__ import annotations

import sys
import warnings

warnings.filterwarnings("ignore")

from thebeast.data.ingest import build_team_bullpens, fetch_statcast_range, team_bullpen_pid
from thebeast.data.repository import SQLiteRepository

DB = "local_data/thebeast.db"
SEASON = 2023
SPAN = ("2023-03-30", "2023-10-01")


def main() -> int:
    repo = SQLiteRepository(DB)
    if repo.get_pitcher(team_bullpen_pid("NYY"), SEASON) is not None:
        print("bullpens already present — skipping", flush=True)
        return 0
    print(f"fetching {SEASON} statcast …", flush=True)
    df = fetch_statcast_range(*SPAN)
    pens = build_team_bullpens(df, SEASON)
    for p in pens:
        repo.save_pitcher(p)
    pens.sort(key=lambda p: p.hr_allowed)
    print(f"stored {len(pens)} team bullpens")
    print(f"  best HR-suppressing: {pens[0].team_id} hr_allowed={pens[0].hr_allowed:.4f}")
    print(f"  worst:               {pens[-1].team_id} hr_allowed={pens[-1].hr_allowed:.4f}")
    ks = sorted(pens, key=lambda p: -p.k_rate)
    print(f"  best K%: {ks[0].team_id} {ks[0].k_rate:.3f}  | worst K%: {ks[-1].team_id} {ks[-1].k_rate:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
