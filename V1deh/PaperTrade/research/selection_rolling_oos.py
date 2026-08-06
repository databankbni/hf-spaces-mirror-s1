#!/usr/bin/env python3
"""research/selection_rolling_oos.py — is the ML top-N SELECTION edge robust across MANY
out-of-sample windows, or a one-window fluke?

research/ml_selection_backtest.py --six-filter showed the top-N BULLISH basket beats the market
on ONE 6-month holdout. This rolls the cutoff across several consecutive OOS windows and reports
the basket's edge / Sharpe / win-rate per window, so we can see if the edge is consistent.

For each window: train a self-contained base model (HGB direction classifier + up_q50 quantile
regressor) on all rows BEFORE the window, then on each decision day in the window buy the top-N
BULLISH stocks ranked by up_q50 and measure the equal-weight basket's 3-day net return vs the
equal-weight market.

Research only; reads training_data_extra.csv; never touches the production model.

Usage:
    python research/selection_rolling_oos.py                        # top-5, 6×2-month windows
    python research/selection_rolling_oos.py --top 5 --windows 6 --test-months 2
"""
from __future__ import annotations

import argparse
import math
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

# Delivery feature columns (research-only; the prod feature pipeline does NOT include these —
# the delivery %% experiment was validated NOT robust across rolling windows and not promoted).
DELIVERY_FEATURE_COLS = ["deliv_per", "deliv_z20", "deliv_chg5"]

_CSV = os.path.join(_PROJ_ROOT, "ml_predictor", "training_data_extra.csv")
_CSV_DELIV = os.path.join(_PROJ_ROOT, "ml_predictor", "training_data_delivery.csv")
COST = 0.30
TRADING_DAYS = 252
HOLD = 3


def _sharpe(rets):
    a = np.asarray([x for x in rets if not np.isnan(x)], dtype=float)
    if a.size < 2 or a.std(ddof=1) <= 1e-9:
        return 0.0
    return float(a.mean() / a.std(ddof=1) * np.sqrt(TRADING_DAYS / HOLD))


def _eval_window(base_dir, up50, feats, te, top_n):
    """Per-day top-N basket net return vs market over one OOS window."""
    Xte = te[feats].to_numpy(float)
    te = te.assign(_dir=base_dir.predict(Xte), _up50=up50.predict(Xte),
                   _net=te["ret_3D"].to_numpy(float) - COST)
    basket, market = [], []
    for _, day in te.groupby("date"):
        market.append(float(day["_net"].mean()))
        bull = day[day["_dir"] == "BULLISH"]
        if len(bull) < top_n:
            basket.append(np.nan); continue
        pick = bull.sort_values("_up50", ascending=False).head(top_n)
        basket.append(float(pick["_net"].mean()))
    b = np.array([x for x in basket if not np.isnan(x)])
    m = np.array(market)
    edge = np.array([bb - mk for bb, mk in zip(basket, market) if not np.isnan(bb)])
    return {
        "days": len(b),
        "basket": b.mean() if len(b) else float("nan"),
        "market": m.mean() if len(m) else float("nan"),
        "edge": edge.mean() if len(edge) else float("nan"),
        "sharpe": _sharpe(basket),
        "win_days": float((b > 0).mean()) if len(b) else float("nan"),
    }, basket, market


