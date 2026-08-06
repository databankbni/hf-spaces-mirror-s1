#!/usr/bin/env python3
"""
research/entry_validation_backtest.py
──────────────────────────────────────
Validates the entry-price open-buffer change against 7 years of NSE data.

Questions answered
──────────────────
Q1  Entry achievability   — Do BUY-signal stocks actually gap UP at next open?
                            Is the timeframe-aware buffer enough to model realistic entry?

Q2  Target hit (strict)   — Does price reach target_hi WITHIN the predicted TF?
                            Reaching target on day-6 for a 5D prediction = FAIL.

Q3  Time-to-target        — For successful trades, how many days did it take?
                            Distribution: same-day vs within-TF vs late vs never.

Q4  Entry impact on R:R   — Old entry (= close) vs new entry (TF buffer).
                            Does the dynamic buffer meaningfully hurt hit rate?

Q5  Failure decomposition — Why did target NOT get hit within TF?
                            Gap-up miss at entry | stalled price | reversed.

Data source: research/ai_prompt_accuracy_iter64.csv  (7 years, 828 rows)
             + actual OHLCV with Open fetched from Yahoo Finance.

Usage:
    python research/entry_validation_backtest.py
    python research/entry_validation_backtest.py --no-cache   # re-download OHLCV
"""
from __future__ import annotations
import sys, os, argparse, pickle
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf

# ── CONFIG ────────────────────────────────────────────────────────────────────
CSV_PATH   = os.path.join(os.path.dirname(__file__), "ai_prompt_accuracy_iter64.csv")
CACHE_FILE = os.path.join(os.path.dirname(__file__), "cache", "ev_ohlcv_with_open.pkl")
ENTRY_BUFFER_BY_TF = {
    "1D": 0.002,  # 0.20%
    "3D": 0.003,  # 0.30%
    "5D": 0.005,  # 0.50%
}
SEP  = "=" * 72
SEP2 = "─" * 72

TICKERS = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS",
    "BAJFINANCE.NS", "SUNPHARMA.NS", "WIPRO.NS",
]

# ── OHLCV DOWNLOAD (includes Open) ───────────────────────────────────────────

def _download_ohlcv(tickers: list[str], no_cache: bool) -> dict[str, pd.DataFrame]:
    """Returns {ticker: DataFrame(Date, Open, High, Low, Close)}."""
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    if not no_cache and os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "rb") as f:
            print("  [cache] Loaded OHLCV with Open from disk.")
            return pickle.load(f)

    print(f"  Downloading {len(tickers)} tickers 2017–2025 from Yahoo Finance…")
    raw = yf.download(tickers, start="2017-01-01", end="2025-06-01",
                      auto_adjust=True, progress=True)
    result = {}
    for tk in tickers:
        try:
            df = pd.DataFrame({
                "Open":  raw["Open"][tk],
                "High":  raw["High"][tk],
                "Low":   raw["Low"][tk],
                "Close": raw["Close"][tk],
            }).dropna()
            df.index = pd.to_datetime(df.index)
            result[tk] = df
        except Exception as e:
            print(f"  WARNING: {tk} failed — {e}")

    with open(CACHE_FILE, "wb") as f:
        pickle.dump(result, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"  Saved OHLCV cache → {CACHE_FILE}")
    return result


# ── PER-ROW ANALYSIS ─────────────────────────────────────────────────────────

TF_DAYS = {"1D": 1, "3D": 3, "5D": 5}


