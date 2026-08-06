"""
target_backtest.py — Verify price target hit rates on NSE 5-year historical data.

Tests:
  1. ATR containment: % of days actual H-L range ⊂ ±N×ATR (N=1.0, 1.5, 2.0)
  2. Camarilla touch: % of next sessions touching R1/R2/R3/S1/S2/S3
  3. Strategy-filtered R2/R3 touch: when strategy signal fires
  4. PDH/PDL touch: prior day H/L touched next session

Outputs verified hit rates → used to calibrate achievable_pct in price_targets.py.
"""
import yfinance as yf
import pandas as pd
import numpy as np
from tickers import TICKERS_NSE, TICKERS_BSE

SEP = "=" * 70


# ── DATA LOADING ─────────────────────────────────────────────────────────────

def _load_data():
    tickers = list(dict.fromkeys(TICKERS_NSE + TICKERS_BSE))[:150]   # 150 liquid for speed
    print(f"Downloading {len(tickers)} tickers (5 years)...")
    raw = yf.download(tickers, start="2019-01-01", end="2024-01-01",
                      auto_adjust=True, progress=False)
    sc = raw["Close"].dropna(axis=1, thresh=500)
    sh = raw["High"].reindex(columns=sc.columns)
    sl = raw["Low"].reindex(columns=sc.columns)
    print(f"  {len(sc.columns)} tickers with sufficient data")
    return sc, sh, sl


# ── TEST 1: ATR CONTAINMENT ───────────────────────────────────────────────────