def run(top_n: int, windows: int, test_months: int, min_train_months: int):
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

    df = pd.read_csv(_CSV)
    df["date"] = pd.to_datetime(df["date"])
    feats = [c for c in FEATURE_COLUMNS if c in df.columns]
    df = df.dropna(subset=feats + ["ret_3D", "up_3D", "dir_3D", "date"]).reset_index(drop=True)
    dmax = df["date"].max()
    dmin = df["date"].min()
    # Build `windows` consecutive test slices ending at dmax, each test_months long.
    edges = [dmax - pd.DateOffset(months=test_months * k) for k in range(windows + 1)][::-1]
    slices = list(zip(edges[:-1], edges[1:]))  # (test_start, test_end)
    print(f"  Data {dmin.date()} → {dmax.date()} · top-{top_n} · {windows}×{test_months}-mo OOS windows · cost {COST}%")

    all_basket, all_market = [], []
    rows = []
    for wi, (ts, tend) in enumerate(slices, 1):
        tr = df[df["date"] < ts]
        te = df[(df["date"] >= ts) & (df["date"] < tend)]
        if (ts - dmin).days < min_train_months * 30 or len(te) < 200:
            print(f"    window {wi} {ts.date()}→{tend.date()}: skipped (train too short / OOS too small)")
            continue
        Xtr = tr[feats].to_numpy(float)
        bd = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.06,
                                            class_weight="balanced", random_state=0)
        bd.fit(Xtr, tr["dir_3D"].to_numpy())
        u5 = HistGradientBoostingRegressor(loss="quantile", quantile=0.5, max_iter=250,
                                           learning_rate=0.06, random_state=0)
        u5.fit(Xtr, tr["up_3D"].to_numpy(float))
        s, basket, market = _eval_window(bd, u5, feats, te, top_n)
        all_basket += basket; all_market += market
        rows.append({"win": wi, "start": ts.date(), "end": tend.date(), **s})
        print(f"    window {wi} {ts.date()}→{tend.date()}: trained on {len(tr):,} rows, {s['days']} decision days")

    print("\n" + "=" * 88)
    print(f"  ROLLING OOS SELECTION EDGE — top-{top_n} BULLISH basket, 3-day hold, net of {COST}%")
    print("=" * 88)
    print(f"  {'Window':<7}{'Period':<24}{'Days':>6}{'Basket%':>9}{'Market%':>9}{'Edge':>8}{'Sharpe':>8}{'WinDay':>8}")
    print("  " + "-" * 78)
    pos = 0
    for r in rows:
        flag = "  ⟵" if r["edge"] > 0 and r["sharpe"] > 0.5 else ""
        if r["edge"] > 0:
            pos += 1
        print(f"  {r['win']:<7}{str(r['start'])+'→'+str(r['end']):<24}{r['days']:>6}"
              f"{r['basket']:>+9.2f}{r['market']:>+9.2f}{r['edge']:>+8.2f}{r['sharpe']:>8.2f}{r['win_days']:>7.0%}{flag}")
    # Pooled across all windows
    ps = _sharpe(all_basket)
    bb = np.array([x for x in all_basket if not np.isnan(x)])
    edge_all = np.array([b - m for b, m in zip(all_basket, all_market) if not np.isnan(b)])
    print("  " + "-" * 78)
    print(f"  {'POOLED':<7}{'all windows':<24}{len(bb):>6}{bb.mean():>+9.2f}"
          f"{'':<9}{edge_all.mean():>+8.2f}{ps:>8.2f}{(bb>0).mean():>7.0%}")
    print(f"\n  Windows with positive edge: {pos}/{len(rows)}  ·  pooled Sharpe {ps:.2f}  ·  "
          f"pooled edge {edge_all.mean():+.2f}%/trade")
    if pos >= math.ceil(0.7 * len(rows)) and ps > 0.5:
        print("  → ROBUST: the selection edge holds across most windows (not a one-window fluke).")
    else:
        print("  → FRAGILE: the edge is inconsistent across windows — treat with caution.")


