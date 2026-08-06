#!/usr/bin/env python3
"""research/ml_confidence_sweep.py — find the max-class-proba threshold that makes the
HIGH-confidence bucket reach a target direction accuracy (default 75%).

Reuses the OOS holdout rows in training_data.csv (date ≥ manifest.holdout_start) and the
model's own calibrated classifier probabilities (confidence_prob = max class proba). For a
grid of thresholds it reports, per timeframe and aggregate:
  • HIGH bucket size (coverage %) at that threshold
  • 3-class direction accuracy of the HIGH bucket (matches ml_backtest's dir_correct)
  • directional-only accuracy (BULLISH/BEARISH picks only — what you actually trade)

Point it at any model dir via ML_MODEL_DIR:
    ML_MODEL_DIR=/tmp/ml_eval_model python research/ml_confidence_sweep.py
    ML_MODEL_DIR=/tmp/ml_eval_model python research/ml_confidence_sweep.py --target 0.75
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from ml_predictor.features import FEATURE_COLUMNS, TIMEFRAMES  # noqa: E402
from ml_predictor.infer import MLPredictor  # noqa: E402

DEFAULT_CSV = os.path.join(_PROJ_ROOT, "ml_predictor", "training_data.csv")
_DIRC = {"INTRADAY": "dir_INTRADAY", "1D": "dir_1D", "3D": "dir_3D"}


def _bucket_stats(maxp: np.ndarray, pred_dir: np.ndarray, true_dir: np.ndarray, thr: float):
    """Return (coverage%, 3class_acc%, directional_acc%, n_high) for maxp >= thr."""
    sel = maxp >= thr
    n = int(sel.sum())
    if n == 0:
        return 0.0, float("nan"), float("nan"), 0
    cov = n / len(maxp) * 100.0
    acc3 = float((pred_dir[sel] == true_dir[sel]).mean()) * 100.0
    # directional-only: predictions that are BULLISH or BEARISH (exclude NEUTRAL calls)
    dmask = sel & np.isin(pred_dir, ["BULLISH", "BEARISH"])
    nd = int(dmask.sum())
    accd = float((pred_dir[dmask] == true_dir[dmask]).mean()) * 100.0 if nd else float("nan")
    return cov, acc3, accd, n


def run(csv_path: str, target: float) -> None:
    predictor = MLPredictor()
    if not predictor.available:
        raise SystemExit("model not loaded — train first (ML_MODEL_DIR to isolate).")

    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["date"])
    holdout_start = predictor.manifest.get("holdout_start")
    oos = df[df["date"] >= pd.to_datetime(holdout_start)].copy() if holdout_start else df
    if oos.empty:
        raise SystemExit("no OOS rows.")
    print(f"  Model dir: {os.environ.get('ML_MODEL_DIR', 'ml_predictor/models')}")
    print(f"  OOS rows (date ≥ {holdout_start}): {len(oos):,}")
    cur_hi = predictor.manifest.get("tf", {}).get("1D", {}).get("conf_hi")
    print(f"  Current conf_hi = {cur_hi}\n")

    feat_mat = oos[FEATURE_COLUMNS].to_numpy(dtype=float)
    grid = [round(x, 3) for x in np.arange(0.45, 0.901, 0.05)]

    # collect per-tf arrays
    per_tf = {}
    for tf in TIMEFRAMES:
        _, proba_m, classes = predictor._raw_predict(tf, feat_mat)
        classes = np.array([str(c) for c in classes])
        maxp = proba_m.max(axis=1)
        pred_dir = classes[proba_m.argmax(axis=1)]
        true_dir = oos[_DIRC[tf]].astype(str).to_numpy()
        per_tf[tf] = (maxp, pred_dir, true_dir)

    for tf in TIMEFRAMES:
        maxp, pred_dir, true_dir = per_tf[tf]
        base3 = (pred_dir == true_dir).mean() * 100
        print(f"── {tf} ──  (all-rows 3-class acc={base3:.0f}%, maxproba range "
              f"{maxp.min():.2f}..{maxp.max():.2f})")
        print(f"  {'thr':>5} {'HIGH cov%':>9} {'3class acc%':>12} {'dir-only acc%':>14} {'nHIGH':>7}")
        hit_thr = None
        for thr in grid:
            cov, acc3, accd, nh = _bucket_stats(maxp, pred_dir, true_dir, thr)
            flag = ""
            if acc3 >= target * 100 and hit_thr is None and nh >= 30:
                hit_thr = thr
                flag = "  <- 3class≥%d%%" % int(target * 100)
            a3 = f"{acc3:.0f}" if not np.isnan(acc3) else "-"
            ad = f"{accd:.0f}" if not np.isnan(accd) else "-"
            print(f"  {thr:>5.2f} {cov:>8.1f}% {a3:>12} {ad:>14} {nh:>7}{flag}")
        if hit_thr is None:
            print(f"  → target {int(target*100)}% 3-class NOT reachable with ≥30 picks (signal ceiling)\n")
        else:
            print(f"  → conf_hi ≈ {hit_thr:.2f} gives ≥{int(target*100)}% 3-class HIGH\n")

    # aggregate (pooled across TFs), matching ml_backtest's overall HIGH number
    allp = np.concatenate([per_tf[tf][0] for tf in TIMEFRAMES])
    allpred = np.concatenate([per_tf[tf][1] for tf in TIMEFRAMES])
    alltrue = np.concatenate([per_tf[tf][2] for tf in TIMEFRAMES])
    print("── AGGREGATE (all TFs pooled — matches ml_backtest HIGH bucket) ──")
    print(f"  {'thr':>5} {'HIGH cov%':>9} {'3class acc%':>12} {'dir-only acc%':>14} {'nHIGH':>7}")
    for thr in grid:
        cov, acc3, accd, nh = _bucket_stats(allp, allpred, alltrue, thr)
        a3 = f"{acc3:.0f}" if not np.isnan(acc3) else "-"
        ad = f"{accd:.0f}" if not np.isnan(accd) else "-"
        print(f"  {thr:>5.2f} {cov:>8.1f}% {a3:>12} {ad:>14} {nh:>7}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=DEFAULT_CSV)
    ap.add_argument("--target", type=float, default=0.75, help="target HIGH-bucket 3-class accuracy")
    args = ap.parse_args()
    run(args.csv, args.target)


if __name__ == "__main__":
    main()
