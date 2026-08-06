#!/usr/bin/env python3
"""
research/price_hit_research.py — Can we get price-hit >= 75%?

Research the REACHABILITY CURVE: over real NSE OHLCV, how often does the favorable move reach a
target of X%? This tells us the max achievable "price-hit" for a directional target at each level,
and whether volatility/confidence gating can push a >=1% target to 75%+.

Two grading modes (both used in the codebase):
  TOUCH  — the intraday High (bull) / Low (bear) over the window touches the target (lenient; this
           is what ml_intraday_backtest + backtest.py target_hit use).
  CLOSE  — the horizon CLOSE move reaches the target (strict).

No LLM. Deterministic. Run:  python research/price_hit_research.py
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

DATA_START = "2024-06-01"
DATA_END   = "2026-07-17"
TEST_START = "2025-01-01"
STEP       = 3

BASE_TICKERS = [
    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","INFY.NS","ICICIBANK.NS","SBIN.NS","TATASTEEL.NS",
    "HINDALCO.NS","AXISBANK.NS","MARUTI.NS","SUNPHARMA.NS","ITC.NS","LT.NS","DLF.NS","ADANIENT.NS",
    "BAJFINANCE.NS","WIPRO.NS","HCLTECH.NS","ONGC.NS","COALINDIA.NS","JSWSTEEL.NS","POWERGRID.NS",
    "NTPC.NS","GRASIM.NS","HINDZINC.NS","VEDL.NS","ASHOKLEY.NS","IDEA.NS","YESBANK.NS","PNB.NS",
    "IRFC.NS","TATAPOWER.NS","BEL.NS","BANKBARODA.NS","GAIL.NS","IOC.NS","SAIL.NS","NMDC.NS",
]


def _reach_level(series: pd.Series, target_hit: float) -> float:
    """Smallest X where P(series >= X) <= target_hit — i.e. the target level that IS hit target_hit."""
    xs = np.arange(0.1, 4.0, 0.05)
    for x in xs:
        if (series >= x).mean() <= target_hit:
            return round(float(x), 2)
    return float("nan")


def main():
    tickers = sorted(set(BASE_TICKERS))
    print(f"Fetching {len(tickers)} tickers {DATA_START}->{DATA_END} ...")
    sc, sh, sl, sv, nc, vc = fetch_data(tickers, DATA_START, DATA_END)
    test_start = pd.Timestamp(TEST_START)

    rows = []
    for ticker in tickers:
        if ticker not in sc.columns:
            continue
        c = sc[ticker].dropna()
        for date in c.index[c.index >= test_start][::STEP]:
            try:
                price = float(c.loc[:date].iloc[-1])
                inds = _compute_indicators(sc[ticker], sh[ticker], sl[ticker], sv[ticker], date)
                atr14 = inds.get("atr14")
                if not price or not atr14:
                    continue
                up0, dn0, up1, dn1, up3, dn3, up5, dn5 = _fwd_intraday_moves(sc, sh, sl, date, ticker)
                r1, r3, r5 = _fwd_returns(sc, date, ticker)
                rows.append(dict(atr_pct=atr14/price*100.0, up0=up0, dn0=dn0, up1=up1, dn1=dn1, r1=r1))
            except Exception:
                continue
    df = pd.DataFrame(rows).replace([np.inf, -np.inf], np.nan)
    print(f"Rows: {len(df)}   median ATR%: {df['atr_pct'].median():.2f}\n")

    def curve(name, fav):
        fav = fav.dropna()
        print(f"── {name}  (n={len(fav)}) ──")
        print("   target X% :  " + "  ".join(f"{x:>4.1f}" for x in [0.5,0.75,1.0,1.25,1.5,2.0]))
        print("   P(reach)  :  " + "  ".join(f"{(fav>=x).mean()*100:>4.0f}" for x in [0.5,0.75,1.0,1.25,1.5,2.0]))
        for h in (0.75, 0.80):
            print(f"   → target for {int(h*100)}% hit: {_reach_level(fav, h)}%")
        print()

    print("=" * 70); print("REACHABILITY (TOUCH grading — intraday High/Low touches target)"); print("=" * 70)
    curve("INTRADAY bull (same-day High vs close, up0)", df["up0"])
    curve("1D bull (next-day High vs close, up1)",       df["up1"])
    curve("INTRADAY bear (|dn0|)", df["dn0"].abs())
    curve("1D bear (|dn1|)",       df["dn1"].abs())

    print("=" * 70); print("REACHABILITY (CLOSE grading — 1D close move, r1)"); print("=" * 70)
    curve("1D bull close (r1>0 side)", df["r1"].clip(lower=0))
    print(f"   P(close up)   : {(df['r1']>0).mean()*100:.0f}%   P(close up & r1>=1%): {((df['r1']>=1.0)).mean()*100:.0f}%\n")

    print("=" * 70); print("VOLATILITY GATING — reach of a FIXED 1.0% target by ATR quartile"); print("=" * 70)
    q = pd.qcut(df["atr_pct"], 4, labels=["Q1 quiet","Q2","Q3","Q4 violent"])
    for tf, fav in (("INTRADAY up0", df["up0"]), ("1D up1", df["up1"])):
        print(f"  {tf}:")
        for name, grp in fav.groupby(q):
            g = grp.dropna()
            print(f"    {name:<11} ATR%~{df.loc[g.index,'atr_pct'].median():4.1f}  "
                  f"P(reach 1.0%)={ (g>=1.0).mean()*100:4.0f}%  P(reach 1.25%)={(g>=1.25).mean()*100:4.0f}%")
        print()


if __name__ == "__main__":
    main()
