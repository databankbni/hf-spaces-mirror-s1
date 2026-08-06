#!/usr/bin/env python3
"""
intraday_eod_backtest.py — Validate INTRADAY profitability the way the historical
daily CSVs can't (they have no intraday bars). Uses yfinance 15m bars (last ~60d).

For a random trading day (or several), enter each liquid stock at 09:15 / 10:00 /
11:00 / 12:00 IST and measure the move to end-of-day (and to the 15:00 IST hit
cutoff the engine uses). Reports:
  1. RAW drift  — P&L of a plain long from entry time to EOD (base rate).
  2. FILTERED   — P&L of a directional trade (long if morning momentum + ORB are
                  bullish, short if bearish, else skip) — mirrors the engine's
                  fast INTRADAY signals (S1/S4/S8/S16 = oversold-bounce/momentum).

Usage:
    python research/intraday_eod_backtest.py                 # 8 random days
    python research/intraday_eod_backtest.py --days 15       # 15 random days
    python research/intraday_eod_backtest.py --date 2026-07-09   # one fixed day
"""
import os, sys, argparse, random
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from intraday_live import get_intraday_bars

IST = "Asia/Kolkata"
# Highly liquid NSE large-caps — all have reliable 15m data.
BASKET = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
          "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "LT.NS", "AXISBANK.NS",
          "KOTAKBANK.NS", "HINDUNILVR.NS", "BAJFINANCE.NS", "MARUTI.NS", "TATASTEEL.NS"]
ENTRY_TIMES = [(9, 15), (10, 0), (11, 0), (12, 0)]   # IST hh:mm
CUTOFF = (15, 0)   # engine's intraday-hit cutoff


def _to_ist(bars: pd.DataFrame) -> pd.DataFrame:
    """Normalise the bar index to IST tz-aware."""
    idx = bars.index
    if idx.tz is None:
        bars = bars.tz_localize("UTC").tz_convert(IST)
    else:
        bars = bars.tz_convert(IST)
    return bars


def _day_sessions(bars: pd.DataFrame) -> dict:
    """Split bars into {date: day_bars} keyed by IST calendar date."""
    out = {}
    for d, g in bars.groupby(bars.index.normalize()):
        # Keep only regular-session bars (09:15–15:30 IST)
        g = g[[(t.hour, t.minute) >= (9, 15) and t.hour < 16 for t in g.index]]
        if len(g) >= 6:  # need a reasonably full session
            out[d.date()] = g
    return out


def _bar_at_or_after(day_bars: pd.DataFrame, hh: int, mm: int):
    """First bar at/after the given IST time; None if none."""
    mask = [(t.hour, t.minute) >= (hh, mm) for t in day_bars.index]
    sub = day_bars[mask]
    return sub.iloc[0] if len(sub) else None


def _price_at_cutoff(day_bars: pd.DataFrame):
    """Close of the last bar at/before the 15:00 cutoff."""
    mask = [(t.hour, t.minute) <= CUTOFF for t in day_bars.index]
    sub = day_bars[mask]
    return float(sub.iloc[-1]["Close"]) if len(sub) else float(day_bars.iloc[-1]["Close"])