def _analyse_row(row: pd.Series, ohlcv: dict[str, pd.DataFrame]) -> dict | None:
    ticker = row["ticker"]
    tf     = str(row["timeframe"])
    n_days = TF_DAYS.get(tf)
    if n_days is None:
        return None

    df = ohlcv.get(ticker)
    if df is None or df.empty:
        return None

    # Find signal date in OHLCV index
    sig_date = pd.to_datetime(row["date"])
    future   = df[df.index > sig_date].head(n_days + 1)   # +1 for entry day check
    if len(future) < 2:
        return None                                         # not enough forward data

    entry_day = future.iloc[0]       # the NEXT trading day (entry day)

    close_price  = float(row["entry_price"])   # previous day's close (signal bar)
    target_hi    = float(row["target_price_hi"])
    target_lo    = float(row["target_price_lo"])
    direction    = str(row["direction"])        # BULLISH / BEARISH / NEUTRAL

    # ── Entry prices ─────────────────────────────────────────────────────────
    entry_old = close_price  # old behaviour: last close
    buf = ENTRY_BUFFER_BY_TF.get(tf, 0.003)
    if direction in ("BULLISH", "BUY", "STRONG BUY"):
        entry_new = round(close_price * (1 + buf), 4)
    elif direction in ("BEARISH", "SELL"):
        entry_new = round(close_price * (1 - buf), 4)
    else:
        entry_new = close_price

    next_open   = float(entry_day["Open"])
    gap_pct     = (next_open - close_price) / close_price * 100

    # Was entry achievable at open?
    if direction in ("BULLISH", "BUY", "STRONG BUY"):
        entry_old_filled = next_open <= entry_old
        entry_new_filled = next_open <= entry_new
    elif direction in ("BEARISH", "SELL"):
        entry_old_filled = next_open >= entry_old
        entry_new_filled = next_open >= entry_new
    else:
        entry_old_filled = False
        entry_new_filled = False

    # ── Target prices (both anchored to close, same as production) ───────────
    ret_hi_pct = (target_hi / close_price - 1) * 100
    ret_lo_pct = (target_lo / close_price - 1) * 100
    target_hi_old = target_hi
    target_hi_new = target_hi

    # ── All highs during holding period (entry day + holding days) ────────────
    all_highs = list(future["High"])     # day1..dayN
    all_lows  = list(future["Low"])
    all_dates = list(future.index)

    # Days-to-target: first day high touches target_hi_new (within TF)
    days_to_target_old = None
    days_to_target_new = None
    for i, (h, d) in enumerate(zip(all_highs, all_dates)):
        day_num = i + 1   # 1-indexed
        if direction in ("BULLISH", "BUY", "STRONG BUY"):
            if days_to_target_old is None and h >= target_hi_old:
                days_to_target_old = day_num
            if days_to_target_new is None and h >= target_hi_new:
                days_to_target_new = day_num
        elif direction in ("BEARISH", "SELL"):
            # For BEARISH: target is the lo (price goes down)
            if days_to_target_old is None and all_lows[i] <= target_lo:
                days_to_target_old = day_num
            if days_to_target_new is None and all_lows[i] <= target_lo:
                days_to_target_new = day_num

    # ── Target hit within TF ─────────────────────────────────────────────────
    hit_old_within_tf = days_to_target_old is not None and days_to_target_old <= n_days
    hit_new_within_tf = days_to_target_new is not None and days_to_target_new <= n_days

    # ── Actual P&L at end of TF (close of last holding day) ──────────────────
    exit_close = float(future.iloc[-1]["Close"])
    pnl_old_pct = (exit_close - entry_old) / entry_old * 100
    if direction in ("BEARISH", "SELL"):
        pnl_new_pct = (entry_new - exit_close) / entry_new * 100
    else:
        pnl_new_pct = (exit_close - entry_new) / entry_new * 100

    # ── Failure mode classification ───────────────────────────────────────────
    # Only for BULLISH predictions that missed target_new within TF
    failure_mode = "N/A"
    if direction in ("BULLISH", "BUY", "STRONG BUY") and not hit_new_within_tf:
        if not entry_new_filled:
            failure_mode = "entry_gap_miss"        # stock gapped past entry
        elif max(all_highs) >= target_hi_new:
            failure_mode = "hit_but_late"          # hit target after TF expired
        elif pnl_new_pct > 0:
            failure_mode = "stalled_short"         # moved right direction but not enough
        elif pnl_new_pct < -1:
            failure_mode = "reversed"              # went the wrong way
        else:
            failure_mode = "flat"                  # barely moved

    return {
        "ticker":            ticker,
        "date":              sig_date,
        "tf":                tf,
        "n_days":            n_days,
        "direction":         direction,
        "close_price":       close_price,
        "next_open":         next_open,
        "gap_pct":           round(gap_pct, 3),
        "entry_old":         entry_old,
        "entry_new":         entry_new,
        "entry_old_filled":  entry_old_filled,
        "entry_new_filled":  entry_new_filled,
        "target_hi_old":     round(target_hi_old, 3),
        "target_hi_new":     round(target_hi_new, 3),
        "ret_hi_pct":        round(ret_hi_pct, 3),
        "days_to_target_old": days_to_target_old,
        "days_to_target_new": days_to_target_new,
        "hit_old_within_tf": hit_old_within_tf,
        "hit_new_within_tf": hit_new_within_tf,
        "pnl_old_pct":       round(pnl_old_pct, 3),
        "pnl_new_pct":       round(pnl_new_pct, 3),
        "failure_mode":      failure_mode,
        "max_up_for_tf":     float(row.get("max_up_for_tf", 0)),
        "min_down_for_tf":   float(row.get("min_down_for_tf", 0)),
        "confidence":        row.get("confidence", ""),
    }


