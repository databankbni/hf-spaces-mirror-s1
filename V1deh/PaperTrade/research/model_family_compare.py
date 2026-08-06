#!/usr/bin/env python3
"""research/model_family_compare.py — settle "would Random Forest / KNN / a merged-strategy
model beat the current gradient-boosted trees?" with an EMPIRICAL out-of-sample A/B.

Trains several model families on the SAME features + SAME time-split as the production ML
model and compares them on the metric that actually matters for swing trades: OUT-OF-SAMPLE
DIRECTION ACCURACY (predicted dir vs realised excess-of-Nifty dir_1D / dir_3D), plus the
tradeable BULLISH-precision (of the stocks it calls BULLISH, how many actually were).

Model families compared:
  • GBT      — HistGradientBoostingClassifier (what production uses)
  • RandForest — RandomForestClassifier
  • KNN      — KNeighborsClassifier (standardised features)
  • LogReg   — LogisticRegression (linear baseline, standardised)
  • +Strat   — GBT with the S1..S20 strategy trigger flags ADDED (tests "merge strategies")

Also runs a META-LABELING probe: train a 2nd model to predict whether the GBT's own call is
correct, then check if gating to its high-confidence subset raises DirAcc (López de Prado's
meta-labeling — the principled way to "self-learn which contexts are reliable").

Research only; reads training_data_extra.csv; never touches the production model.

Usage:
    python research/model_family_compare.py                 # dir_3D, 6-month OOS
    python research/model_family_compare.py --tf 1D --holdout-months 6
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from ml_predictor.features import FEATURE_COLUMNS  # noqa: E402

_CSV = os.path.join(_PROJ_ROOT, "ml_predictor", "training_data_extra.csv")
_DIRC = {"1D": "dir_1D", "3D": "dir_3D"}
# Strategy trigger flags already present in the feature CSV (the "merge strategies" inputs).
_TRIG_COLS = [f"trigger_T{n}" for n in range(1, 8)]


def _metrics(y_true, y_pred, label=""):
    from sklearn.metrics import accuracy_score, f1_score
    acc = accuracy_score(y_true, y_pred)
    f1 = f1_score(y_true, y_pred, average="macro")
    # BULLISH precision — of everything called BULLISH, how many really were (the tradeable edge)
    bull_mask = y_pred == "BULLISH"
    bull_prec = float((y_true[bull_mask] == "BULLISH").mean()) if bull_mask.sum() else float("nan")
    bull_n = int(bull_mask.sum())
    return {"model": label, "acc": acc, "macro_f1": f1, "bull_prec": bull_prec, "bull_n": bull_n}


def run(tf: str, holdout_months: int):
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline

    df = pd.read_csv(_CSV)
    df["date"] = pd.to_datetime(df["date"])
    target = _DIRC[tf]
    feats = [c for c in FEATURE_COLUMNS if c in df.columns]
    df = df.dropna(subset=feats + [target])
    cutoff = df["date"].max() - pd.DateOffset(months=holdout_months)
    tr = df[df["date"] <= cutoff]
    te = df[df["date"] > cutoff]
    print(f"  TF={tf} · target={target} · features={len(feats)}")
    print(f"  Train ≤ {cutoff.date()}: {len(tr):,} rows · OOS > {cutoff.date()}: {len(te):,} rows")
    print(f"  OOS class balance: " + ", ".join(f"{k} {v:.0%}" for k, v in te[target].value_counts(normalize=True).items()))
    if len(te) < 200:
        raise SystemExit("OOS too small — lower --holdout-months or rebuild the CSV.")

    Xtr, ytr = tr[feats].to_numpy(float), tr[target].to_numpy()
    Xte, yte = te[feats].to_numpy(float), te[target].to_numpy()

    results = []
    # 1) GBT — production family
    gbt = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06, class_weight="balanced", random_state=0)
    gbt.fit(Xtr, ytr)
    results.append(_metrics(yte, gbt.predict(Xte), "GBT (production family)"))
    # 2) Random Forest
    rf = RandomForestClassifier(n_estimators=400, max_depth=12, class_weight="balanced", n_jobs=-1, random_state=0)
    rf.fit(Xtr, ytr)
    results.append(_metrics(yte, rf.predict(Xte), "RandomForest"))
    # 3) KNN (standardised)
    knn = make_pipeline(StandardScaler(), KNeighborsClassifier(n_neighbors=45, weights="distance", n_jobs=-1))
    knn.fit(Xtr, ytr)
    results.append(_metrics(yte, knn.predict(Xte), "KNN (k=45, scaled)"))
    # 4) Logistic Regression (linear baseline)
    lr = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced"))
    lr.fit(Xtr, ytr)
    results.append(_metrics(yte, lr.predict(Xte), "LogReg (linear)"))
    # 5) GBT + explicit strategy trigger flags ("merge strategies")
    trig = [c for c in _TRIG_COLS if c in df.columns]
    if trig:
        feats2 = feats + trig
        gbt2 = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06, class_weight="balanced", random_state=0)
        gbt2.fit(tr[feats2].to_numpy(float), ytr)
        results.append(_metrics(yte, gbt2.predict(te[feats2].to_numpy(float)), f"GBT + {len(trig)} strat flags"))

    # ── Majority-class baseline (what you beat by doing nothing) ──
    maj = pd.Series(ytr).mode()[0]
    results.append(_metrics(yte, np.array([maj] * len(yte)), f"Baseline (always {maj})"))

    print("\n" + "=" * 78)
    print(f"  MODEL-FAMILY A/B — out-of-sample direction accuracy ({target})")
    print("=" * 78)
    print(f"  {'Model':<28}{'DirAcc':>8}{'MacroF1':>9}{'BULLprec':>10}{'BULL_n':>8}")
    print("  " + "-" * 66)
    for r in results:
        bp = f"{r['bull_prec']:.0%}" if r["bull_prec"] == r["bull_prec"] else "—"
        print(f"  {r['model']:<28}{r['acc']:>7.1%}{r['macro_f1']:>9.2f}{bp:>10}{r['bull_n']:>8}")

    # ── META-LABELING probe: can a 2nd model predict when GBT is right? ──
    print("\n" + "=" * 78)
    print("  META-LABELING PROBE — gate to contexts where GBT is predicted reliable")
    print("=" * 78)
    # In-sample cross-fitted 'GBT correct?' labels to avoid leakage: refit GBT on a sub-split.
    from sklearn.model_selection import cross_val_predict
    base = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06, class_weight="balanced", random_state=0)
    tr_pred = cross_val_predict(base, Xtr, ytr, cv=3, method="predict")
    correct = (tr_pred == ytr).astype(int)
    meta = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06, random_state=0)
    meta.fit(Xtr, correct)
    # Base GBT already fit above (gbt). Its OOS calls + meta's P(correct):
    p_correct = meta.predict_proba(Xte)[:, 1]
    base_pred = gbt.predict(Xte)
    base_acc = (base_pred == yte).mean()
    for thr in (0.5, 0.6, 0.7):
        keep = p_correct >= thr
        if keep.sum() < 20:
            print(f"  P(correct)≥{thr:.1f}: too few kept ({int(keep.sum())})")
            continue
        gated_acc = (base_pred[keep] == yte[keep]).mean()
        bull = keep & (base_pred == "BULLISH")
        bull_prec = (yte[bull] == "BULLISH").mean() if bull.sum() else float("nan")
        print(f"  P(correct)≥{thr:.1f}: kept {keep.mean():>4.0%} of rows · DirAcc {gated_acc:.1%} "
              f"(vs {base_acc:.1%} ungated) · BULLprec {bull_prec:.0%} (n={int(bull.sum())})")
    print("\n  Read: if gating to high P(correct) raises DirAcc above ungated, meta-labeling is the")
    print("  real lever — a 2nd model that learns WHICH setups to trust (self-learns from outcomes).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="3D", choices=["1D", "3D"])
    ap.add_argument("--holdout-months", type=int, default=6)
    args = ap.parse_args()
    run(args.tf, args.holdout_months)


if __name__ == "__main__":
    main()
