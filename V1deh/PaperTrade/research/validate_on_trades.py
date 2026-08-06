#!/usr/bin/env python3
"""
research/validate_on_trades.py — Validate LLM prompts on actual paper trade dates.

Two modes:
  default            — 7 specific trade entry dates (fast, ~21 LLM calls)
  --sweep            — every trading day in the 2-week window (full, ~210 calls)

Run:
    python research/validate_on_trades.py           # entry-dates mode
    python research/validate_on_trades.py --sweep   # 2-week sweep
"""
from __future__ import annotations
import sys, os, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))   # import backtest directly

import warnings
import pandas as pd

warnings.filterwarnings("ignore")

from backtest import (
    fetch_data, _compute_indicators, _fwd_intraday_moves, _fwd_returns,
    _vix_nifty_series, _simple_ml_prob, run_backtest, print_results, TIMEFRAMES,
)

# ── TRADED TICKERS ─────────────────────────────────────────────────────────────
# GVT&D.NS not found in Yahoo Finance — skipped.
TRADED_TICKERS = [
    "HINDALCO.NS",
    "IPCALAB.NS",
    "POLYCAB.NS",
    "DLF.NS",
    "SHRIRAMFIN.NS",
    "AXISCADES.NS",
]

# Actual trade outcomes (for cross-reference table)
TRADE_OUTCOMES = {
    "HINDALCO.NS":   {"entry": "2026-06-16", "actual_pnl": +2.16},
    "IPCALAB.NS":    {"entry": "2026-06-16", "actual_pnl": +3.10},
    "POLYCAB.NS":    {"entry": "2026-06-21", "actual_pnl": -2.97},
    "DLF.NS":        {"entry": "2026-06-21", "actual_pnl": +1.21},
    "SHRIRAMFIN.NS": {"entry": "2026-06-21", "actual_pnl": +1.47},
    "AXISCADES.NS":  {"entry": "2026-06-22", "actual_pnl": -5.80},
}

# 2-week sweep window (last 2 weeks of trading as of 2026-06-29)
SWEEP_START = "2026-06-16"
SWEEP_END   = "2026-06-27"   # last Friday close available

# Need ≥200 trading days before sweep start for EMA200
DATA_START  = "2025-01-01"
DATA_END    = "2026-07-01"


def _snap_to_trading_day(c_series: pd.Series, ts: pd.Timestamp):
    prior = c_series.index[c_series.index <= ts]
    return prior[-1] if not prior.empty else None


def _build_work_items(tickers, dates, sc, sh, sl, sv, nc, vc, nifty_ema200, vix_slope):
    """Build run_backtest work items for every (ticker, date) pair."""
    company_names = {t: t.replace(".NS", "") for t in tickers}
    work_items = []
    skipped = 0

    for date in dates:
        for ticker in tickers:
            if ticker not in sc.columns:
                continue

            snapped = _snap_to_trading_day(sc[ticker].dropna(), date)
            if snapped is None or snapped != date:
                # Only use exact trading days (avoid double-counting weekend snaps)
                continue

            try:
                vix_level = float(vc.loc[:date].dropna().iloc[-1])
                nifty_v   = float(nc.loc[:date].dropna().iloc[-1])
                nifty_ema = float(nifty_ema200.loc[:date].dropna().iloc[-1])
                nifty_ok  = nifty_v > nifty_ema
                vix_decl  = float(vix_slope.loc[:date].dropna().iloc[-1]) < 0
                macro_ok  = nifty_ok and vix_level < 20
            except Exception:
                skipped += 1
                continue

            r1, r3, r5 = _fwd_returns(sc, date, ticker)
            up0, dn0, up1, dn1, up3, dn3, up5, dn5 = _fwd_intraday_moves(sc, sh, sl, date, ticker)

            price   = float(sc[ticker].dropna().loc[:date].iloc[-1])
            inds    = _compute_indicators(sc[ticker], sh[ticker], sl[ticker], sv[ticker], date)
            ml_prob = _simple_ml_prob(sc[ticker], sv[ticker], date)

            idx = sc[ticker].dropna().index.searchsorted(date, side="right")
            try:
                # 252-bar window matches production (predictor_core passes .tail(252)). A short
                # 20-bar window forced _volatility_percentile/_realized_move_anchor to flat defaults.
                ohlcv = pd.DataFrame({
                    "High":   sh[ticker].iloc[max(0, idx - 252):idx].values,
                    "Low":    sl[ticker].iloc[max(0, idx - 252):idx].values,
                    "Close":  sc[ticker].iloc[max(0, idx - 252):idx].values,
                    "Volume": sv[ticker].iloc[max(0, idx - 252):idx].values,
                }).dropna()
            except Exception:
                ohlcv = None

            for tf in TIMEFRAMES:
                # INTRADAY uses the same-day swing (up0/dn0); its close-to-close ret is ~0.
                ret_for_tf = {"INTRADAY": 0.0, "1D": r1, "3D": r3, "5D": r5}[tf]
                if pd.isna(ret_for_tf):
                    continue  # forward data not yet available
                if tf != "INTRADAY" and pd.isna({"1D": r1, "3D": r3, "5D": r5}[tf]):
                    continue
                work_items.append(dict(
                    date=date, ticker=ticker, tf=tf,
                    price=price, ml_prob=ml_prob, inds=inds,
                    company=company_names[ticker], ohlcv=ohlcv,
                    nifty_ok=nifty_ok, macro_ok=macro_ok,
                    vix_level=vix_level, vix_decl=vix_decl,
                    r1=r1, r3=r3, r5=r5,
                    up0=up0, dn0=dn0,
                    up1=up1, dn1=dn1, up3=up3, dn3=dn3, up5=up5, dn5=dn5,
                ))

    if skipped:
        print(f"  ({skipped} (ticker, date) pairs skipped — missing macro data)")
    return work_items


