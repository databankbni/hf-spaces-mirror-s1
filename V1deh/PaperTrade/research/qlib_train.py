#!/usr/bin/env python3
"""
research/qlib_train.py — Train LightGBM alpha model on NSE data.

Replaces ml_combiner.py's LogisticRegression/XGBoost with LightGBM, using the
same build_feature_matrix() feature pipeline and a 13-fold walk-forward split
that mirrors the existing ml_combiner.py structure.

Note: pyqlib is not available for Python 3.13; this script uses LightGBM
directly on the pandas feature matrix produced by ml_combiner.build_feature_matrix().
The saved model (research/models/lgbm_model.pkl) is loaded at inference time by
qlib_predictor.py, which slots into predictor_core.get_ml_feature_score().

Usage (one-time, run from project root):
    python research/qlib_train.py

Output:
    research/models/lgbm_model.pkl   ← trained model + metadata
"""

from __future__ import annotations
import sys
import os
import pickle
import warnings
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import accuracy_score

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING)

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
MODEL_DIR  = PROJECT_ROOT / "research" / "models"
MODEL_PATH = MODEL_DIR / "lgbm_model.pkl"

# ── Training config ───────────────────────────────────────────────────────────
TRAIN_START = "2019-01-01"
TRAIN_END   = "2024-01-01"
HORIZON_DAYS = 3        # 3D forward return is best-performing per backtest findings
N_FOLDS      = 13
FOLD_MONTHS  = 6        # each fold covers 6 months of OOS test data
PROB_THRESHOLD = 0.60   # mirrors ml_combiner.PROB_THRESHOLD

# LightGBM hyperparameters
LGB_PARAMS = {
    "objective":        "binary",
    "metric":           "binary_logloss",
    "n_estimators":     500,
    "learning_rate":    0.05,
    "max_depth":        6,
    "num_leaves":       63,
    "subsample":        0.8,
    "colsample_bytree": 0.8,
    "min_child_samples": 100,
    "reg_alpha":        0.1,
    "reg_lambda":       0.1,
    "class_weight":     "balanced",
    "random_state":     42,
    "verbose":          -1,
    "n_jobs":           -1,
}

FEAT_COLS_EXCLUDE = {"date", "ticker", "label", "fwd_ret", "nifty_fwd"}


def generate_wf_splits(n_folds: int = N_FOLDS, fold_months: int = FOLD_MONTHS) -> list[dict]:
    """Expanding-window walk-forward splits (mirrors ml_combiner.py logic)."""
    splits = []
    test_end = pd.Timestamp(TRAIN_END)
    for fold in range(n_folds, 0, -1):
        t_end   = test_end - pd.DateOffset(months=fold_months * (fold - 1))
        t_start = t_end - pd.DateOffset(months=fold_months)
        if t_start <= pd.Timestamp(TRAIN_START):
            continue
        splits.append({
            "fold":        n_folds - fold + 1,
            "train_start": pd.Timestamp(TRAIN_START),
            "train_end":   t_start,
            "test_start":  t_start,
            "test_end":    t_end,
        })
    return splits


def train_lgbm_fold(X_tr, y_tr, X_te, y_te) -> tuple[lgb.LGBMClassifier, np.ndarray]:
    """Train one LightGBM fold, return (model, test_probabilities)."""
    model = lgb.LGBMClassifier(**LGB_PARAMS)
    model.fit(
        X_tr, y_tr,
        eval_set=[(X_te, y_te)],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(period=-1)],
    )
    probs = model.predict_proba(X_te)[:, 1]
    return model, probs


def evaluate_fold(probs: np.ndarray, labels: np.ndarray, fold: int,
                  test_start: pd.Timestamp, test_end: pd.Timestamp) -> dict:
    oos_acc    = accuracy_score(labels, (probs >= 0.5).astype(int)) * 100
    sig_mask   = probs >= PROB_THRESHOLD
    n_sigs     = int(sig_mask.sum())
    sig_acc    = float((labels[sig_mask] == 1).mean() * 100) if n_sigs > 0 else float("nan")
    return {
        "fold":       fold,
        "test_start": test_start.strftime("%Y-%m"),
        "test_end":   test_end.strftime("%Y-%m"),
        "oos_acc":    round(oos_acc, 1),
        "n_signals":  n_sigs,
        "signal_acc": round(sig_acc, 1) if not np.isnan(sig_acc) else None,
        "n_test":     len(labels),
    }


