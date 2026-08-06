"""Re-score the 2023→2024 holdout under a model variant and compare to baseline.

Reuses the already-ingested statlines + saved lineups in local_data/thebeast.db
and the game list in predictions.jsonl (no network), so model changes can be
measured in ~1 minute against the 2099-game baseline.

Usage:
  uv run python scripts/experiment.py --shrink-pa 200 --shrink-bf 300 --n 150
"""
from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

from sklearn.metrics import roc_auc_score

from thebeast.data.repository import SQLiteRepository
from thebeast.matchup.calibration import PlattCalibrator
from thebeast.pipeline import simulate_matchup

LOCAL = Path(__file__).resolve().parent.parent / "local_data"
DB_PATH = str(LOCAL / "thebeast.db")
PRED_PATH = LOCAL / "predictions.jsonl"
TRAIN_SEASON = 2023

# Baseline from the original raw-rate run (no shrinkage).
BASELINE = {"raw_logloss": 0.7176, "auc": 0.5667, "platt_heldout": 0.6826}


def _ll(p, y) -> float:
    p = np.clip(np.asarray(p, float), 1e-15, 1 - 1e-15)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _parse_teams(game_id: str) -> tuple[str, str]:
    # "2024-04-01-ATL-CWS" → date, away, home
    _, away, home = game_id.rsplit("-", 2)
    return home, away


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shrink-pa", type=int, default=200)
    ap.add_argument("--shrink-bf", type=int, default=300)
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--no-bullpen", action="store_true")
    args = ap.parse_args()

    repo = SQLiteRepository(DB_PATH)
    games = [json.loads(l) for l in PRED_PATH.read_text().splitlines() if l.strip()]
    print(f"re-scoring {len(games)} games  shrink_pa={args.shrink_pa} "
          f"shrink_bf={args.shrink_bf} n={args.n}", flush=True)

    probs, y = [], []
    for i, g in enumerate(games, 1):
        home, away = _parse_teams(g["game_id"])
        result, _ = simulate_matchup(
            g["game_id"], repo, home_team=home, away_team=away,
            n=args.n, seed=args.seed, season=TRAIN_SEASON,
            shrink_pa=args.shrink_pa, shrink_bf=args.shrink_bf,
            use_bullpen=not args.no_bullpen,
            calibrate=False, calibrate_totals=False,  # measure the raw model
        )
        probs.append(result.home_win_probability)
        y.append(1 if g["home_won"] else 0)
        if i % 400 == 0:
            print(f"  {i}/{len(games)}", flush=True)

    probs = np.array(probs)
    y = np.array(y)
    n = len(y)
    base = y.mean()

    # Held-out Platt: fit on 60%, evaluate on 40%.
    rng = np.random.default_rng(0)
    idx = rng.permutation(n)
    tr, te = idx[: int(0.6 * n)], idx[int(0.6 * n):]
    cal = PlattCalibrator().fit(probs[tr].tolist(), y[tr].tolist())
    platt_te = cal.transform(probs[te].tolist())

    raw_ll = _ll(probs, y)
    auc = roc_auc_score(y, probs)
    platt_heldout = _ll(platt_te, y[te])
    base_ll = _ll([base] * n, y)

    def delta(new, old, lower_better=True):
        d = new - old
        better = (d < 0) if lower_better else (d > 0)
        return f"{new:.4f}  (Δ {d:+.4f} {'✅' if better else '❌'} vs {old:.4f})"

    print(f"\n=== RESULTS (n={n}, base rate {base:.3f}) ===")
    print(f"  AUC            : {delta(auc, BASELINE['auc'], lower_better=False)}")
    print(f"  raw  log-loss  : {delta(raw_ll, BASELINE['raw_logloss'])}")
    print(f"  base log-loss  : {base_ll:.4f}")
    print(f"  Platt heldout  : {delta(platt_heldout, BASELINE['platt_heldout'])}")
    print(f"  Platt beats base rate: {platt_heldout < _ll([base]*len(te), y[te])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
