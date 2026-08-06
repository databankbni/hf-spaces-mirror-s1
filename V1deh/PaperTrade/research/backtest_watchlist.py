#!/usr/bin/env python3
"""
research/backtest_watchlist.py — Backtest AI prompts on current watchlist stocks.

Uses realistic AI-owned ranges (tight_test=False) so results match what the UI shows.
Also runs a live spot-check prediction for each stock to verify UI output.

Run:
    python research/backtest_watchlist.py           # historical backtest + live spot-check
    python research/backtest_watchlist.py --live-only  # live spot-check only (fast)
"""
from __future__ import annotations
import sys, os, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import warnings
import threading
import time
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

from backtest import (
    fetch_data, _compute_indicators, _fwd_intraday_moves, _fwd_returns,
    _vix_nifty_series, _simple_ml_prob, run_backtest, print_results,
    TIMEFRAMES, NIFTY, VIX_TK,
)

# ── CONFIG ──────────────────────────────────────────────────────────────────
# Test last ~3 months with a step of 20 trading days → ~5 dates
DATA_START  = "2025-01-01"
DATA_END    = "2026-07-17"
TEST_START  = "2026-04-01"   # only run from this date forward
STEP        = 20             # every 20 trading days (~4 weeks)

_PACE_SECS  = int(os.environ.get("BACKTEST_LLM_PACE_SECS", 12))


def _get_watchlist_tickers():
    try:
        import database as db
        wl = db.get_watchlist()
        tickers = [w["ticker"] for w in wl]
        if not tickers:
            print("WARNING: Watchlist is empty — using fallback set")
            return ["TATASTEEL.NS", "AXISCADES.NS", "HINDZINC.NS"]
        return tickers
    except Exception as e:
        print(f"WARNING: Could not read watchlist ({e}) — using fallback set")
        return ["TATASTEEL.NS", "AXISCADES.NS", "HINDZINC.NS"]


def _snap_to_trading_day(idx, ts):
    prior = idx[idx <= ts]
    return prior[-1] if not prior.empty else None


def _build_work_items(tickers, dates, sc, sh, sl, sv, nc, vc, nifty_ema200, vix_slope):
    company_names = {t: t.replace(".NS", "") for t in tickers}
    work_items = []
    skipped = 0

    for date in dates:
        for ticker in tickers:
            if ticker not in sc.columns:
                continue
            snapped = _snap_to_trading_day(sc[ticker].dropna().index, date)
            if snapped is None or snapped != date:
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

            idx2 = sc[ticker].dropna().index.searchsorted(date, side="right")
            try:
                ohlcv = pd.DataFrame({
                    "High":   sh[ticker].iloc[max(0, idx2 - 20):idx2].values,
                    "Low":    sl[ticker].iloc[max(0, idx2 - 20):idx2].values,
                    "Close":  sc[ticker].iloc[max(0, idx2 - 20):idx2].values,
                    "Volume": sv[ticker].iloc[max(0, idx2 - 20):idx2].values,
                }).dropna()
            except Exception:
                ohlcv = None

            for tf in ["INTRADAY", "1D", "3D"]:  # 5D retired from UI
                ret_for_tf = {"INTRADAY": 0.0, "1D": r1, "3D": r3}[tf]
                if pd.isna(ret_for_tf) and tf != "INTRADAY":
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
        print(f"  ({skipped} (ticker,date) pairs skipped — missing macro data)")
    return work_items


