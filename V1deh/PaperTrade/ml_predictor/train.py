#!/usr/bin/env python3
"""ml_predictor/train.py — fit the quantile-regression price model.

For each timeframe TF ∈ {INTRADAY, 1D, 3D} we train 5 sklearn HistGradientBoosting
estimators (15 total artifacts), all native to scikit-learn (already in
requirements.txt — no lightgbm/xgboost/torch, so HF Spaces builds cleanly):

  up_q50   HistGradientBoostingRegressor(loss="quantile", quantile=0.50)  → median best-up excursion
  up_q90   HistGradientBoostingRegressor(loss="quantile", quantile=0.90)  → optimistic high
  down_q50 quantile=0.50 on the worst-down excursion                       → median dip depth
  down_q10 quantile=0.10 on the worst-down excursion                       → downside/stop floor
  direction HistGradientBoostingClassifier(class_weight="balanced")        → BULLISH/BEARISH/NEUTRAL

Time-based split (no leakage): train on rows on/before `cutoff = max_date - HOLDOUT_MONTHS`,
with a TRADING-DAY embargo dropping rows whose 3-day label window crosses the cutoff.
Writes joblib artifacts + manifest.json to ml_predictor/models/.

Usage (from project root, after dataset.py):
    python ml_predictor/train.py
    python ml_predictor/train.py --csv ml_predictor/training_data.csv --holdout-months 5
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from datetime import timedelta

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

import joblib  # noqa: E402
import sklearn  # noqa: E402
from sklearn.ensemble import HistGradientBoostingRegressor, HistGradientBoostingClassifier  # noqa: E402
from sklearn.calibration import CalibratedClassifierCV  # noqa: E402

from ml_predictor.features import FEATURE_COLUMNS, TIMEFRAMES  # noqa: E402

# MODEL_DIR / CSV overridable via env for safe A/B experiments (train a variant to a temp
# dir + point infer/backtest at it via ML_MODEL_DIR without clobbering the production model).
MODEL_DIR = os.environ.get("ML_MODEL_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "models"))
DEFAULT_CSV = os.environ.get("ML_CSV", os.path.join(os.path.dirname(os.path.abspath(__file__)), "training_data.csv"))

HOLDOUT_MONTHS = 5      # last N months held out as the test window
EMBARGO_DAYS = 5        # calendar-day gap between train-end and holdout (label window is ≤3 trading days)
MIN_TRAIN_ROWS = 500

# Label column per (target, TF).
_UP_LABEL = {"INTRADAY": "up_INTRADAY", "1D": "up_1D", "3D": "up_3D"}
_DN_LABEL = {"INTRADAY": "dn_INTRADAY", "1D": "dn_1D", "3D": "dn_3D"}
_DIR_LABEL = {"INTRADAY": "dir_INTRADAY", "1D": "dir_1D", "3D": "dir_3D"}

# Hyperparameters (env-overridable for tuning experiments).
_MAX_ITER = int(os.environ.get("ML_MAX_ITER", "300"))
_MAX_LEAVES = int(os.environ.get("ML_MAX_LEAVES", "31"))
_LR = float(os.environ.get("ML_LR", "0.06"))
_MIN_LEAF = int(os.environ.get("ML_MIN_LEAF", "60"))
_L2 = float(os.environ.get("ML_L2", "1.0"))
_REG_PARAMS = dict(max_iter=_MAX_ITER, max_leaf_nodes=_MAX_LEAVES, learning_rate=_LR,
                   min_samples_leaf=_MIN_LEAF, l2_regularization=_L2, random_state=42)
_CLF_PARAMS = dict(max_iter=_MAX_ITER, max_leaf_nodes=_MAX_LEAVES, learning_rate=_LR,
                   min_samples_leaf=_MIN_LEAF, l2_regularization=_L2, random_state=42,
                   class_weight="balanced")


def _fit_quantile(X, y, q):
    m = HistGradientBoostingRegressor(loss="quantile", quantile=q, **_REG_PARAMS)
    m.fit(X, y)
    return m


def train_all(csv_path: str = DEFAULT_CSV, out_dir: str = MODEL_DIR,
              holdout_months: int = HOLDOUT_MONTHS) -> dict:
    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["date"])
    max_date = df["date"].max()
    cutoff = max_date - pd.DateOffset(months=holdout_months)
    train_end = cutoff - timedelta(days=EMBARGO_DAYS)
    print(f"  Rows: {len(df):,} · dates {df['date'].min().date()} → {max_date.date()}")
    print(f"  Train ≤ {train_end.date()} (embargo {EMBARGO_DAYS}d) · holdout {cutoff.date()} → {max_date.date()}")

    train_df = df[df["date"] <= train_end]
    test_df = df[df["date"] >= cutoff]
    print(f"  Train rows: {len(train_df):,} · Holdout rows: {len(test_df):,}")
    if len(train_df) < MIN_TRAIN_ROWS:
        raise SystemExit(f"Not enough training rows ({len(train_df)} < {MIN_TRAIN_ROWS}). "
                         f"Build a denser CSV (dataset.py --step 1) or reduce --holdout-months.")

    os.makedirs(out_dir, exist_ok=True)
    X_tr_full = train_df[FEATURE_COLUMNS].to_numpy(dtype=float)

    manifest = {
        "sklearn_version": sklearn.__version__,
        "feature_columns": FEATURE_COLUMNS,
        "timeframes": TIMEFRAMES,
        "train_cutoff": str(train_end.date()),
        "holdout_start": str(cutoff.date()),
        "max_date": str(max_date.date()),
        "n_train_rows": int(len(train_df)),
        "quantiles": {"up": [0.10, 0.50, 0.90], "down": [0.10, 0.50, 0.90]},
        # Whether 1D/3D direction labels are EXCESS-of-Nifty (alpha). Mirrors dataset.py's
        # ML_EXCESS_LABELS default; consumed by infer.py to set each TF's dir_basis so the UI
        # can say "outperform/underperform vs Nifty" instead of a misleading absolute call.
        "excess_labels": os.environ.get("ML_EXCESS_LABELS", "1") != "0",
        "tf": {},
    }

    for tf in TIMEFRAMES:
        print(f"\n  ── {tf} ──")
        up_y = train_df[_UP_LABEL[tf]].to_numpy(dtype=float)
        dn_y = train_df[_DN_LABEL[tf]].to_numpy(dtype=float)
        dir_y = train_df[_DIR_LABEL[tf]].astype(str).to_numpy()

        # Drop rows with NaN labels (features may contain NaN — HistGBM handles them).
        up_ok = np.isfinite(up_y)
        dn_ok = np.isfinite(dn_y)

        # up-excursion quantiles: q10 = easily-reached floor, q50 = expected high, q90 = optimistic.
        up_q10 = _fit_quantile(X_tr_full[up_ok], up_y[up_ok], 0.10)
        up_q50 = _fit_quantile(X_tr_full[up_ok], up_y[up_ok], 0.50)
        up_q90 = _fit_quantile(X_tr_full[up_ok], up_y[up_ok], 0.90)
        # down-excursion quantiles: q10 = deep worst-case (stop floor), q50 = median dip (buy level),
        # q90 = shallow dip closest to 0 (easily-reached bearish range bound).
        down_q10 = _fit_quantile(X_tr_full[dn_ok], dn_y[dn_ok], 0.10)
        down_q50 = _fit_quantile(X_tr_full[dn_ok], dn_y[dn_ok], 0.50)
        down_q90 = _fit_quantile(X_tr_full[dn_ok], dn_y[dn_ok], 0.90)

        # Direction classifier with ISOTONIC PROBABILITY CALIBRATION (improvement "c").
        # The raw HistGBM proba was over-confident; CalibratedClassifierCV(cv=3) maps it to
        # empirical frequencies so max-proba is a trustworthy P(correct) — the basis for the
        # HIGH/MEDIUM/LOW label (previously derived from band-width, which anti-correlated
        # with returns per the diagnostics).
        clf = CalibratedClassifierCV(
            HistGradientBoostingClassifier(**_CLF_PARAMS), method="isotonic", cv=3)
        clf.fit(X_tr_full, dir_y)

        for name, mdl in [("up_q10", up_q10), ("up_q50", up_q50), ("up_q90", up_q90),
                          ("down_q10", down_q10), ("down_q50", down_q50), ("down_q90", down_q90),
                          ("direction", clf)]:
            joblib.dump(mdl, os.path.join(out_dir, f"{tf}_{name}.joblib"))

        # ── Per-TF metadata: band width + calibrated-confidence thresholds ──
        p_up10 = up_q10.predict(X_tr_full)
        p_up90 = np.maximum(up_q90.predict(X_tr_full), p_up10)  # monotonic
        median_band = float(np.median(p_up90 - p_up10))
        dir_classes = list(clf.classes_)
        # Confidence thresholds = ABSOLUTE, tied to the calibrated max-class probability's
        # reliability relative to the random baseline (1/n_classes). Because the classifier is
        # isotonic-calibrated, max_proba ≈ P(direction correct), so these thresholds mean the
        # same thing across timeframes and stocks. This replaced the old per-TF TERTILES, which
        # forced exactly 1/3 of EVERY TF's predictions to LOW regardless of real reliability —
        # so an easy call could read "LOW" just for sitting in the bottom third. Now a TF whose
        # direction is genuinely more separable (INTRADAY) earns more HIGHs, and a noisy TF (3D)
        # earns more LOWs — honest and comparable.
        #
        # conf_hi is PER-TF and calibrated so a "HIGH" label means ≥~85% direction accuracy
        # (research/ml_confidence_sweep.py, OOS 25k rows): INTRADAY max-proba reaches 0.99 and
        # conf_hi=0.72 yields ~87% 3-class / ~85% directional-only accuracy at ~46% coverage
        # (0.70→86%/84% cov 51%, 0.75→89%/87% cov 40%). 1D/3D max-proba tops out at ~0.63 and
        # even the most-confident calls only hit ~62-66% — an 85% (or even 75%) HIGH is
        # UNREACHABLE (signal ceiling), so HIGH is disabled for them (conf_hi>1) and they cap
        # at MEDIUM. Every threshold is env-overridable per TF (ML_CONF_HI_INTRADAY, …) for A/B.
        maxp_tr = clf.predict_proba(X_tr_full).max(axis=1)
        baseline = 1.0 / max(1, len(dir_classes))
        _DEFAULT_CONF_HI = {"INTRADAY": 0.72, "1D": 1.01, "3D": 1.01}
        conf_hi = float(os.environ.get(f"ML_CONF_HI_{tf}",
                        os.environ.get("ML_CONF_HI_MARGIN_ABS",
                        _DEFAULT_CONF_HI.get(tf, baseline + 0.20))))
        conf_mid = baseline + float(os.environ.get(f"ML_CONF_MID_{tf}",
                        os.environ.get("ML_CONF_MID_MARGIN", "0.08")))

        manifest["tf"][tf] = {
            "median_train_width": median_band,
            "direction_classes": dir_classes,
            "conf_hi": round(conf_hi, 4),
            "conf_mid": round(conf_mid, 4),
            "conf_scheme": "absolute_vs_baseline_perTF",
            "high_disabled": conf_hi > 1.0,
            "train_maxproba_p33": round(float(np.quantile(maxp_tr, 0.33)), 4),
            "train_maxproba_p66": round(float(np.quantile(maxp_tr, 0.66)), 4),
        }

        # ── Quick holdout calibration (coverage) sanity print ──
        if len(test_df) > 20:
            Xte = test_df[FEATURE_COLUMNS].to_numpy(dtype=float)
            up_true = test_df[_UP_LABEL[tf]].to_numpy(dtype=float)
            dn_true = test_df[_DN_LABEL[tf]].to_numpy(dtype=float)
            pred_up90 = np.maximum(up_q90.predict(Xte), up_q50.predict(Xte))
            pred_dn10 = np.minimum(down_q10.predict(Xte), down_q50.predict(Xte))
            cov_up = float(np.mean(up_true <= pred_up90))     # target ≈ 0.90
            cov_dn = float(np.mean(dn_true >= pred_dn10))     # target ≈ 0.90 (10% below)
            dir_acc = float(np.mean(clf.predict(Xte) == test_df[_DIR_LABEL[tf]].astype(str).to_numpy()))
            print(f"    up_q90 coverage={cov_up:.0%} (~90%) · dn_q10 coverage={cov_dn:.0%} (~90%) "
                  f"· dir_acc={dir_acc:.0%} · median band={median_band:.2f}%")
            manifest["tf"][tf].update({
                "holdout_up_q90_coverage": round(cov_up, 3),
                "holdout_dn_q10_coverage": round(cov_dn, 3),
                "holdout_direction_accuracy": round(dir_acc, 3),
            })

    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    n_est = len(TIMEFRAMES) * 7  # 6 quantile regressors + 1 direction classifier per TF
    print(f"\n  ✓ Wrote {n_est} estimators + manifest.json → {out_dir}")
    print(f"  sklearn={sklearn.__version__} · train_cutoff={manifest['train_cutoff']}")
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=DEFAULT_CSV)
    ap.add_argument("--out", default=MODEL_DIR)
    ap.add_argument("--holdout-months", type=int, default=HOLDOUT_MONTHS)
    args = ap.parse_args()
    train_all(args.csv, args.out, args.holdout_months)


if __name__ == "__main__":
    main()
