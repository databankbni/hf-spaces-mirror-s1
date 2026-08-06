#!/usr/bin/env python3
"""
research/new_features_backtest.py — Backtest impact of feature modules.

Tests 2 hypotheses against historical NSE data (2024-01-01 to 2025-06-01):
  H1 — Fundamentals filter: Do fundamental_score >= 60 trades outperform baseline?
  H2 — Sector rotation: Do trades in 'leading_sectors' beat trades in 'lagging_sectors'?

Method:
  - Fetch OHLCV + indicators for each stock at each test date
  - Compute 3D and 5D forward returns (close-to-close)
  - Classify each date with fundamentals score and sector position
  - Compare win rates and avg returns across filtered vs unfiltered populations
  - Output: plain text table (no LLM calls — this is a pure signal test)

Usage:
    cd /Users/videkhanna/Documents/Projects/PaperTrade
    python research/new_features_backtest.py
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import warnings
warnings.filterwarnings("ignore")

import math
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

# ── CONFIG ─────────────────────────────────────────────────────────────────────
UNIVERSE = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS",
    "BAJFINANCE.NS", "SUNPHARMA.NS", "WIPRO.NS",
]
START = "2023-07-01"  # pull data from mid-2023 to cover 2024 test dates
END   = "2025-06-01"
TEST_START = "2024-01-01"
TEST_END   = "2025-06-01"
STEP  = 40  # every 40 trading days


# ── DATA LOADING ───────────────────────────────────────────────────────────────

def load_prices(tickers: list[str]) -> dict[str, pd.Series]:
    print(f"  Downloading OHLCV for {len(tickers)} stocks ({START} → {END})...")
    all_prices: dict[str, pd.Series] = {}
    for tk in tickers:
        try:
            df = yf.download(tk, start=START, end=END, progress=False, auto_adjust=True)
            if df.empty:
                print(f"    [skip] {tk}: no data")
                continue
            close = df["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            all_prices[tk] = close.dropna()
            print(f"    {tk}: {len(all_prices[tk])} bars")
        except Exception as e:
            print(f"    [error] {tk}: {e}")
    return all_prices


def get_test_dates(close: pd.Series) -> list[pd.Timestamp]:
    """Sample every STEP-th bar between TEST_START and TEST_END."""
    idx = close.loc[TEST_START:TEST_END].index
    return list(idx[::STEP])


def forward_return(close: pd.Series, date: pd.Timestamp, n_days: int) -> Optional[float]:
    """Close-to-close return n_days forward from date."""
    try:
        future_idx = close.index[close.index > date]
        if len(future_idx) < n_days:
            return None
        future_close = float(close.loc[future_idx[n_days - 1]])
        current_close = float(close.loc[date])
        return (future_close / current_close - 1) * 100
    except Exception:
        return None


# ── FEATURE: FUNDAMENTALS SCORE ────────────────────────────────────────────────

def batch_fundamentals(tickers: list[str]) -> dict[str, dict]:
    """Fetch fundamentals once per ticker (cached by fundamentals.py)."""
    print("  Fetching fundamentals for each ticker...")
    from fundamentals import get_fundamentals
    results = {}
    for tk in tickers:
        try:
            f = get_fundamentals(tk)
            results[tk] = f
            score = f.get("fundamental_score", "?")
            pe_lbl = f.get("pe_relative", "?")
            print(f"    {tk}: score={score}/100  PE={pe_lbl}")
        except Exception as e:
            print(f"    [warn] {tk}: {e}")
            results[tk] = {"fundamental_score": 50}
    return results


# ── FEATURE: SECTOR PULSE ──────────────────────────────────────────────────────

def get_sector_pulse_at(date: pd.Timestamp, sector_data: dict[str, pd.Series]) -> dict:
    """
    Build a simplified 'leading/lagging' classification at a historical date.
    Uses pre-fetched sector index price series.
    """
    leading, lagging = [], []
    results = []
    for name, series in sector_data.items():
        try:
            past = series.loc[:date].dropna()
            if len(past) < 6:
                continue
            latest = float(past.iloc[-1])
            p5 = float(past.iloc[-6]) if len(past) >= 6 else latest
            chg_5d = (latest / p5 - 1) * 100 if p5 > 0 else 0
            results.append((name, chg_5d))
        except Exception:
            continue
    if results:
        results.sort(key=lambda x: x[1], reverse=True)
        leading  = [r[0] for r in results[:3]]
        lagging  = [r[0] for r in results[-3:]]
    return {"leading_sectors": leading, "lagging_sectors": lagging}


def load_sector_series() -> dict[str, pd.Series]:
    """Pre-fetch NSE sector index prices for historical backtesting."""
    from sector_pulse import _SECTORS
    print("  Downloading NSE sector indices for backtesting...")
    out = {}
    for s in _SECTORS:
        try:
            df = yf.download(s["ticker"], start=START, end=END, progress=False, auto_adjust=True)
            if df.empty:
                continue
            close = df["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            out[s["name"]] = close.dropna()
            print(f"    {s['name']} ({s['ticker']}): {len(out[s['name']])} bars")
        except Exception as e:
            print(f"    [skip] {s['name']}: {e}")
    return out


def get_ticker_sector(ticker: str) -> Optional[str]:
    from sector_pulse import get_sector_for_ticker
    return get_sector_for_ticker(ticker)


# ── ANALYSIS ──────────────────────────────────────────────────────────────────

def _stats(returns: list[float]) -> dict:
    if not returns:
        return {"n": 0, "win_rate": 0, "avg_ret": 0, "avg_win": 0, "avg_loss": 0}
    wins  = [r for r in returns if r > 0]
    losses= [r for r in returns if r <= 0]
    return {
        "n":        len(returns),
        "win_rate": round(len(wins) / len(returns) * 100, 1),
        "avg_ret":  round(sum(returns) / len(returns), 2),
        "avg_win":  round(sum(wins) / len(wins), 2) if wins else 0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
    }


def _print_comparison(label_a: str, a: dict, label_b: str, b: dict, tf: str) -> None:
    print(f"\n  [{tf}] {label_a:35s}  n={a['n']:>3}  win={a['win_rate']:>5.1f}%  avg={a['avg_ret']:>+5.2f}%")
    print(f"  [{tf}] {label_b:35s}  n={b['n']:>3}  win={b['win_rate']:>5.1f}%  avg={b['avg_ret']:>+5.2f}%")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def run_backtest():
    print("\n" + "═" * 70)
    print("  NEW FEATURES BACKTEST — PaperTrade")
    print(f"  Universe: {', '.join(UNIVERSE)}")
    print(f"  Dates: {TEST_START} → {TEST_END}, step={STEP} bars")
    print("═" * 70)

    # 1. Load price data
    prices = load_prices(UNIVERSE)
    if not prices:
        print("[error] No price data loaded — check internet connection")
        return

    # 2. Fundamentals (fetched once — time-stable)
    fund = batch_fundamentals(UNIVERSE)

    # 3. Sector series for historical pulse
    sector_series = load_sector_series()

    # 4. Build observation matrix
    records = []
    for tk, close in prices.items():
        dates = get_test_dates(close)
        tk_sector = get_ticker_sector(tk)
        f = fund.get(tk, {})
        fund_score = f.get("fundamental_score", 50)

        for date in dates:
            r3 = forward_return(close, date, 3)
            r5 = forward_return(close, date, 5)
            if r3 is None and r5 is None:
                continue

            sector_ctx = get_sector_pulse_at(date, sector_series) if sector_series else {}
            leading  = sector_ctx.get("leading_sectors", [])
            lagging  = sector_ctx.get("lagging_sectors", [])
            is_leading = tk_sector in leading if tk_sector else None
            is_lagging = tk_sector in lagging if tk_sector else None

            records.append({
                "ticker":     tk,
                "date":       date,
                "ret_3d":     r3,
                "ret_5d":     r5,
                "fund_score": fund_score,
                "is_leading": is_leading,
                "is_lagging": is_lagging,
            })

    if not records:
        print("[error] No observation records built — check data")
        return

    print(f"\n  Built {len(records)} observations across {len(prices)} tickers")

    # ── HYPOTHESIS TESTS ──────────────────────────────────────────────────────
    print("\n" + "═" * 70)
    print("  H1: FUNDAMENTALS FILTER (score >= 60)")
    print("  Do stocks with strong fundamentals outperform?")
    print("═" * 70)

    for tf, col in [("3D", "ret_3d"), ("5D", "ret_5d")]:
        all_r   = [r[col] for r in records if r[col] is not None]
        strong  = [r[col] for r in records if r[col] is not None and r["fund_score"] >= 60]
        weak    = [r[col] for r in records if r[col] is not None and r["fund_score"] <  60]

        _print_comparison(
            "All tickers (baseline)",       _stats(all_r),
            "Fundamental score >= 60",      _stats(strong), tf
        )
        if weak:
            print(f"  [{tf}] {'Fundamental score < 60':35s}  n={_stats(weak)['n']:>3}  "
                  f"win={_stats(weak)['win_rate']:>5.1f}%  avg={_stats(weak)['avg_ret']:>+5.2f}%")

    print("\n" + "═" * 70)
    print("  H2: SECTOR ROTATION — LEADING vs LAGGING")
    print("  Do leading-sector trades outperform lagging-sector trades?")
    print("═" * 70)

    for tf, col in [("3D", "ret_3d"), ("5D", "ret_5d")]:
        all_r     = [r[col] for r in records if r[col] is not None]
        lead_r    = [r[col] for r in records if r[col] is not None and r["is_leading"] is True]
        lag_r     = [r[col] for r in records if r[col] is not None and r["is_lagging"] is True]
        unmapped  = sum(1 for r in records if r[col] is not None and r["is_leading"] is None)

        _print_comparison(
            "Leading sector trades",        _stats(lead_r),
            "Lagging sector trades",        _stats(lag_r),   tf
        )
        if all_r:
            print(f"  [{tf}] {'Baseline (all)':35s}  n={_stats(all_r)['n']:>3}  "
                  f"win={_stats(all_r)['win_rate']:>5.1f}%  avg={_stats(all_r)['avg_ret']:>+5.2f}%")
        if unmapped > 0:
            print(f"  [{tf}]   ({unmapped} observations with unmapped sector — excluded from H2)")

    # ── COMBINED FILTER ───────────────────────────────────────────────────────
    print("\n" + "═" * 70)
    print("  COMBINED: fundamentals >= 60 + leading sector")
    print("═" * 70)

    for tf, col in [("3D", "ret_3d"), ("5D", "ret_5d")]:
        all_r = [r[col] for r in records if r[col] is not None]
        combined = [
            r[col] for r in records
            if r[col] is not None
            and r["fund_score"] >= 60
            and r["is_leading"] is True
        ]
        _print_comparison(
            "All (baseline)",               _stats(all_r),
            "Both filters active",          _stats(combined), tf
        )

    print("\n" + "═" * 70)
    print("  INTERPRETATION GUIDE")
    print("  win_rate > baseline win_rate   → filter ADDS value (use it)")
    print("  avg_ret  > baseline avg_ret    → filter improves expected return")
    print("  n < 20 obs                     → insufficient data (interpret cautiously)")
    print("═" * 70)
    print(f"\n  Completed: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")


if __name__ == "__main__":
    run_backtest()
