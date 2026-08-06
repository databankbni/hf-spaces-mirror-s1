"""Is the AUC ceiling model-limited or Monte-Carlo-noise-limited?

Re-scores a sample of holdout games at several sim counts and reports AUC at
each. If AUC climbs with n, the measured ceiling was partly sampling noise (and
more sims is a free accuracy gain); if it plateaus, the limit is model signal.

  uv run python scripts/auc_vs_n.py
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
from sklearn.metrics import roc_auc_score

from thebeast.data.repository import SQLiteRepository
from thebeast.pipeline import simulate_matchup

LOCAL = Path(__file__).resolve().parent.parent / "local_data"
DB = str(LOCAL / "thebeast.db")
PRED = LOCAL / "predictions.jsonl"
SAMPLE = 700
N_VALUES = [150, 600, 2400]


def main() -> int:
    repo = SQLiteRepository(DB)
    games = [json.loads(l) for l in PRED.read_text().splitlines() if l.strip()]
    rng = np.random.default_rng(0)
    idx = rng.permutation(len(games))[:SAMPLE]
    sample = [games[i] for i in idx]
    y = np.array([1 if g["home_won"] else 0 for g in sample])
    print(f"sample {len(sample)} games", flush=True)

    for n in N_VALUES:
        probs = []
        for g in sample:
            h, a = g["game_id"].rsplit("-", 2)[1:][::-1]
            r, _ = simulate_matchup(g["game_id"], repo, home_team=h, away_team=a,
                                    n=n, seed=7, season=2023, park_season=2023,
                                    calibrate=False, calibrate_totals=False)
            probs.append(r.home_win_probability)
        probs = np.array(probs)
        auc = roc_auc_score(y, probs)
        print(f"  n={n:5d}  AUC={auc:.4f}  prob_std={probs.std():.3f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
