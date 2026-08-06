"""Fit the totals calibrator: remove the simulator's total-runs over-prediction.

Re-simulates the 2024 holdout (context on, totals-calibration off) and fits a
single scale so the model's mean total matches the actual mean total. Writes
data/totals_calibrator.json.

  uv run python scripts/fit_totals_calibrator.py
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np

from thebeast.data.repository import SQLiteRepository
from thebeast.matchup.calibration import TotalsCalibrator
from thebeast.pipeline import simulate_matchup

LOCAL = Path(__file__).resolve().parent.parent / "local_data"
DB = str(LOCAL / "thebeast.db")
PRED = LOCAL / "predictions.jsonl"
TOTALS = LOCAL / "totals_2024.json"           # written by measure_context.py
OUT = Path(__file__).resolve().parent.parent / "data" / "totals_calibrator.json"


def main() -> int:
    actual = json.loads(TOTALS.read_text())
    games = [json.loads(l) for l in PRED.read_text().splitlines() if l.strip()]
    repo = SQLiteRepository(DB)

    model, act = [], []
    for i, g in enumerate(games, 1):
        gid = g["game_id"]
        if gid not in actual:
            continue
        h, a = gid.rsplit("-", 2)[1:][::-1]  # (home, away)
        res, _ = simulate_matchup(gid, repo, home_team=h, away_team=a, n=150,
                                  seed=7, season=2023, park_season=2023,
                                  calibrate=False, calibrate_totals=False)
        model.append(res.total_mean)
        act.append(actual[gid])
        if i % 500 == 0:
            print(f"  {i}/{len(games)}", flush=True)

    model = np.array(model)
    act = np.array(act)
    cal = TotalsCalibrator.fit(model, act)
    cal_model = model * cal.scale
    print(f"\nfit on {len(model)} games")
    print(f"  actual mean total : {act.mean():.3f}")
    print(f"  model  mean total : {model.mean():.3f}  (bias {model.mean()-act.mean():+.3f})")
    print(f"  scale             : {cal.scale:.4f}")
    print(f"  calibrated mean   : {cal_model.mean():.3f}  (bias {cal_model.mean()-act.mean():+.3f})")
    print(f"  MAE  {np.abs(model-act).mean():.3f} → {np.abs(cal_model-act).mean():.3f}")
    cal.save(OUT)
    print(f"  wrote {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