def _print_summary(df):
    print("\n" + "=" * 70)
    print("Accuracy by Timeframe")
    print("=" * 70)
    for tf in TIMEFRAMES:
        sub = df[df["timeframe"] == tf]
        if sub.empty:
            continue
        n        = len(sub)
        tgt_hits = int(sub["target_hit_for_tf"].sum())
        dir_hits = int(sub["intraday_hit_for_tf"].sum())
        print(f"  {tf}: {tgt_hits}/{n}  target_hit={tgt_hits/n*100:.0f}%  "
              f"direction={dir_hits/n*100:.0f}%")

    total     = len(df)
    tgt_total = int(df["target_hit_for_tf"].sum())
    dir_total = int(df["intraday_hit_for_tf"].sum())
    print(f"\n  Overall: {tgt_total}/{total} = {tgt_total/total*100:.0f}% target_hit  "
          f"|  {dir_total}/{total} = {dir_total/total*100:.0f}% direction")

    # Breakdown by ticker
    print("\n" + "=" * 70)
    print("Accuracy by Ticker")
    print("=" * 70)
    print(f"  {'Ticker':<18} {'N':>4} {'Target%':>8} {'Dir%':>8} {'Actual P&L':>12}")
    print("  " + "-" * 54)
    for t in TRADED_TICKERS:
        sub = df[df["ticker"] == t]
        if sub.empty:
            continue
        n        = len(sub)
        tgt_hits = int(sub["target_hit_for_tf"].sum())
        dir_hits = int(sub["intraday_hit_for_tf"].sum())
        outcome  = TRADE_OUTCOMES.get(t, {})
        pnl_str  = f"{outcome['actual_pnl']:+.1f}%" if "actual_pnl" in outcome else "—"
        print(f"  {t:<18} {n:>4} {tgt_hits/n*100:>7.0f}% {dir_hits/n*100:>7.0f}% {pnl_str:>12}")

    # Direction distribution
    print("\n" + "=" * 70)
    print("Direction Distribution")
    print("=" * 70)
    dist = df.groupby(["timeframe", "direction"]).size().unstack(fill_value=0)
    print(dist.to_string())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sweep", action="store_true",
                        help="Test every trading day in the 2-week window (slow, ~210 calls)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Cap the number of work items (quick sanity check of the pipeline)")
    args = parser.parse_args()

    mode = "sweep" if args.sweep else "entry-dates"

    print("=" * 70)
    print(f"Validate LLM Prompts — {'Last 2-Week Sweep' if args.sweep else 'Trade Entry Dates'}")
    print("=" * 70)
    print(f"Tickers : {', '.join(TRADED_TICKERS)}")

    # 1. Download OHLCV
    sc, sh, sl, sv, nc, vc = fetch_data(TRADED_TICKERS, DATA_START, DATA_END)
    nifty_ema200, vix_slope = _vix_nifty_series(nc, vc)

    # 2. Choose dates
    if args.sweep:
        # Every actual NSE trading day in the 2-week window
        all_nifty_days = nc.dropna().index
        dates = all_nifty_days[
            (all_nifty_days >= pd.Timestamp(SWEEP_START)) &
            (all_nifty_days <= pd.Timestamp(SWEEP_END))
        ]
        print(f"Window  : {SWEEP_START} → {SWEEP_END}  ({len(dates)} trading days)")
        n_max = len(dates) * len(TRADED_TICKERS) * len(TIMEFRAMES)
        print(f"Items   : up to {n_max} LLM calls (~{n_max * 6 // 60} min at 6s/call)")
    else:
        # Only the specific entry dates from our actual trades
        raw_dates = sorted({pd.Timestamp(v["entry"]) for v in TRADE_OUTCOMES.values()})
        dates = []
        for ts in raw_dates:
            snapped = _snap_to_trading_day(nc.dropna(), ts)
            if snapped is not None:
                dates.append(snapped)
        dates = list(dict.fromkeys(dates))  # deduplicate, preserve order
        n_max = len(dates) * len(TRADED_TICKERS) * len(TIMEFRAMES)
        print(f"Dates   : {[str(d.date()) for d in dates]}")
        print(f"Items   : up to {n_max} LLM calls (~{n_max * 6 // 60} min at 6s/call)")

    print()

    # 3. Build work items
    work_items = _build_work_items(
        TRADED_TICKERS, dates, sc, sh, sl, sv, nc, vc, nifty_ema200, vix_slope
    )
    print(f"{len(work_items)} work items queued\n")

    if not work_items:
        print("ERROR: No valid work items.")
        sys.exit(1)

    # 4. Run backtest — prod_like=True mirrors the live /api/watchlist-picks path
    #    (fast_mode single synthesis call, AI-owned ranges, fast_fail=False so calls wait on
    #     rate limits, retry, and fall through to Ollama exactly as the app does).
    suffix = "sweep" if args.sweep else "trades"
    csv_out = os.path.join(os.path.dirname(__file__), f"ai_prompt_accuracy_{suffix}.csv")
    df = run_backtest(work_items, csv_path=csv_out, prod_like=True,
                      limit_work_items=args.limit)

    if df is None or df.empty:
        print("ERROR: run_backtest returned no results.")
        sys.exit(1)

    _print_summary(df)
    print(f"\nSaved → {csv_out}")

    # Full breakdown — Tables 1-5 (trigger accuracy, per-regime slice, etc.)
    print("\n" + "=" * 70)
    print("FULL BREAKDOWN (shared with backtest.py output)")
    print_results(df)


if __name__ == "__main__":
    main()
