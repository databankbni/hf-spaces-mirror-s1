"""Fit the production Platt calibrator from the 2023→2024 holdout predictions.

Reads local_data/predictions.jsonl (model home-win prob + actual outcome per
game) and writes the two-parameter calibrator to data/calibrator.json, which the
pipeline loads at inference to de-bias the simulator's overconfident win probs.

  uv run python scripts/fit_calibrator.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from thebeast.matchup.calibration import PlattCalibrator, reliability_curve

ROOT = Path(__file__).resolve().parent.parent
PRED = ROOT / "local_data" / "predictions.jsonl"
OUT = ROOT / "data" / "calibrator.json"


def main() -> int:
    recs = [json.loads(l) for l in PRED.read_text().splitlines() if l.strip()]
    probs = [r["model_home_win_prob"] for r in recs]
    y = [1 if r["home_won"] else 0 for r in recs]

    cal = PlattCalibrator().fit(probs, y)
    adjusted = cal.transform(probs)

    pre = reliability_curve(probs, y)
    post = reliability_curve(adjusted, y)
    print(f"fit on {len(recs)} games")
    print(f"  params           : {cal.to_dict()}")
    print(f"  raw  prob range  : [{min(probs):.3f}, {max(probs):.3f}]")
    print(f"  calib prob range : [{min(adjusted):.3f}, {max(adjusted):.3f}]")
    print(f"  max decile dev   : {pre.max_deviation:.3f} → {post.max_deviation:.3f}")

    cal.save(OUT)
    print(f"  wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
