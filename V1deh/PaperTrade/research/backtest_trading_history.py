#!/usr/bin/env python3
"""
research/backtest_trading_history.py — Backtest on actual trading history.

Tests LLM prompt accuracy against the exact tickers and dates you've traded on:
  - Tickers: AXISCADES, DLF, GVT&D, HINDALCO, IPCALAB, POLYCAB, SHRIRAMFIN, STAR
  - Date range: 2026-06-16 to 2026-06-24
  - ~10 closed trades across this period

Run with:
  python research/backtest_trading_history.py
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from research.backtest import run_backtest

# Actual tickers and dates from your paper trading history
TICKERS = [
    "AXISCADES.NS",
    "DLF.NS",
    "GVTD.NS",  # GVT&D.NS → GVTD.NS (normalize ticker format)
    "HINDALCO.NS",
    "IPCALAB.NS",
    "POLYCAB.NS",
    "SHRIRAMFIN.NS",
    "STAR.NS",
]

START_DATE = "2026-06-16"
END_DATE = "2026-06-24"

if __name__ == "__main__":
    print(f"Backtest on actual trading history")
    print(f"Tickers: {', '.join(TICKERS)}")
    print(f"Date range: {START_DATE} to {END_DATE}")
    print(f"Expected rows: ~{len(TICKERS)} * 3 TFs * ~2 weeks = ~{len(TICKERS) * 3 * 2}")
    print()

    # Run backtest
    df = run_backtest(
        tickers=TICKERS,
        start_date=START_DATE,
        end_date=END_DATE,
        ai_forecast_only=True,
        cache_dir=os.path.join(os.path.dirname(__file__), "cache"),
    )

    if df is None or df.empty:
        print("ERROR: Backtest produced no results")
        sys.exit(1)

    # Save to CSV
    output_csv = os.path.join(os.path.dirname(__file__), "ai_prompt_accuracy_trading_history.csv")
    df.to_csv(output_csv, index=False)
    print(f"✓ Backtest complete: {len(df)} predictions")
    print(f"✓ Saved to: {output_csv}\n")

    # Analyze by timeframe
    from collections import defaultdict
    stats = defaultdict(lambda: {"total": 0, "hits": 0})
    for _, row in df.iterrows():
        tf = row.get("timeframe", "N/A")
        target_hit = int(row.get("target_hit_for_tf", 0))
        stats[tf]["total"] += 1
        stats[tf]["hits"] += target_hit

    print("Target Hit Accuracy by Timeframe:")
    print("=" * 50)
    for tf in sorted(stats.keys()):
        total = stats[tf]["total"]
        hits = stats[tf]["hits"]
        pct = (hits / total * 100) if total > 0 else 0
        print(f"{tf}: {hits}/{total} = {pct:.1f}%")

    total_all = sum(s["total"] for s in stats.values())
    hits_all = sum(s["hits"] for s in stats.values())
    overall_pct = (hits_all / total_all * 100) if total_all > 0 else 0
    print("=" * 50)
    print(f"Overall: {hits_all}/{total_all} = {overall_pct:.1f}%")
