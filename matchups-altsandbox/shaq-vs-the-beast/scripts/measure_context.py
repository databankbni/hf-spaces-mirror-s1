"""Measure the park/weather context effect on total-runs accuracy (2024 holdout).

Re-simulates the holdout games with use_context off vs on and compares the
projected total to the actual game total (MAE + bias). Park/weather move totals,
not win prob, so this is the right metric. No odds needed.

  uv run python scripts/measure_context.py
"""
from __future__ import annotations

import json
import warnings
from datetime import date, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np

from thebeast.data.repository import SQLiteRepository
from thebeast.data.sources.results import MLBResultsSource
from thebeast.pipeline import simulate_matchup

LOCAL = Path(__file__).resolve().parent.parent / "local_data"
DB = str(LOCAL / "thebeast.db")
PRED = LOCAL / "predictions.jsonl"
TOTALS = LOCAL / "totals_2024.json"
SPAN = (date(2024, 3, 28), date(2024, 9, 30))


def actual_totals() -> dict[str, int]:
    if TOTALS.exists():
        return json.loads(TOTALS.read_text())
    src = MLBResultsSource()
    out: dict[str, int] = {}
    cur, end = SPAN
    while cur <= end:
        try:
            for r in src.fetch_results(cur):
                out[r.game_id] = r.home_score + r.away_score
        except Exception:
            pass
        cur += timedelta(days=1)
    TOTALS.write_text(json.dumps(out))
    return out


def main() -> int:
    repo = SQLiteRepository(DB)
    totals = actual_totals()
    print(f"actual totals for {len(totals)} games", flush=True)
    games = [json.loads(l) for l in PRED.read_text().splitlines() if l.strip()]

    def teams(gid):
        _, a, h = gid.rsplit("-", 2)
        return h, a

    rows = []
    for i, g in enumerate(games, 1):
        gid = g["game_id"]
        if gid not in totals:
            continue
        h, a = teams(gid)
        common = dict(home_team=h, away_team=a, n=150, seed=7, season=2023,
                      park_season=2023, calibrate=False, calibrate_totals=False)
        off, _ = simulate_matchup(gid, repo, use_context=False, **common)
        on, _ = simulate_matchup(gid, repo, use_context=True, **common)
        rows.append((totals[gid], off.total_mean, on.total_mean))
        if i % 500 == 0:
            print(f"  {i}/{len(games)}", flush=True)

    actual = np.array([r[0] for r in rows], dtype=float)
    off = np.array([r[1] for r in rows], dtype=float)
    on = np.array([r[2] for r in rows], dtype=float)
    print(f"\n=== TOTAL-RUNS ACCURACY ({len(rows)} games) ===")
    print(f"  actual mean total : {actual.mean():.2f}")
    print(f"  context OFF  MAE  : {np.abs(off - actual).mean():.3f}  bias {off.mean()-actual.mean():+.3f}")
    print(f"  context ON   MAE  : {np.abs(on - actual).mean():.3f}  bias {on.mean()-actual.mean():+.3f}")
    print(f"  mean |Δ| from park/weather : {np.abs(on - off).mean():.3f} runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
