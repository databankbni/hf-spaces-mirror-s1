#!/usr/bin/env python3
"""
research/tight_range_backtest.py — Deterministic reachability backtest for the TIGHT INTRADAY/1D
directional bands (user request 2026-07-30: "ranges should be short like 1.0–1.25 so the mean is
clear — check, fix, backtest").

The tight band is a deterministic function of (direction, ATR%) applied AFTER the LLM/ML direction
call (predictor_core / ai_forecast._TIGHT_BAND). Direction accuracy is unchanged by the band shape,
so we isolate the *range* quality here — no LLM calls, fast — by measuring, over real NSE OHLCV, how
often the tight band's targets are actually reached when the direction is right:

  mean_hit  = P(favorable move >= band midpoint)   ← the actionable "did the mean get hit"
  near_hit  = P(favorable move >= band near bound)  ← band entered at all
  For 1D we also condition on the realized close direction (r1) to reflect the directional call.

It also prints the OLD band's metric for context (INTRADAY old = wide floored band; 1D old = the flat
±1% range-only containment) so the accuracy trade-off of tightening is explicit.

Run:  python research/tight_range_backtest.py
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

from backtest import fetch_data, _compute_indicators, _fwd_intraday_moves, _fwd_returns
import predictor_core as pc

DATA_START = "2024-06-01"
DATA_END   = "2026-07-17"
TEST_START = "2025-01-01"
STEP       = 5   # every 5 trading days

# A diversified fixed set across sectors/cap tiers (+ current watchlist).
BASE_TICKERS = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS", "SBIN.NS",
    "TATASTEEL.NS", "HINDALCO.NS", "AXISBANK.NS", "MARUTI.NS", "TATAMOTORS.NS",
    "SUNPHARMA.NS", "ITC.NS", "LT.NS", "DLF.NS", "ADANIENT.NS", "BAJFINANCE.NS",
    "WIPRO.NS", "HCLTECH.NS", "ONGC.NS", "COALINDIA.NS", "JSWSTEEL.NS",
    "POWERGRID.NS", "NTPC.NS", "GRASIM.NS", "HINDZINC.NS", "VEDL.NS",
    "ASHOKLEY.NS", "IDEA.NS", "YESBANK.NS", "PNB.NS", "IRFC.NS",
]


def _watchlist():
    try:
        import database as db
        return [w["ticker"] for w in db.get_watchlist()]
    except Exception:
        return []


def _old_intraday_band(atr_pct: float):
    """Reconstruct the PRE-tight INTRADAY band (both bounds floored to >=1%, far volatility-scaled).
    near ~ 0.148*ATR% floored to 1; far ~ 0.47*ATR% floored to >=1 & capped 2, spread>=0.15."""
    near = 0.12 * (1.31 ** 0.83) * atr_pct            # ~0.148*ATR%
    far  = 0.156 * (5.70 ** 0.6354) * atr_pct         # ~0.47*ATR%
    far  = min(2.0, far)
    if far - near < 0.15:
        far = near + 0.15
    near = max(near, 1.0)
    far  = max(far, near + 0.15)
    far  = min(2.0, far)
    return near, far


def main():
    tickers = sorted(set(BASE_TICKERS + _watchlist()))
    print(f"Fetching {len(tickers)} tickers {DATA_START}→{DATA_END} …")
    sc, sh, sl, sv, nc, vc = fetch_data(tickers, DATA_START, DATA_END)

    test_start = pd.Timestamp(TEST_START)
    rows = []
    for ticker in tickers:
        if ticker not in sc.columns:
            continue
        c = sc[ticker].dropna()
        dates = c.index[c.index >= test_start][::STEP]
        for date in dates:
            try:
                price = float(c.loc[:date].iloc[-1])
                inds = _compute_indicators(sc[ticker], sh[ticker], sl[ticker], sv[ticker], date)
                atr14 = inds.get("atr14")
                if not price or not atr14:
                    continue
                atr_pct = atr14 / price * 100.0
                up0, dn0, up1, dn1, up3, dn3, up5, dn5 = _fwd_intraday_moves(sc, sh, sl, date, ticker)
                r1, r3, r5 = _fwd_returns(sc, date, ticker)
                rows.append(dict(ticker=ticker, date=date, atr_pct=atr_pct,
                                 up0=up0, dn0=dn0, up1=up1, dn1=dn1, r1=r1))
            except Exception:
                continue

    df = pd.DataFrame(rows).replace([np.inf, -np.inf], np.nan)
    print(f"Rows: {len(df)}\n")

    # ── INTRADAY ────────────────────────────────────────────────────────────
    d = df.dropna(subset=["up0", "atr_pct"])
    near = d["atr_pct"].apply(lambda a: pc._tight_band_mag("INTRADAY", a)[0])
    far  = d["atr_pct"].apply(lambda a: pc._tight_band_mag("INTRADAY", a)[1])
    mid  = (near + far) / 2.0
    old  = d["atr_pct"].apply(lambda a: _old_intraday_band(a))
    old_mid = old.apply(lambda t: (t[0] + t[1]) / 2.0)
    print("=" * 68)
    print("INTRADAY  (favorable move = same-day High vs close, up0)")
    print("=" * 68)
    print(f"  avg band width : {(far-near).mean():.3f}%   avg mid: {mid.mean():.3f}%   "
          f"(OLD avg mid {old_mid.mean():.3f}%, width {(old.apply(lambda t:t[1]-t[0])).mean():.3f}%)")
    print(f"  NEW mean_hit   : {(d['up0'] >= mid).mean()*100:5.1f}%   "
          f"near_hit {(d['up0'] >= near).mean()*100:5.1f}%   far_hit {(d['up0'] >= far).mean()*100:5.1f}%")
    print(f"  OLD mean_hit   : {(d['up0'] >= old_mid).mean()*100:5.1f}%   "
          f"(same up0, wider band → higher raw hit but fuzzier mean)")

    # ── 1D ─────────────────────────────────────────────────────────────────
    d = df.dropna(subset=["up1", "r1", "atr_pct"])
    near = d["atr_pct"].apply(lambda a: pc._tight_band_mag("1D", a)[0])
    far  = d["atr_pct"].apply(lambda a: pc._tight_band_mag("1D", a)[1])
    mid  = (near + far) / 2.0
    up_day = d["r1"] > 0
    print("\n" + "=" * 68)
    print("1D  (directional: favorable move = next-day High vs close, up1)")
    print("=" * 68)
    print(f"  avg band width : {(far-near).mean():.3f}%   avg mid: {mid.mean():.3f}%")
    # Directional target_hit: called BULLISH, closed up, and intraday high reached the mean.
    tgt = up_day & (d["up1"] >= mid)
    print(f"  NEW dir target_hit (closed up & high>=mid): {tgt.mean()*100:5.1f}%")
    print(f"  NEW mean_hit | up-day                     : {(d.loc[up_day,'up1'] >= mid.loc[up_day]).mean()*100:5.1f}%")
    print(f"  P(closed up)                              : {up_day.mean()*100:5.1f}%")
    # OLD 1D = flat +/-1% range-only containment claim.
    print(f"  OLD 1D range-only hit  P(|r1| <= 1%)      : {(d['r1'].abs() <= 1.0).mean()*100:5.1f}%")


if __name__ == "__main__":
    main()