def analyse(all_days: dict, sample_dates: list) -> None:
    # results[entry_time] -> list of pnl% for each strategy
    raw = {et: [] for et in ENTRY_TIMES}          # plain long
    mom = {et: [] for et in ENTRY_TIMES}          # momentum-continuation
    rev = {et: [] for et in ENTRY_TIMES}          # oversold-bounce / reversion (engine's actual bias)
    mom_dir = {et: {"long": 0, "short": 0, "skip": 0} for et in ENTRY_TIMES}
    rev_dir = {et: {"long": 0, "short": 0, "skip": 0} for et in ENTRY_TIMES}

    for (ticker, date), day_bars in all_days.items():
        if date not in sample_dates:
            continue
        day_open = float(day_bars.iloc[0]["Open"])
        eod = float(day_bars.iloc[-1]["Close"])
        orb = day_bars.iloc[:1]  # first 15m bar = opening range
        orb_hi, orb_lo = float(orb["High"].iloc[0]), float(orb["Low"].iloc[0])

        for et in ENTRY_TIMES:
            bar = _bar_at_or_after(day_bars, *et)
            if bar is None:
                continue
            entry = float(bar["Open"])
            if entry <= 0:
                continue
            ret_eod = (eod / entry - 1) * 100
            move = (entry / day_open - 1) * 100   # move since open at entry time
            above_orb, below_orb = entry > orb_hi, entry < orb_lo

            raw[et].append(ret_eod)

            # MOMENTUM: follow the move (long if up, short if down)
            if move > 0.1 and not below_orb:
                mom[et].append(ret_eod);   mom_dir[et]["long"] += 1
            elif move < -0.1 and not above_orb:
                mom[et].append(-ret_eod);  mom_dir[et]["short"] += 1
            else:
                mom_dir[et]["skip"] += 1

            # REVERSION (engine's INTRADAY bias): fade the move — long if DOWN
            # (oversold bounce), short if UP (fade the pop).
            if move < -0.2:
                rev[et].append(ret_eod);   rev_dir[et]["long"] += 1     # long the dip
            elif move > 0.2:
                rev[et].append(-ret_eod);  rev_dir[et]["short"] += 1    # fade the pop
            else:
                rev_dir[et]["skip"] += 1

    def _row(label, arr):
        if not arr:
            return f"  {label:18s}  n=   0"
        a = np.array(arr)
        return (f"  {label:18s}  n={len(a):4d}  avgP&L={a.mean():+.3f}%  "
                f"win%={(a>0).mean()*100:4.0f}  median={np.median(a):+.3f}%  "
                f"best={a.max():+.2f}%  worst={a.min():+.2f}%")

    print(f"\n{'='*78}\nRAW long — entry time → EOD (base rate, no direction filter)\n{'='*78}")
    for et in ENTRY_TIMES:
        print(_row(f"{et[0]:02d}:{et[1]:02d} IST", raw[et]))

    print(f"\n{'='*78}\nMOMENTUM — follow the move (long if up / short if down since open)\n{'='*78}")
    for et in ENTRY_TIMES:
        d = mom_dir[et]
        print(_row(f"{et[0]:02d}:{et[1]:02d} IST", mom[et]) +
              f"   [L={d['long']} S={d['short']} skip={d['skip']}]")

    print(f"\n{'='*78}\nREVERSION — fade the move (long the dip / short the pop) = engine's bias\n{'='*78}")
    for et in ENTRY_TIMES:
        d = rev_dir[et]
        print(_row(f"{et[0]:02d}:{et[1]:02d} IST", rev[et]) +
              f"   [L={d['long']} S={d['short']} skip={d['skip']}]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=8, help="number of random days to sample")
    ap.add_argument("--date", type=str, default=None, help="fixed date YYYY-MM-DD")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()
    if args.seed is not None:
        random.seed(args.seed)

    print(f"Fetching 15m bars (last 60d) for {len(BASKET)} liquid NSE stocks…")
    all_days = {}          # (ticker, date) -> day_bars
    date_universe = set()
    for tk in BASKET:
        bars = get_intraday_bars(tk, interval="15m", period="60d")
        if bars is None or bars.empty:
            print(f"  [skip] {tk}: no data")
            continue
        bars = _to_ist(bars)
        sessions = _day_sessions(bars)
        for d, g in sessions.items():
            all_days[(tk, d)] = g
            date_universe.add(d)
    print(f"  Loaded {len(all_days)} stock-days across {len(date_universe)} sessions.")

    all_dates = sorted(date_universe)
    if args.date:
        target = pd.to_datetime(args.date).date()
        sample = [target] if target in date_universe else []
        if not sample:
            print(f"\n{args.date} not in available sessions. Available: "
                  f"{all_dates[0]} … {all_dates[-1]}")
            return
    else:
        # skip the 2 most recent (may be partial) then sample
        pool = all_dates[:-2] if len(all_dates) > 4 else all_dates
        sample = sorted(random.sample(pool, min(args.days, len(pool))))

    print(f"\nSampled {len(sample)} session(s): {', '.join(str(d) for d in sample)}")
    analyse(all_days, sample)


if __name__ == "__main__":
    main()
