#!/usr/bin/env python3
"""
backtest_top5.py — Simulate top5 pick selection on historical backtest data.

Applies the _score_5d / _score_1w scoring logic from top5_picker.py to each
(date × timeframe) group in existing CSV datasets, selects the top-N picks,
and measures:
  1. target_hit_for_tf  — same intraday-touch metric as backtest.py
  2. direction accuracy — predicted direction matches actual price movement
  3. avg actual return  — mean ret_for_tf for longs, -ret_for_tf for shorts

Usage:
    python research/backtest_top5.py
"""

import os, sys
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESEARCH_DIR = os.path.dirname(os.path.abspath(__file__))

CONF_MULT    = {"HIGH": 1.0, "MEDIUM": 0.80, "LOW": 0.55}
BEARISH_DIRS = {"BEARISH", "SLIGHTLY BEARISH"}
BULLISH_DIRS = {"BULLISH", "SLIGHTLY BULLISH"}
ACCEPTED     = BULLISH_DIRS | BEARISH_DIRS


def _score(row: pd.Series) -> float:
    """Replicate top5_picker._score_5d using CSV columns."""
    direction = str(row.get("direction", "NEUTRAL"))
    if direction not in ACCEPTED:
        return -1.0  # excluded directions sort to bottom

    is_bearish = direction in BEARISH_DIRS

    # Compute ret_hi / ret_lo from target prices (calibrated range values)
    try:
        ret_hi = ((float(row["target_price_hi"]) / float(row["entry_price"])) - 1) * 100
        ret_lo = ((float(row["target_price_lo"]) / float(row["entry_price"])) - 1) * 100
    except (KeyError, TypeError, ZeroDivisionError):
        return -1.0

    base_ret = abs(ret_lo) if is_bearish else ret_hi
    if base_ret <= 0:
        return -1.0

    conf_mult = CONF_MULT.get(str(row.get("confidence", "LOW")), 0.55)
    ml_prob   = float(row.get("ml_prob", 0.5) or 0.5)

    if is_bearish:
        ml_factor = 1.0 + (0.5 - ml_prob) * 0.30
    else:
        ml_factor = 1.0 + (ml_prob - 0.5) * 0.30

    return base_ret * conf_mult * ml_factor


def _direction_correct(row: pd.Series) -> int:
    """1 if AI direction matches actual price movement over the timeframe."""
    direction   = str(row.get("direction", "NEUTRAL"))
    actual_ret  = float(row.get("ret_for_tf", 0) or 0)
    if direction in BULLISH_DIRS:
        return 1 if actual_ret > 0 else 0
    if direction in BEARISH_DIRS:
        return 1 if actual_ret < 0 else 0
    # NEUTRAL: hit if absolute move is within ±1%
    return 1 if abs(actual_ret) <= 1.0 else 0


def _profit_if_traded(row: pd.Series) -> float:
    """Simulated NET P&L (%) treating each pick as a long or short — after NSE
    round-trip transaction costs. Price prediction ≠ profitable trading: a move
    that doesn't clear fees is not an edge (see Stock-Prediction-Models doc)."""
    direction  = str(row.get("direction", "NEUTRAL"))
    actual_ret = float(row.get("ret_for_tf", 0) or 0)
    gross = -actual_ret if direction in BEARISH_DIRS else actual_ret
    try:
        from costs import cost_pct_for_timeframe
        gross -= cost_pct_for_timeframe(str(row.get("timeframe", "1D")))
    except Exception:
        pass
    return gross