def print_fold_table(fold_stats: list[dict]) -> None:
    header = f"{'Fold':>4}  {'Period':>16}  {'OOS Acc':>8}  {'N Signals':>10}  {'Signal Acc':>11}  {'N Test':>7}"
    print(f"\n{'─'*68}")
    print(f"  {header}")
    print(f"  {'─'*64}")
    for fs in fold_stats:
        oos_s = f"{fs['oos_acc']:.1f}%" if fs["oos_acc"] is not None else "   N/A"
        sig_s = f"{fs['signal_acc']:.1f}%" if fs["signal_acc"] is not None else "   N/A"
        print(f"  {fs['fold']:>4}  "
              f"{fs['test_start']:>7}–{fs['test_end']:<7}  "
              f"{oos_s:>8}  {fs['n_signals']:>10}  {sig_s:>11}  {fs['n_test']:>7}")


def main() -> None:
    print("=" * 68)
    print("  QLIB TRAIN — LightGBM Alpha Model for NSE")
    print(f"  Period: {TRAIN_START} → {TRAIN_END}  |  Horizon: {HORIZON_DAYS}D")
    print(f"  Run: {datetime.now().strftime('%d %b %Y %H:%M')}")
    print("=" * 68)

    # ── Step 1: Load data ────────────────────────────────────────────────────
    print("\n  Loading NSE market data (yfinance, ~150 tickers × 5 years)...")
    from trial_run import load_data
    sc, sh, sl, sv, nifty_c, vix_c = load_data()
    print(f"  Tickers: {sc.shape[1]}  |  Dates: {len(sc)}")

    # ── Step 2: Build macro features ─────────────────────────────────────────
    mc_obj = None
    try:
        from macro_context import MacroContext
        mc_obj = MacroContext()
        mc_obj.load(TRAIN_START, TRAIN_END)
        print(f"  Macro context: {mc_obj.summary()}")
    except Exception as e:
        print(f"  Macro context skipped ({e}); macro features will be zero-filled")

    from ml_combiner import build_feature_matrix, _build_macro_feat
    macro_feat = _build_macro_feat(vix_c, mc_obj)

    # ── Step 3: Build feature matrix ─────────────────────────────────────────
    print(f"\n  Building feature matrix ({HORIZON_DAYS}D horizon)...")
    feat_matrix = build_feature_matrix(
        sc, sh, sl, sv, nifty_c, vix_c, macro_feat, HORIZON_DAYS
    )
    feat_cols = [c for c in feat_matrix.columns if c not in FEAT_COLS_EXCLUDE]
    print(f"  Rows: {len(feat_matrix):,}  |  Features: {len(feat_cols)}")
    print(f"  Up-day base rate: {feat_matrix['label'].mean()*100:.1f}%")
    print(f"  Feature columns: {feat_cols}")

    # ── Step 4: Walk-forward evaluation ──────────────────────────────────────
    splits = generate_wf_splits()
    print(f"\n  Walk-forward splits: {len(splits)}")

    fold_stats  = []
    all_probs   = []
    all_labels  = []
    fold_models = []

    for sp in splits:
        train_mask = (feat_matrix["date"] >= sp["train_start"]) & \
                     (feat_matrix["date"] <  sp["train_end"])
        test_mask  = (feat_matrix["date"] >= sp["test_start"]) & \
                     (feat_matrix["date"] <  sp["test_end"])

        tr = feat_matrix[train_mask].dropna(subset=feat_cols)
        te = feat_matrix[test_mask].dropna(subset=feat_cols)

        if len(tr) < 500 or len(te) < 10:
            fold_stats.append({
                "fold": sp["fold"], "test_start": sp["test_start"].strftime("%Y-%m"),
                "test_end": sp["test_end"].strftime("%Y-%m"),
                "oos_acc": None, "n_signals": 0, "signal_acc": None, "n_test": len(te),
            })
            continue

        X_tr, y_tr = tr[feat_cols].values, tr["label"].values
        X_te, y_te = te[feat_cols].values, te["label"].values

        model, probs = train_lgbm_fold(X_tr, y_tr, X_te, y_te)
        fold_stats.append(evaluate_fold(probs, y_te, sp["fold"], sp["test_start"], sp["test_end"]))
        all_probs.extend(probs.tolist())
        all_labels.extend(y_te.tolist())
        fold_models.append(model)
        print(f"  Fold {sp['fold']:>2}  {sp['test_start'].strftime('%Y-%m')}–{sp['test_end'].strftime('%Y-%m')}  "
              f"OOS={fold_stats[-1]['oos_acc']}%  signals={fold_stats[-1]['n_signals']}  "
              f"sig_acc={fold_stats[-1]['signal_acc']}%", flush=True)

    print_fold_table(fold_stats)

    # ── Step 5: Overall OOS stats ─────────────────────────────────────────────
    if all_probs:
        p = np.array(all_probs)
        y = np.array(all_labels)
        overall_oos = accuracy_score(y, (p >= 0.5).astype(int)) * 100
        sig_mask    = p >= PROB_THRESHOLD
        n_sigs      = sig_mask.sum()
        sig_acc     = (y[sig_mask] == 1).mean() * 100 if n_sigs > 0 else float("nan")
        print(f"\n{'═'*68}")
        print(f"  OVERALL OOS  |  LightGBM  |  Threshold={PROB_THRESHOLD}")
        print(f"{'─'*68}")
        print(f"  OOS accuracy (all):      {overall_oos:.1f}%")
        print(f"  High-conf signals:       {n_sigs}")
        print(f"  Signal accuracy:         {sig_acc:.1f}%")
        print(f"{'═'*68}")

    # ── Step 6: Train final model on full 2019-2022, validate 2023 ────────────
    print("\n  Training final model (2019-2022 train / 2023 validate)...")
    final_train_mask = (feat_matrix["date"] >= TRAIN_START) & \
                       (feat_matrix["date"] <  "2023-01-01")
    final_val_mask   = (feat_matrix["date"] >= "2023-01-01") & \
                       (feat_matrix["date"] <  TRAIN_END)

    tr_f = feat_matrix[final_train_mask].dropna(subset=feat_cols)
    te_f = feat_matrix[final_val_mask].dropna(subset=feat_cols)

    X_tr_f, y_tr_f = tr_f[feat_cols].values, tr_f["label"].values
    X_te_f, y_te_f = te_f[feat_cols].values, te_f["label"].values

    final_model = lgb.LGBMClassifier(**LGB_PARAMS)
    final_model.fit(
        X_tr_f, y_tr_f,
        eval_set=[(X_te_f, y_te_f)],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(period=-1)],
    )
    val_probs = final_model.predict_proba(X_te_f)[:, 1]
    val_acc   = accuracy_score(y_te_f, (val_probs >= 0.5).astype(int)) * 100
    val_sigs  = (val_probs >= PROB_THRESHOLD).sum()
    val_sig_acc = (y_te_f[val_probs >= PROB_THRESHOLD] == 1).mean() * 100 if val_sigs > 0 else float("nan")
    print(f"  Final model — 2023 validation:  OOS={val_acc:.1f}%  signals={val_sigs}  sig_acc={val_sig_acc:.1f}%")

    # Feature importance (top 10)
    importances = pd.Series(
        final_model.feature_importances_, index=feat_cols
    ).sort_values(ascending=False)
    print("\n  Top-10 feature importances:")
    for feat, imp in importances.head(10).items():
        print(f"    {feat:<20} {imp:>6.0f}")

    # ── Step 7: Save model ────────────────────────────────────────────────────
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "model":         final_model,
        "feature_names": feat_cols,
        "horizon_days":  HORIZON_DAYS,
        "trained_at":    datetime.now().isoformat(),
        "train_period":  f"{TRAIN_START} → 2022-12-31",
        "val_acc":       round(val_acc, 1),
        "val_signal_acc": round(val_sig_acc, 1) if not np.isnan(val_sig_acc) else None,
        "prob_threshold": PROB_THRESHOLD,
    }
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)

    print(f"\n  Model saved → {MODEL_PATH}")
    print(f"  Size: {MODEL_PATH.stat().st_size / 1024:.0f} KB")
    print("=" * 68)


if __name__ == "__main__":
    main()