def test_atr_containment(sc: pd.DataFrame, sh: pd.DataFrame, sl: pd.DataFrame) -> dict:
    """
    For each day, compute ATR14 from prior 14 days.
    Check if actual H-L range fits within ±N×ATR (measured from prior close).
    """
    print(f"\n{SEP}")
    print("  TEST 1 — ATR Range Containment")
    print(SEP)

    results = {1.0: [], 1.5: [], 2.0: []}

    for tk in sc.columns:
        c  = sc[tk].dropna()
        h  = sh[tk].reindex(c.index).ffill()
        lo = sl[tk].reindex(c.index).ffill()
        if len(c) < 30:
            continue
        tr  = pd.concat([h - lo, (h - c.shift()).abs(), (lo - c.shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().shift(1)   # prior day's ATR14

        # For each bar: does the actual H-L range fit within ±N×ATR from prior close?
        prior_c = c.shift(1)
        for mult in results:
            upper = prior_c + mult * atr
            lower = prior_c - mult * atr
            contained = (h <= upper) & (lo >= lower)
            results[mult].extend(contained.dropna().tolist())

    print(f"  {'Multiplier':>12} {'Hit Rate':>10} {'N':>8}")
    print(f"  {'───────────':>12} {'────────':>10} {'──────':>8}")
    out = {}
    for mult, vals in results.items():
        rate = np.mean(vals) * 100
        out[f"atr_{mult}x"] = round(rate, 1)
        print(f"  ±{mult:.1f}× ATR14  {rate:>8.1f}%  {len(vals):>8,}")
    return out


# ── TEST 2: CAMARILLA TOUCH RATE ─────────────────────────────────────────────

def test_camarilla_touch(
    sc: pd.DataFrame, sh: pd.DataFrame, sl: pd.DataFrame,
    levels: list | None = None,
) -> dict:
    """
    For each bar, compute Camarilla levels from prior day's OHLC.
    Check if next session touches each level (H >= R or L <= S).
    """
    if levels is None:
        levels = ["R1", "R2", "R3", "S1", "S2", "S3"]

    print(f"\n{SEP}")
    print("  TEST 2 — Camarilla Pivot Touch Rates (next session)")
    print(SEP)

    counts = {lvl: {"hit": 0, "total": 0} for lvl in levels}
    factor = 1.0714

    for tk in sc.columns:
        c  = sc[tk].dropna()
        h  = sh[tk].reindex(c.index).ffill()
        lo = sl[tk].reindex(c.index).ffill()
        if len(c) < 5:
            continue

        # Shift by 1: compute levels from yesterday's OHLC
        prev_h = h.shift(1); prev_l = lo.shift(1); prev_c = c.shift(1)
        rng = prev_h - prev_l

        level_vals = {
            "R1": prev_c + factor * rng * 0.1,
            "R2": prev_c + factor * rng * 0.2,
            "R3": prev_c + factor * rng * 0.3,
            "S1": prev_c - factor * rng * 0.1,
            "S2": prev_c - factor * rng * 0.2,
            "S3": prev_c - factor * rng * 0.3,
        }

        valid = rng.dropna().index
        for lvl in levels:
            lv = level_vals[lvl].reindex(valid)
            # Bullish levels: touched when next session High >= level
            if lvl.startswith("R"):
                touched = h.reindex(valid) >= lv
            else:
                touched = lo.reindex(valid) <= lv
            mask = touched.dropna()
            counts[lvl]["hit"]   += int(mask.sum())
            counts[lvl]["total"] += len(mask)

    print(f"  {'Level':>6} {'Hit Rate':>10} {'N':>8}")
    print(f"  {'─────':>6} {'────────':>10} {'──────':>8}")
    out = {}
    for lvl in levels:
        d = counts[lvl]
        rate = d["hit"] / d["total"] * 100 if d["total"] > 0 else 0
        out[f"cam_{lvl}"] = round(rate, 1)
        print(f"  {lvl:>6}  {rate:>8.1f}%  {d['total']:>8,}")
    return out


# ── TEST 3: STRATEGY-FILTERED R3 TOUCH ───────────────────────────────────────

def test_strategy_filtered_touch(
    sc: pd.DataFrame, sh: pd.DataFrame, sl: pd.DataFrame,
    days_fwd: int = 3,
) -> dict:
    """
    When a bullish RSI oversold signal fires (proxy for HIGH strategy),
    does the stock touch Camarilla R3 within `days_fwd` sessions?
    Uses RSI<35 + SMA200 as a simple HIGH-strategy proxy.
    """
    from trial_run import rsi

    print(f"\n{SEP}")
    print(f"  TEST 3 — Strategy-Filtered R3 Touch (within {days_fwd}D)")
    print(SEP)

    hit = total = 0
    factor = 1.0714

    for tk in sc.columns:
        c  = sc[tk].dropna()
        h  = sh[tk].reindex(c.index).ffill()
        lo = sl[tk].reindex(c.index).ffill()
        if len(c) < 210:
            continue
        rsi14 = rsi(c)
        sma200 = c.rolling(200).mean()
        # Proxy signal: RSI oversold bounce near SMA200 support
        signal = (rsi14 < 35) & (c > sma200 * 0.97) & (rsi14 > rsi14.shift(1))
        signal_dates = c.index[signal.fillna(False)]

        prev_h = h.shift(1); prev_l = lo.shift(1); prev_c = c.shift(1)
        rng = prev_h - prev_l
        r3 = prev_c + factor * rng * 0.3

        c_arr  = c.values
        h_arr  = h.values
        r3_arr = r3.values
        idx_map = {ts: i for i, ts in enumerate(c.index)}

        for d in signal_dates:
            i = idx_map.get(d)
            if i is None or i + days_fwd >= len(c_arr):
                continue
            target = r3_arr[i]
            if np.isnan(target):
                continue
            touched = any(h_arr[i+1:i+1+days_fwd] >= target)
            hit   += int(touched)
            total += 1

    rate = hit / total * 100 if total > 0 else 0
    print(f"  Strategy signal → R3 touch within {days_fwd}D: {rate:.1f}% (N={total:,})")
    return {"strategy_r3_touch": round(rate, 1), "n": total}


# ── TEST 4: PDH/PDL TOUCH ────────────────────────────────────────────────────

def test_pdh_pdl_touch(sc: pd.DataFrame, sh: pd.DataFrame, sl: pd.DataFrame) -> dict:
    """Prior Day High (PDH) and Prior Day Low (PDL) touch rates next session."""
    print(f"\n{SEP}")
    print("  TEST 4 — Prior Day High / Low Touch Rate (next session)")
    print(SEP)

    pdh_hits = pdh_total = 0
    pdl_hits = pdl_total = 0

    for tk in sc.columns:
        c  = sc[tk].dropna()
        h  = sh[tk].reindex(c.index).ffill()
        lo = sl[tk].reindex(c.index).ffill()
        if len(c) < 5:
            continue
        pdh = h.shift(1)
        pdl = lo.shift(1)
        next_h = h
        next_l = lo
        valid = pdh.dropna().index
        pdh_hits  += int((next_h.reindex(valid) >= pdh.reindex(valid)).sum())
        pdh_total += len(valid)
        pdl_hits  += int((next_l.reindex(valid) <= pdl.reindex(valid)).sum())
        pdl_total += len(valid)

    pdh_rate = pdh_hits / pdh_total * 100 if pdh_total > 0 else 0
    pdl_rate = pdl_hits / pdl_total * 100 if pdl_total > 0 else 0
    print(f"  PDH touched next session: {pdh_rate:.1f}% (N={pdh_total:,})")
    print(f"  PDL touched next session: {pdl_rate:.1f}% (N={pdl_total:,})")
    return {"pdh_touch": round(pdh_rate, 1), "pdl_touch": round(pdl_rate, 1)}


# ── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\nTarget Backtest — NSE 5-Year Hit Rate Verification")
    print(SEP)
    sc, sh, sl = _load_data()

    r1 = test_atr_containment(sc, sh, sl)
    r2 = test_camarilla_touch(sc, sh, sl)
    r3 = test_strategy_filtered_touch(sc, sh, sl, days_fwd=3)
    r4 = test_pdh_pdl_touch(sc, sh, sl)

    all_results = {**r1, **r2, **r3, **r4}
    print(f"\n{SEP}")
    print("  SUMMARY — Verified Hit Rates (use for achievable_pct in price_targets.py)")
    print(SEP)
    for k, v in all_results.items():
        if isinstance(v, (int, float)):
            print(f"  {k:<30} {v:.1f}%")