def simulate(df: pd.DataFrame, top_n: int = 5, label: str = "") -> None:
    df = df.copy()
    df["score"]            = df.apply(_score, axis=1)
    df["direction_correct"] = df.apply(_direction_correct, axis=1)
    df["simulated_pnl"]    = df.apply(_profit_if_traded, axis=1)

    selected_rows, excluded_rows = [], []

    for (date, tf), grp in df.groupby(["date", "timeframe"]):
        # Only eligible = BULLISH/BEARISH directions (score > 0).
        # Mirrors top5_picker: NEUTRAL is never added to candidates_all.
        eligible   = grp[grp["score"] > 0].sort_values("score", ascending=False)
        ineligible = grp[grp["score"] <= 0]  # NEUTRAL / no-direction → always excluded
        top = eligible.head(min(top_n, len(eligible)))
        bot = pd.concat([eligible.tail(max(0, len(eligible) - top_n)), ineligible])
        if not top.empty:
            selected_rows.append(top.assign(_sel="selected"))
        if not bot.empty:
            excluded_rows.append(bot.assign(_sel="excluded"))

    sel = pd.concat(selected_rows, ignore_index=True) if selected_rows else pd.DataFrame()
    exc = pd.concat(excluded_rows, ignore_index=True) if excluded_rows else pd.DataFrame()
    all_ = pd.concat([sel, exc], ignore_index=True)

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  Stocks/date: {df.groupby(['date','timeframe'])['ticker'].count().mean():.0f}  "
          f"  Dates: {df['date'].nunique()}  "
          f"  TFs: {df['timeframe'].nunique()}")
    print(f"{'='*60}")
    print(f"  {'Group':12s}  {'N':>5}  {'TargetHit':>9}  {'DirAcc':>7}  {'AvgP&L':>7}")
    print(f"  {'-'*50}")

    for grp_name, grp_df in [("selected", sel), ("excluded", exc), ("all", all_)]:
        if grp_df.empty:
            print(f"  {grp_name:12s}  {'—':>5}")
            continue
        n        = len(grp_df)
        hit      = grp_df["target_hit_for_tf"].mean()
        dir_acc  = grp_df["direction_correct"].mean()
        avg_pnl  = grp_df["simulated_pnl"].mean()
        print(f"  {grp_name:12s}  {n:5d}  {hit:9.1%}  {dir_acc:7.1%}  {avg_pnl:+6.2f}%")

    # Break selected down by direction
    if not sel.empty:
        print("\n  Selected — by direction:")
        for dname, dgrp in sel.groupby("direction"):
            n       = len(dgrp)
            hit     = dgrp["target_hit_for_tf"].mean()
            dir_acc = dgrp["direction_correct"].mean()
            avg_pnl = dgrp["simulated_pnl"].mean()
            print(f"    {dname:18s}  n={n:3d}  hit={hit:.1%}  dir={dir_acc:.1%}  pnl={avg_pnl:+.2f}%")

    # Break selected down by timeframe
    if not sel.empty and sel["timeframe"].nunique() > 1:
        print("\n  Selected — by timeframe:")
        for tf, tfgrp in sel.groupby("timeframe"):
            n       = len(tfgrp)
            hit     = tfgrp["target_hit_for_tf"].mean()
            dir_acc = tfgrp["direction_correct"].mean()
            avg_pnl = tfgrp["simulated_pnl"].mean()
            print(f"    {tf:6s}  n={n:3d}  hit={hit:.1%}  dir={dir_acc:.1%}  pnl={avg_pnl:+.2f}%")


# ── Load datasets ──────────────────────────────────────────────────────────────

DATASETS = [
    ("ai_prompt_accuracy_trades.csv",    "Trades CSV  (6 stocks, 3 dates, 1D/3D/5D)", 5),
    ("ai_prompt_accuracy_sweep.csv",     "Sweep CSV   (6 stocks, ~10 dates, 1D/3D/5D)", 5),
    ("ai_prompt_accuracy_3d.csv",        "3D CSV      (14 stocks, 11 dates, 3D only)", 5),
    ("ai_prompt_accuracy_iter64.csv",    "iter64 CSV  (6 stocks, 46 dates, 1D/3D/5D)", 5),
]

print("Top5 Picker Backtest — Selection Quality Analysis")
print("=" * 60)
print("Metric definitions:")
print("  TargetHit = intraday calibrated-range touch (same as backtest.py)")
print("  DirAcc    = predicted direction matches actual price move")
print("  AvgP&L    = mean simulated return (long for BULLISH, short for BEARISH)")

for fname, desc, top_n in DATASETS:
    path = os.path.join(RESEARCH_DIR, fname)
    if not os.path.exists(path):
        print(f"\n  [skip] {fname} not found")
        continue
    try:
        df = pd.read_csv(path)
        simulate(df, top_n=top_n, label=desc)
    except Exception as e:
        print(f"\n  [error] {fname}: {e}")