# ── REPORT PRINTER ────────────────────────────────────────────────────────────

def _pct(n: int, d: int) -> str:
    return f"{n/d*100:.1f}%" if d else "N/A"


def print_report(df: pd.DataFrame) -> None:
    bull = df[df["direction"].isin(["BULLISH", "BUY", "STRONG BUY"])]
    bear = df[df["direction"].isin(["BEARISH", "SELL"])]

    print(f"\n{SEP}")
    print("  ENTRY PRICE VALIDATION BACKTEST")
    print(f"  Data: {df['date'].min().date()} → {df['date'].max().date()} "
          f"| {len(df)} predictions | 6 NSE stocks | 3 timeframes")
    print(SEP)

    # ── Q1: Gap-up behavior at next open ─────────────────────────────────────
    print(f"\n{'Q1  ENTRY ACHIEVABILITY — Gap at Next Open':^72}")
    print(SEP2)
    print(f"{'Metric':<45} {'BULLISH':>12} {'BEARISH':>12}")
    print(SEP2)

    for label, subset in [("BULLISH", bull), ("BEARISH", bear)]:
        gaps = subset["gap_pct"]
        if not len(gaps):
            continue
        print(f"  Avg gap next-open vs close  ({label:<8})   {gaps.mean():>+.3f}%")
        print(f"  Median gap                               {gaps.median():>+.3f}%")
        print(f"  % that gap UP > 0                        {_pct((gaps > 0).sum(), len(gaps))}")
        print(f"  % that gap > 0.3% (misses buffer)        {_pct((gaps > 0.3).sum(), len(gaps))}")
        print(f"  % that gap > 0.5%                        {_pct((gaps > 0.5).sum(), len(gaps))}")
        print(f"  % that gap > 1.0%                        {_pct((gaps > 1.0).sum(), len(gaps))}")
        print()

    print(f"  Entry fill rate — old (at close) :  {_pct(bull['entry_old_filled'].sum(), len(bull))}")
    print(f"  Entry fill rate — new (TF policy):  {_pct(bull['entry_new_filled'].sum(), len(bull))}")
    print(f"  Improvement in fill rate          :  "
          f"+{(bull['entry_new_filled'].mean() - bull['entry_old_filled'].mean())*100:.1f}pp")

    # ── Q2: Strict TF target hit rate ────────────────────────────────────────
    print(f"\n{SEP2}")
    print(f"{'Q2  STRICT TARGET HIT — within predicted timeframe':^72}")
    print(SEP2)
    print(f"{'TF':<6} {'N':>5}  {'OldHit%':>9}  {'NewHit%':>9}  {'Delta':>8}  {'AvgRetHi%':>10}")
    print(SEP2)

    for tf in ["1D", "3D", "5D"]:
        sub = bull[bull["tf"] == tf]
        if sub.empty:
            continue
        old_hit = sub["hit_old_within_tf"].mean() * 100
        new_hit = sub["hit_new_within_tf"].mean() * 100
        avg_ret = sub["ret_hi_pct"].mean()
        print(f"  {tf:<4} {len(sub):>5}  {old_hit:>8.1f}%  {new_hit:>8.1f}%  "
              f"{new_hit-old_hit:>+7.1f}pp  {avg_ret:>9.2f}%")

    print()
    print(f"  Key insight: Target hit rate should stay the same old vs new.")
    print(f"  Entry policy changes fill quality and P&L, not market target reachability.")

    # ── Q3: Time-to-target distribution ──────────────────────────────────────
    print(f"\n{SEP2}")
    print(f"{'Q3  TIME TO TARGET (BULLISH predictions that hit)':^72}")
    print(SEP2)
    print(f"{'TF':<6} {'Hit same-day':>14} {'Hit day 2':>11} {'Hit day 3':>11} "
          f"{'Hit day 4-5':>12} {'Never/Late':>11}")
    print(SEP2)

    for tf in ["1D", "3D", "5D"]:
        n_days = TF_DAYS[tf]
        sub    = bull[bull["tf"] == tf].copy()
        total  = len(sub)
        d = sub["days_to_target_new"].copy()

        day1   = (d == 1).sum()
        day2   = (d == 2).sum()
        day3   = (d == 3).sum()
        day45  = ((d >= 4) & (d <= 5)).sum()
        late   = total - day1 - day2 - day3 - day45

        def pp(n): return f"{_pct(n,total):>10}"
        print(f"  {tf:<4} {pp(day1)} {pp(day2)} {pp(day3)} {pp(day45)} {pp(late)}")

    # Average days-to-target for successful trades
    print()
    hits = bull[bull["hit_new_within_tf"]]
    if len(hits):
        avg_days = hits["days_to_target_new"].mean()
        med_days = hits["days_to_target_new"].median()
        print(f"  Avg days-to-target (successful trades): {avg_days:.1f} days")
        print(f"  Median days-to-target                 : {med_days:.0f} days")

    # Prediction accuracy by TF: reached target exactly on the last day vs early
    print()
    for tf in ["1D", "3D", "5D"]:
        n_days = TF_DAYS[tf]
        sub    = bull[bull["tf"] == tf]
        hits_  = sub[sub["hit_new_within_tf"]]
        on_last_day = (hits_["days_to_target_new"] == n_days).sum()
        early       = (hits_["days_to_target_new"] < n_days).sum()
        print(f"  {tf}: {len(hits_)} hits — "
              f"{_pct(early, len(hits_))} hit EARLY (before TF end), "
              f"{_pct(on_last_day, len(hits_))} hit ON the final day")

    # ── Q4: P&L impact of entry buffer ───────────────────────────────────────
    print(f"\n{SEP2}")
    print(f"{'Q4  R:R IMPACT — old entry (close) vs new entry (TF buffer)':^72}")
    print(SEP2)
    print(f"{'TF':<6} {'Avg P&L old':>13} {'Avg P&L new':>13} {'Delta':>8} "
          f"{'Win% old':>10} {'Win% new':>10}")
    print(SEP2)

    for tf in ["1D", "3D", "5D"]:
        sub = bull[bull["tf"] == tf]
        if sub.empty:
            continue
        pnl_o = sub["pnl_old_pct"].mean()
        pnl_n = sub["pnl_new_pct"].mean()
        win_o = (sub["pnl_old_pct"] > 0).mean() * 100
        win_n = (sub["pnl_new_pct"] > 0).mean() * 100
        print(f"  {tf:<4} {pnl_o:>+12.2f}% {pnl_n:>+12.2f}% {pnl_n-pnl_o:>+7.3f}pp "
              f"{win_o:>9.1f}% {win_n:>9.1f}%")

    # ── Q5: Failure decomposition ─────────────────────────────────────────────
    print(f"\n{SEP2}")
    print(f"{'Q5  FAILURE MODE — why BULLISH trades missed target within TF':^72}")
    print(SEP2)

    misses = bull[~bull["hit_new_within_tf"]]
    modes  = misses["failure_mode"].value_counts()
    total_misses = len(misses)
    print(f"  Total missed: {total_misses} / {len(bull)} BULLISH predictions")
    print()

    labels = {
        "entry_gap_miss": "Gap-up past entry (unfillable at open)",
        "hit_but_late":   "Price DID hit target but AFTER TF expired",
        "stalled_short":  "Moved right direction, fell short of target",
        "reversed":       "Price reversed (down > -1%)",
        "flat":           "Price barely moved (±1%)",
    }
    for mode, count in modes.items():
        desc = labels.get(mode, mode)
        print(f"  {_pct(count, total_misses):>6}  {count:>4}  {desc}")

    # Sub-breakdown: "hit_but_late" — how late?
    late_hits = misses[misses["failure_mode"] == "hit_but_late"]
    if len(late_hits):
        print()
        print(f"  Of the {len(late_hits)} 'hit but late' cases:")
        for tf in ["1D", "3D", "5D"]:
            sub_late = late_hits[late_hits["tf"] == tf]
            if len(sub_late):
                med_d = sub_late["days_to_target_new"].median()
                print(f"    {tf}: {len(sub_late)} trades — median {med_d:.0f} days to target "
                      f"(vs {TF_DAYS[tf]}-day window)")

    # ── SUMMARY TABLE ─────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print(f"{'SUMMARY':^72}")
    print(SEP)
    print()
    print(f"  OLD SYSTEM (entry = last close):          "
          f"entry fills {_pct(bull['entry_old_filled'].sum(), len(bull))} of the time")
    print(f"  NEW SYSTEM (entry = close ± TF buffer):   "
          f"entry fills {_pct(bull['entry_new_filled'].sum(), len(bull))} of the time")
    print()
    for tf in ["1D", "3D", "5D"]:
        sub = bull[bull["tf"] == tf]
        old_hit = sub["hit_old_within_tf"].mean() * 100
        new_hit = sub["hit_new_within_tf"].mean() * 100
        print(f"  {tf} strict hit rate:  old={old_hit:.1f}%  new={new_hit:.1f}%  "
              f"delta={new_hit-old_hit:+.1f}pp")

    late_pct = _pct(
        bull[bull["failure_mode"] == "hit_but_late"].shape[0],
        len(bull[~bull["hit_new_within_tf"]])
    )
    print()
    print(f"  {late_pct} of all misses DID eventually hit target — just not within TF")
    print(f"  → These are 'false failures' where timeframe was too tight")
    print()

    gap_miss_pct = _pct(
        bull[bull["failure_mode"] == "entry_gap_miss"].shape[0], len(bull)
    )
    print(f"  {gap_miss_pct} of BULLISH trades had an unfillable gap-up at open")
    print(f"  → TF-aware buffer absorbs many of these; beyond policy threshold = skip")
    print(SEP)


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-cache", action="store_true", help="Re-download OHLCV")
    parser.add_argument("--csv",      default=CSV_PATH,   help="Input CSV path")
    parser.add_argument("--save",     default="",         help="Save results to CSV path")
    args = parser.parse_args()

    print(f"\n{SEP}")
    print("  Loading prediction CSV…")
    df = pd.read_csv(args.csv)
    df["date"] = pd.to_datetime(df["date"])
    print(f"  {len(df)} rows loaded from {os.path.basename(args.csv)}")

    print("\n  Loading OHLCV with Open prices…")
    ohlcv = _download_ohlcv(TICKERS, no_cache=args.no_cache)

    print("\n  Running per-row analysis…")
    results = []
    for _, row in df.iterrows():
        rec = _analyse_row(row, ohlcv)
        if rec:
            results.append(rec)

    out = pd.DataFrame(results)
    print(f"  Analysed {len(out)} rows (skipped {len(df) - len(out)} — insufficient fwd data)")

    if args.save:
        out.to_csv(args.save, index=False)
        print(f"  Results saved → {args.save}")

    print_report(out)


if __name__ == "__main__":
    main()
