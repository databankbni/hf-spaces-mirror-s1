"""Ingest additional full seasons into local_data/thebeast.db (for multi-season blend)."""
from __future__ import annotations

import sys
import warnings
from datetime import date

warnings.filterwarnings("ignore")

from scripts.calibration_run import _month_ranges  # reuse month splitter
import pandas as pd

from thebeast.data.ingest import fetch_statcast_range, ingest_dataframe
from thebeast.data.repository import SQLiteRepository

DB_PATH = "local_data/thebeast.db"
SPANS = {
    2021: (date(2021, 4, 1), date(2021, 10, 3)),
    2022: (date(2022, 4, 7), date(2022, 10, 5)),
}
MIN_PA = 100
MIN_BF = 100


def main() -> int:
    repo = SQLiteRepository(DB_PATH)
    for season, (start, end) in SPANS.items():
        existing = repo.get_batters_for_season(season)
        if len(existing) > 200:
            print(f"[{season}] already have {len(existing)} batters — skipping", flush=True)
            continue
        frames = []
        for m_start, m_end in _month_ranges(start, end):
            print(f"[{season}] fetching {m_start}..{m_end}", flush=True)
            frames.append(fetch_statcast_range(m_start.isoformat(), m_end.isoformat()))
        df = pd.concat(frames, ignore_index=True)
        n_b, n_p = ingest_dataframe(df, season, repo, min_pa=MIN_PA, min_bf=MIN_BF)
        print(f"[{season}] DONE — {n_b} batters, {n_p} pitchers", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