def _print_summary(df, tickers):
    print("\n" + "=" * 70)
    print("Accuracy by Timeframe  (tight_test=False → AI's own ranges)")
    print("=" * 70)
    for tf in ["INTRADAY", "1D", "3D"]:
        sub = df[df["timeframe"] == tf]
        if sub.empty:
            continue
        n        = len(sub)
        tgt_hits = int(sub["target_hit_for_tf"].sum())
        dir_hits = int(sub["intraday_hit_for_tf"].sum())
        bullish  = int((sub["direction"] == "BULLISH").sum())
        bearish  = int((sub["direction"] == "BEARISH").sum())
        neutral  = int((sub["direction"] == "NEUTRAL").sum())
        avg_lo   = sub["target_price_lo"].mean() if "target_price_lo" in sub.columns else float("nan")
        avg_hi   = sub["target_price_hi"].mean() if "target_price_hi" in sub.columns else float("nan")
        avg_range_pct = sub.apply(
            lambda r: abs(r.get("target_price_hi", 0) - r.get("target_price_lo", 0)) /
                      r.get("entry_price", 1) * 100 if r.get("entry_price", 0) > 0 else 0,
            axis=1
        ).mean() if "target_price_hi" in sub.columns else float("nan")
        print(f"  {tf:>10}:  target_hit={tgt_hits}/{n} ({tgt_hits/n*100:.0f}%)  "
              f"dir={dir_hits/n*100:.0f}%  "
              f"[B:{bullish} Bear:{bearish} N:{neutral}]  "
              f"avg_range={avg_range_pct:.1f}%")

    total     = len(df)
    tgt_total = int(df["target_hit_for_tf"].sum())
    dir_total = int(df["intraday_hit_for_tf"].sum())
    print(f"\n  Overall: {tgt_total}/{total} = {tgt_total/total*100:.0f}% target_hit  "
          f"|  {dir_total}/{total} = {dir_total/total*100:.0f}% direction")

    print("\n" + "=" * 70)
    print("Accuracy by Ticker")
    print("=" * 70)
    print(f"  {'Ticker':<18} {'N':>4} {'Target%':>8} {'Dir%':>6} {'AvgRange%':>10}")
    print("  " + "-" * 52)
    for t in tickers:
        sub = df[df["ticker"] == t]
        if sub.empty:
            continue
        n        = len(sub)
        tgt_hits = int(sub["target_hit_for_tf"].sum())
        dir_hits = int(sub["intraday_hit_for_tf"].sum())
        avg_range_pct = sub.apply(
            lambda r: abs(r.get("target_price_hi", 0) - r.get("target_price_lo", 0)) /
                      r.get("entry_price", 1) * 100 if r.get("entry_price", 0) > 0 else 0,
            axis=1
        ).mean() if "target_price_hi" in sub.columns else float("nan")
        print(f"  {t:<18} {n:>4} {tgt_hits/n*100:>7.0f}% {dir_hits/n*100:>6.0f}% {avg_range_pct:>9.1f}%")