def run_dual(top_n: int, windows: int, test_months: int, min_train_months: int):
    """Per rolling window, train BASE (current features) AND BASE+DELIVERY, compare the edge/Sharpe
    delta — so we can see if delivery %% helps CONSISTENTLY, not just on one window."""
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

    df = pd.read_csv(_CSV_DELIV)
    df["date"] = pd.to_datetime(df["date"])
    base_feats = [c for c in FEATURE_COLUMNS if c in df.columns and not c.startswith("deliv")]
    deliv_feats = base_feats + [c for c in DELIVERY_FEATURE_COLS if c in df.columns]
    df = df.dropna(subset=base_feats + ["ret_3D", "up_3D", "dir_3D", "date"]).reset_index(drop=True)
    dmax, dmin = df["date"].max(), df["date"].min()
    edges = [dmax - pd.DateOffset(months=test_months * k) for k in range(windows + 1)][::-1]
    slices = list(zip(edges[:-1], edges[1:]))
    print(f"  BASE vs BASE+DELIVERY · top-{top_n} · {windows}×{test_months}-mo OOS windows · "
          f"{len(deliv_feats)-len(base_feats)} delivery feats")

    def _fit(feats, tr):
        bd = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.06,
                                            class_weight="balanced", random_state=0)
        bd.fit(tr[feats].to_numpy(float), tr["dir_3D"].to_numpy())
        u5 = HistGradientBoostingRegressor(loss="quantile", quantile=0.5, max_iter=250,
                                           learning_rate=0.06, random_state=0)
        u5.fit(tr[feats].to_numpy(float), tr["up_3D"].to_numpy(float))
        return bd, u5

    rows = []
    for wi, (ts, tend) in enumerate(slices, 1):
        tr = df[df["date"] < ts]
        te = df[(df["date"] >= ts) & (df["date"] < tend)]
        if (ts - dmin).days < min_train_months * 30 or len(te) < 200:
            continue
        bd0, u0 = _fit(base_feats, tr)
        s0, _, _ = _eval_window(bd0, u0, base_feats, te, top_n)
        bd1, u1 = _fit(deliv_feats, tr)
        s1, _, _ = _eval_window(bd1, u1, deliv_feats, te, top_n)
        rows.append({"win": wi, "start": ts.date(), "end": tend.date(),
                     "e0": s0["edge"], "sh0": s0["sharpe"], "e1": s1["edge"], "sh1": s1["sharpe"]})
        print(f"    window {wi} {ts.date()}→{tend.date()}: trained on {len(tr):,} rows")

    print("\n" + "=" * 90)
    print(f"  ROLLING BASE vs +DELIVERY — top-{top_n} selection edge & Sharpe per OOS window")
    print("=" * 90)
    print(f"  {'Window':<24}{'Base edge':>10}{'+Deliv edge':>12}{'Δedge':>8}"
          f"{'Base Shp':>10}{'+Deliv Shp':>12}{'ΔShp':>8}")
    print("  " + "-" * 84)
    de_pos = sh_pos = 0
    for r in rows:
        de = r["e1"] - r["e0"]; dsh = r["sh1"] - r["sh0"]
        if de > 0: de_pos += 1
        if dsh > 0: sh_pos += 1
        flag = "  ⟵" if (de > 0 and dsh > 0) else ""
        print(f"  {str(r['start'])+'→'+str(r['end']):<24}{r['e0']:>+10.2f}{r['e1']:>+12.2f}{de:>+8.2f}"
              f"{r['sh0']:>10.2f}{r['sh1']:>12.2f}{dsh:>+8.2f}{flag}")
    n = len(rows)
    print("  " + "-" * 84)
    print(f"  Delivery improves EDGE in {de_pos}/{n} windows · improves SHARPE in {sh_pos}/{n} windows")
    if de_pos >= math.ceil(0.7 * n) and sh_pos >= math.ceil(0.7 * n):
        print("  → CONSISTENT: delivery %% helps across most windows — worth promoting to prod.")
    else:
        print("  → INCONSISTENT: delivery %% helps only sometimes — the single-window gain was likely noise.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--windows", type=int, default=6)
    ap.add_argument("--test-months", type=int, default=2)
    ap.add_argument("--min-train-months", type=int, default=12)
    ap.add_argument("--delivery", action="store_true",
                    help="compare BASE vs BASE+DELIVERY per window (needs training_data_delivery.csv)")
    args = ap.parse_args()
    if args.delivery:
        run_dual(args.top, args.windows, args.test_months, args.min_train_months)
    else:
        run(args.top, args.windows, args.test_months, args.min_train_months)


if __name__ == "__main__":
    main()
