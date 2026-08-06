#!/usr/bin/env python3
"""research/meta_label_selection.py — does META-LABELING improve the validated ML SELECTION edge?

Background: research/ml_selection_backtest.py showed the top-N BULLISH basket beats the market
out-of-sample (survives the 6-filter funnel). The model can't call per-stock DIRECTION (coin-flip)
but it RANKS well. This experiment adds a López de Prado META-LABEL: a 2nd model that predicts
whether the base model's BULLISH pick will actually be PROFITABLE (3-day close return > cost), then
uses that P(profit) to GATE / RE-RANK the top-N. Question: does it lift the basket's OOS edge?

Pipeline (self-contained, trains its own base + meta — no model files, fully reproducible):
  1. Chronological split: train ≤ (max_date − holdout), OOS after.
  2. BASE (mirrors production selection): HGB direction classifier (BULLISH filter) + HGB
     quantile-0.5 regressor on up_3D (the ranking signal).
  3. META: on the IS rows the base calls BULLISH, label = (ret_3D − cost > 0). Train HGB
     classifier → P(profit). Uses the SAME features + the strategy trigger flags already present.
  4. OOS: per decision day, from the base-BULLISH candidates build top-N baskets three ways —
       • BASE    : top-N by up_q50 (current production ranking)
       • META    : top-N by P(profit)
       • META-GATE: base ranking but only picks with P(profit) ≥ threshold
     Compare each basket's net edge over the equal-weight market, plus daily Sharpe / win rate.

Research only; reads training_data_extra.csv; NEVER touches the production model.

Usage:
    python research/meta_label_selection.py                       # top-5, 6-mo OOS, 3-day hold
    python research/meta_label_selection.py --top 5 --holdout-months 6 --gate 0.55
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
COST = 0.30            # round-trip cost %
TRADING_DAYS = 252
HOLD = 3               # 3-day close-to-close hold (ret_3D)


def _sharpe(daily_rets):
    a = np.asarray(daily_rets, dtype=float)
    a = a[~np.isnan(a)]
    if a.size < 2 or a.std(ddof=1) <= 1e-9:
        return 0.0
    return float(a.mean() / a.std(ddof=1) * np.sqrt(TRADING_DAYS / HOLD))


def _basket_stats(day_baskets, market_daily):
    """day_baskets: list of per-day basket mean net returns; market_daily: aligned market means."""
    b = np.array([x for x in day_baskets if not np.isnan(x)])
    if not len(b):
        return None
    edge = np.array([db - mk for db, mk in zip(day_baskets, market_daily)
                     if not np.isnan(db) and not np.isnan(mk)])
    return {
        "days": len(b), "mean": b.mean(), "sharpe": _sharpe(day_baskets),
        "edge": edge.mean() if len(edge) else float("nan"),
        "win_days": float((b > 0).mean()),
    }


def run(top_n: int, holdout_months: int, gate: float):
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

    df = pd.read_csv(_CSV)
    df["date"] = pd.to_datetime(df["date"])
    feats = [c for c in FEATURE_COLUMNS if c in df.columns]
    need = feats + ["ret_3D", "up_3D", "dir_3D", "date", "ticker"]
    df = df.dropna(subset=[c for c in need if c in df.columns]).reset_index(drop=True)
    cutoff = df["date"].max() - pd.DateOffset(months=holdout_months)
    tr = df[df["date"] <= cutoff]
    te = df[df["date"] > cutoff].copy()
    print(f"  Train ≤ {cutoff.date()}: {len(tr):,} · OOS: {len(te):,} · top-{top_n} · gate P≥{gate} · cost {COST}%")

    Xtr = tr[feats].to_numpy(float)
    Xte = te[feats].to_numpy(float)

    # ── BASE: direction classifier (BULLISH filter) + up_q50 ranking regressor ──
    base_dir = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06,
                                              class_weight="balanced", random_state=0)
    base_dir.fit(Xtr, tr["dir_3D"].to_numpy())
    up50 = HistGradientBoostingRegressor(loss="quantile", quantile=0.5,
                                         max_iter=300, learning_rate=0.06, random_state=0)
    up50.fit(Xtr, tr["up_3D"].to_numpy(float))

    classes = list(base_dir.classes_)
    bull_i = classes.index("BULLISH") if "BULLISH" in classes else None

    # IS base BULLISH calls → META label = profitable (ret_3D − cost > 0)
    tr_dir = base_dir.predict(Xtr)
    is_bull = tr_dir == "BULLISH"
    y_meta = (tr["ret_3D"].to_numpy(float)[is_bull] - COST > 0).astype(int)
    meta = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06, random_state=0)
    meta.fit(Xtr[is_bull], y_meta)
    print(f"  META trained on {is_bull.sum():,} IS BULLISH picks · base-profit rate {y_meta.mean():.0%}")

    # ── OOS: base predictions + meta P(profit) ──
    te_dir = base_dir.predict(Xte)
    te_up50 = up50.predict(Xte)
    te_pmeta = meta.predict_proba(Xte)[:, 1]
    te = te.assign(_dir=te_dir, _up50=te_up50, _pmeta=te_pmeta,
                   _net=te["ret_3D"].to_numpy(float) - COST)

    base_b, meta_b, gate_b, mkt_b = [], [], [], []
    n_gate_days = 0
    for d, day in te.groupby("date"):
        mkt_b.append(float(day["_net"].mean()))
        bull = day[day["_dir"] == "BULLISH"]
        if len(bull) < top_n:
            base_b.append(np.nan); meta_b.append(np.nan); gate_b.append(np.nan); continue
        base_pick = bull.sort_values("_up50", ascending=False).head(top_n)
        meta_pick = bull.sort_values("_pmeta", ascending=False).head(top_n)
        gated = bull[bull["_pmeta"] >= gate].sort_values("_up50", ascending=False).head(top_n)
        base_b.append(float(base_pick["_net"].mean()))
        meta_b.append(float(meta_pick["_net"].mean()))
        if len(gated) >= 1:
            gate_b.append(float(gated["_net"].mean())); n_gate_days += 1
        else:
            gate_b.append(np.nan)

    print("\n" + "=" * 82)
    print(f"  META-LABELING vs BASE SELECTION — OOS top-{top_n} basket, 3-day hold, net of {COST}%")
    print("=" * 82)
    print(f"  {'Strategy':<24}{'Days':>6}{'AvgNet%':>9}{'EdgeVsMkt':>11}{'Sharpe':>8}{'WinDays':>9}")
    print("  " + "-" * 68)
    for label, series in [("BASE (rank up_q50)", base_b),
                          ("META (rank P-profit)", meta_b),
                          (f"META-GATE (P≥{gate})", gate_b)]:
        s = _basket_stats(series, mkt_b)
        if s:
            print(f"  {label:<24}{s['days']:>6}{s['mean']:>+9.2f}{s['edge']:>+11.2f}"
                  f"{s['sharpe']:>8.2f}{s['win_days']:>8.0%}")
    mk = np.array([x for x in mkt_b if not np.isnan(x)])
    print(f"  {'MARKET (equal-weight)':<24}{len(mk):>6}{mk.mean():>+9.2f}{0.0:>+11.2f}{_sharpe(mkt_b):>8.2f}{'—':>9}")

    print("\n  Read: if META or META-GATE beats BASE on Sharpe/Edge, the meta-model adds value")
    print("  (self-learns which picks to trust). If not, base ranking already captures the edge.")
    print("  This is the prod-safe test BEFORE wiring any gating into the live selector.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--holdout-months", type=int, default=6)
    ap.add_argument("--gate", type=float, default=0.55, help="P(profit) threshold for META-GATE")
    args = ap.parse_args()
    run(args.top, args.holdout_months, args.gate)


if __name__ == "__main__":
    main()