def _live_spot_check(tickers):
    """Predict each watchlist stock right now and show what the UI would display."""
    print("\n" + "=" * 70)
    print("LIVE SPOT-CHECK — what the UI shows right now")
    print("=" * 70)
    print(f"  {'Ticker':<18} {'TF':>10} {'Dir':>10} {'Conf':>7} {'Lo%':>7} {'Hi%':>7} "
          f"{'Range%':>8} {'BUY?':>6} {'Source'}")
    print("  " + "-" * 85)

    from predictor_core import predict_stock_v2, timeframe_to_dates

    results = []
    for ticker in tickers:
        for tf in ["INTRADAY", "1D", "3D"]:
            try:
                start, end = timeframe_to_dates(tf)
                pred = predict_stock_v2(
                    ticker=ticker, start_date=start, end_date=end,
                    _run_ai_forecast=True,
                )
                af = pred.get("ai_forecast") or {}
                direction  = af.get("direction") or pred.get("direction") or pred.get("predicted_direction") or "—"
                confidence = af.get("confidence") or pred.get("confidence") or "—"
                ret_lo     = af.get("predicted_return_lo") or pred.get("predicted_return_lo", 0)
                ret_hi     = af.get("predicted_return_hi") or pred.get("predicted_return_hi", 0)
                should_buy = af.get("should_buy")
                source     = af.get("source", "—")
                entry_px   = af.get("entry_price", 0)
                range_pct  = abs((ret_hi or 0) - (ret_lo or 0))
                buy_str    = "BUY" if should_buy is True else ("SKIP" if should_buy is False else "—")
                print(f"  {ticker:<18} {tf:>10} {direction:>10} {confidence:>7} "
                      f"{(ret_lo or 0):>+7.2f} {(ret_hi or 0):>+7.2f} {range_pct:>7.2f}% "
                      f"{buy_str:>6}  {source}")
                results.append({
                    "ticker": ticker, "tf": tf,
                    "direction": direction, "confidence": confidence,
                    "ret_lo": ret_lo, "ret_hi": ret_hi, "range_pct": range_pct,
                    "should_buy": should_buy, "source": source, "entry_px": entry_px,
                })
            except Exception as e:
                print(f"  {ticker:<18} {tf:>10} ERROR: {e}")
            time.sleep(2)  # light throttle between live calls

    # Range realism summary
    if results:
        import statistics
        all_ranges = [r["range_pct"] for r in results if r.get("range_pct", 0) > 0]
        if not all_ranges:
            print("\n  No AI forecasts succeeded — all predictions used fallback or NO TRADE.")
            return
        print(f"\n  Range stats: min={min(all_ranges):.2f}%  "
              f"avg={statistics.mean(all_ranges):.2f}%  "
              f"max={max(all_ranges):.2f}%")
        print(f"  Expected realistic ranges: INTRADAY ~0.5-2%, 1D ~1-4%, 3D ~2-7%")
        tiny = [r for r in results if r.get("range_pct", 99) < 0.5]
        if tiny:
            print(f"  WARNING: {len(tiny)} predictions have suspiciously tiny ranges (<0.5%):")
            for r in tiny:
                lo = r["ret_lo"] or 0
                hi = r["ret_hi"] or 0
                print(f"    {r['ticker']} {r['tf']} lo={lo:+.3f}% hi={hi:+.3f}%")
        else:
            print(f"  OK: All ranges are ≥0.5% — looks realistic.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-only", action="store_true",
                        help="Skip historical backtest; only run live spot-check")
    args = parser.parse_args()

    tickers = _get_watchlist_tickers()

    print("=" * 70)
    print("Watchlist Backtest — realistic AI ranges (tight_test=False)")
    print("=" * 70)
    print(f"Tickers : {', '.join(tickers)}")

    if not args.live_only:
        print(f"Period  : {TEST_START} → {DATA_END}  step={STEP} trading days")

        # Download data
        sc, sh, sl, sv, nc, vc = fetch_data(tickers, DATA_START, DATA_END)
        nifty_ema200, vix_slope = _vix_nifty_series(nc, vc)

        # Build date list
        all_nifty_days = nc.dropna().index
        dates = all_nifty_days[all_nifty_days >= pd.Timestamp(TEST_START)][::STEP]
        print(f"Dates   : {len(dates)}  ({[str(d.date()) for d in dates]})")
        work_items = _build_work_items(tickers, dates, sc, sh, sl, sv, nc, vc, nifty_ema200, vix_slope)
        n_tfs = 3
        print(f"Items   : {len(work_items)} LLM calls (~{len(work_items) * _PACE_SECS // 60} min at {_PACE_SECS}s/call)\n")

        if not work_items:
            print("ERROR: No valid work items.")
        else:
            csv_out = os.path.join(os.path.dirname(__file__), "ai_prompt_accuracy_watchlist.csv")
            df = run_backtest(work_items, csv_path=csv_out)
            if df is not None and not df.empty:
                _print_summary(df, tickers)
                print(f"\nSaved → {csv_out}")
                print("\n" + "=" * 70)
                print("FULL BREAKDOWN")
                print_results(df)
            else:
                print("ERROR: run_backtest returned no results.")

    _live_spot_check(tickers)


if __name__ == "__main__":
    main()
