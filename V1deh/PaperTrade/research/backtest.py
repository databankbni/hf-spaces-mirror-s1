#!/usr/bin/env python3
"""
research/backtest.py — LLM Prompt Accuracy Backtest (1D / 3D / 5D).

Uses _fast_mode=True (single LLM call per prediction, no debate). The
synthesis prompt is the same one used in production — this tests its
calibration directly.

Universe  : 6 diverse NSE stocks (mixed bullish/bearish in 2024-2025)
Dates     : 2020-01-01 → 2025-06-01, every 40 trading days
Calls     : scales with test dates × 6 tickers × 3 timeframes
Rate      : 12/min global, 1 worker
Output    : research/ai_prompt_accuracy.csv

Accuracy semantics:
    - Primary: intraday directional hit over the horizon (high/low touched anytime).
    - Secondary: intraday target-range hit using forecast target bounds.
This avoids close-only bias and validates whether predictions were reachable
at any time while the market was open.

Usage:
    python research/backtest.py                                 # run full test from historical market data
    python research/backtest.py --timeframes 3D                # run only selected timeframe(s)
    python research/backtest.py --print-only                    # re-print existing CSV
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import warnings
import threading
import time
import json
import numpy as np
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings("ignore")

from trial_run import rsi, adx_s

# ── CONFIG ─────────────────────────────────────────────────────────────────────
START      = "2020-01-01"
END        = "2025-06-01"
DATA_START = "2010-01-01"
NIFTY      = "^NSEI"
VIX_TK     = "^INDIAVIX"
STEP       = 60       # every 60 trading days → ~22 dates × 15 tickers × 3 TFs = ~990 work items
WORKERS    = 1        # single worker — avoids 429 burst; rate limiter still controls pace

# ── HOLD-OUT SPLIT ────────────────────────────────────────────────────────────
# Training window: START → TRAIN_END  (loop_backtest.py optimizes here)
# Hold-out window: HOLDOUT_START → HOLDOUT_END  (--eval flag; never used for optimization)
TRAIN_END     = "2024-12-31"
HOLDOUT_START = "2025-01-01"
HOLDOUT_END   = "2025-06-01"

TIMEFRAMES = ["INTRADAY", "1D", "3D"]   # 5D retired everywhere — no longer predicted or tested
_TF_COL    = {"INTRADAY": "ret_intraday", "1D": "ret_1d", "3D": "ret_3d"}

# 15 diverse liquid NSE stocks — 5 sectors × 3 stocks each; mix of bull/bear regimes
LLM_UNIVERSE = [
    # Banking / NBFC
    "HDFCBANK.NS",    # large-cap banking — underperformed 2024
    "ICICIBANK.NS",   # banking — strong performer 2023-2024
    "BAJFINANCE.NS",  # NBFC — volatile, both directions
    # IT
    "TCS.NS",         # IT blue-chip — mixed 2024
    "INFY.NS",        # IT — underperformed vs sector in 2024
    "WIPRO.NS",       # IT — persistent underperformer 2024
    # Energy / Industrial
    "RELIANCE.NS",    # diversified energy/telecom — mostly sideways-to-up
    "NTPC.NS",        # power — steady up-trend 2023-2024
    "LTIM.NS",        # L&T Infotech — IT/industrial cross
    # Pharma / Consumer
    "SUNPHARMA.NS",   # pharma — mixed 2024, corrections
    "DRREDDY.NS",     # pharma — volatile, both directions
    "HINDUNILVR.NS",  # FMCG — defensive, low-beta
    # Auto / Metals
    "MARUTI.NS",      # auto — strong 2023-2024 performer
    "TATASTEEL.NS",   # metals — highly cyclical, bearish in 2024
    "TITAN.NS",       # consumer durables — volatile uptrend
]

CALIBRATION_ARTIFACT = "confidence_calibration.json"
CALIBRATION_DIR = os.path.dirname(__file__)


# ── DATA ───────────────────────────────────────────────────────────────────────

def fetch_data(tickers, start, end):
    all_tk = list(set(tickers + [NIFTY, VIX_TK]))
    print(f"  Downloading {len(tickers)} tickers {start} → {end} (actual market data)…")
    raw = yf.download(all_tk, start=start, end=end, auto_adjust=True, progress=False)

    def _s(field, tk):
        try:
            s = raw[field][tk]
            return s.dropna() if isinstance(s, pd.Series) else pd.Series(dtype=float)
        except Exception:
            return pd.Series(dtype=float)

    sc = raw["Close"][tickers].copy()
    sh = raw["High"][tickers].copy()
    sl = raw["Low"][tickers].copy()
    sv = raw["Volume"][tickers].copy()
    return sc, sh, sl, sv, _s("Close", NIFTY), _s("Close", VIX_TK)


def fetch_open_series(tickers, start, end):
    """Additive companion to fetch_data() — Open prices only, keyed by ticker. Kept as a
    separate function (not a new fetch_data() return value) so the 5 existing callers of
    fetch_data() (blend_backtest.py, validate_on_trades.py, backtest_watchlist.py,
    price_hit_research.py, tight_range_backtest.py) don't need to change their unpacking."""
    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)
    return raw["Open"][tickers].copy()


def _fwd_returns(sc, date, ticker):
    try:
        c = sc[ticker].dropna()
        idx = c.index.searchsorted(date)
        p0 = c.iloc[idx]
        def _r(n):
            i = idx + n
            return (c.iloc[i] / p0 - 1) * 100 if i < len(c) else float("nan")
        return _r(1), _r(3), _r(5)
    except Exception:
        return float("nan"), float("nan"), float("nan")


def _fwd_intraday_moves(sc, sh, sl, date, ticker):
    """Return best/worst intraday move (%) over INTRADAY(same-day)/1D/3D/5D after `date`.

    INTRADAY (up0/dn0) is the entry day's own intraday swing vs its close — a daily-OHLC
    proxy for a same-session move (no 3pm cap; the live validator applies the real cap).
    """
    try:
        c = sc[ticker].dropna()
        idx = c.index.searchsorted(date)
        p0 = c.iloc[idx]

        def _moves(n):
            future_dates = c.index[idx + 1: idx + n + 1]
            if len(future_dates) < n:
                return float("nan"), float("nan")
            h_win = sh[ticker].reindex(future_dates).dropna()
            l_win = sl[ticker].reindex(future_dates).dropna()
            if h_win.empty or l_win.empty:
                return float("nan"), float("nan")
            max_up = (float(h_win.max()) / p0 - 1.0) * 100.0
            min_down = (float(l_win.min()) / p0 - 1.0) * 100.0
            return max_up, min_down

        # Same-day range: entry day's own High/Low vs its close.
        try:
            entry_day = c.index[idx]
            up0 = (float(sh[ticker].reindex([entry_day]).iloc[0]) / p0 - 1.0) * 100.0
            dn0 = (float(sl[ticker].reindex([entry_day]).iloc[0]) / p0 - 1.0) * 100.0
        except Exception:
            up0, dn0 = float("nan"), float("nan")

        up1, dn1 = _moves(1)
        up3, dn3 = _moves(3)
        up5, dn5 = _moves(5)
        return up0, dn0, up1, dn1, up3, dn3, up5, dn5
    except Exception:
        return (float("nan"),) * 8


def _entry_day_open_close(so, sc, date, ticker):
    """Genuine same-day INTRADAY direction: (Close/Open - 1)*100 of the entry day itself.

    Additive companion to _fwd_intraday_moves — that function's up0/dn0 (Close-anchored
    high/low excursion) also feeds ml_predictor's already-validated calibration and must not
    change. This is a NEW, separate signal used only for real direction-accuracy / net-P&L
    reporting (TABLE 6), since up0/dn0 can't answer "did the day finish green or red" (their
    reference price IS the day's own close, so there's no forward point to compare against).
    """
    try:
        c = sc[ticker].dropna()
        idx = c.index.searchsorted(date)
        entry_day = c.index[idx]
        o = float(so[ticker].reindex([entry_day]).iloc[0])
        cl = float(c.iloc[idx])
        if o <= 0 or pd.isna(o) or pd.isna(cl):
            return float("nan")
        return (cl / o - 1.0) * 100.0
    except Exception:
        return float("nan")


def _vix_nifty_series(nc, vc):
    return nc.ewm(span=200).mean(), vc.ewm(span=5).mean().diff()


def _simple_ml_prob(sc_tk, sv_tk, date):
    try:
        c = sc_tk.loc[:date].dropna()
        if len(c) < 200:
            return 0.5
        p = 0.5
        e20  = c.ewm(span=20).mean().iloc[-1]
        e50  = c.ewm(span=50).mean().iloc[-1]
        e200 = c.ewm(span=200).mean().iloc[-1]
        last = c.iloc[-1]
        if last > e20:  p += 0.07
        if e20  > e50:  p += 0.07
        if e50  > e200: p += 0.07
        r = rsi(c).iloc[-1]
        if r < 40:   p += 0.10
        elif r > 65: p -= 0.10
        fast = c.ewm(span=12).mean()
        slow = c.ewm(span=26).mean()
        if (fast.iloc[-1] - slow.iloc[-1]) > (fast - slow).ewm(span=9).mean().iloc[-1]:
            p += 0.07
        v = sv_tk.loc[:date].dropna()
        if len(v) >= 20 and v.iloc[-1] > 1.2 * v.rolling(20).mean().iloc[-1]:
            p += 0.04
        return float(np.clip(p, 0.3, 0.8))
    except Exception:
        return 0.5


def _compute_indicators(sc_tk, sh_tk, sl_tk, sv_tk, date, nifty_c=None):
    c = sc_tk.loc[:date].dropna()
    h = sh_tk.loc[:date].dropna()
    l = sl_tk.loc[:date].dropna()
    v = sv_tk.loc[:date].dropna()
    if len(c) < 26:
        return {}
    price = float(c.iloc[-1])
    inds  = {}
    # Relative strength vs Nifty over ~3 months (63 trading days) — same formula as
    # predictor_core.py's rs3m / ml_combiner.py's rs3m feature (the excess-of-Nifty signal that
    # ml_predictor's ML_EXCESS_LABELS is built on, validated ~10x 1D expectancy improvement over
    # raw-return labels). A structurally underperforming stock ("laggard") is a classic
    # hedge-fund-style filter: don't go long just because a laggard's own RSI/BB looks oversold.
    if nifty_c is not None:
        try:
            ni = nifty_c.loc[:date].dropna()
            if len(c) >= 63 and len(ni) >= 63:
                stock_ret = c.iloc[-1] / c.iloc[-63] - 1.0
                nifty_ret = ni.iloc[-1] / ni.iloc[-63] - 1.0
                inds["rs_3m_pct"] = round((stock_ret - nifty_ret) * 100, 2)
        except Exception:
            pass
    # All keys use production names (matching predictor_core.py / _build_context_block).
    # Legacy backtest names kept alongside so old CSV analysis still works.
    try:
        _rsi14 = round(float(rsi(c, 14).iloc[-1]), 1)
        inds["rsi14"]   = _rsi14
        inds["RSI_14"]  = _rsi14  # legacy alias
        inds["RSI_5"]   = round(float(rsi(c,  5).iloc[-1]), 1)
        inds["rsi5"]    = inds["RSI_5"]
        inds["RSI_2"]   = round(float(rsi(c,  2).iloc[-1]), 1)
        inds["rsi2"]    = inds["RSI_2"]
    except Exception:
        pass
    e20  = float(c.ewm(span=20).mean().iloc[-1])
    e50  = float(c.ewm(span=50).mean().iloc[-1])  if len(c) >= 50  else None
    e200 = float(c.ewm(span=200).mean().iloc[-1]) if len(c) >= 200 else None
    inds["ema20"] = round(e20, 2)
    inds["Price_vs_EMA20"]  = f"{'above' if price > e20  else 'below'} (EMA20=₹{e20:.2f})"
    if e50:
        inds["ema50"]          = round(e50, 2)
        inds["Price_vs_EMA50"] = f"{'above' if price > e50  else 'below'} (EMA50=₹{e50:.2f})"
    if e200:
        inds["ema200"]          = round(e200, 2)
        inds["Price_vs_EMA200"] = f"{'above' if price > e200 else 'below'} (EMA200=₹{e200:.2f})"
    try:
        fast_ema = c.ewm(span=12).mean()
        slow_ema = c.ewm(span=26).mean()
        hist = float(((fast_ema - slow_ema) - (fast_ema - slow_ema).ewm(span=9).mean()).iloc[-1])
        inds["macd_signal"]   = round(hist, 4)
        inds["MACD_histogram"] = inds["macd_signal"]  # legacy alias
    except Exception:
        pass
    try:
        if len(v) >= 20:
            _vr = round(float(v.iloc[-1] / v.rolling(20).mean().iloc[-1]), 2)
            inds["vol_ratio"]        = _vr
            inds["Volume_ratio_20D"] = _vr  # legacy alias
    except Exception:
        pass
    try:
        if len(h) >= 15 and len(l) >= 15:
            _h = h.iloc[-15:]; _l = l.iloc[-15:]; _c = c.iloc[-15:]
            tr = pd.concat([_h-_l, (_h-_c.shift(1)).abs(), (_l-_c.shift(1)).abs()], axis=1).max(axis=1)
            inds["atr14"]    = round(float(tr.mean()), 2)
            inds["ATR14 ₹"]  = inds["atr14"]  # legacy alias
    except Exception:
        pass
    try:
        if len(h) >= 15 and len(l) >= 15:
            inds["adx14"] = round(float(adx_s(h, l, c).iloc[-1]), 1)
    except Exception:
        pass
    # Extra context: 90D return and distance from 52W high
    try:
        if len(c) >= 63:
            _r90 = round((c.iloc[-1] / c.iloc[-63] - 1) * 100, 1)
            inds["return_90d"]  = _r90
            inds["Return_90D_%"] = _r90  # legacy alias
    except Exception:
        pass
    try:
        if len(c) >= 252:
            hi52 = c.iloc[-252:].max()
            inds["Dist_from_52W_High_%"] = round((c.iloc[-1] / hi52 - 1) * 100, 1)
    except Exception:
        pass
    # Short-term momentum — critical direction signals
    try:
        if len(c) >= 10:
            _r10 = round((c.iloc[-1] / c.iloc[-10] - 1) * 100, 1)
            inds["return_10d"]  = _r10
            inds["Return_10D_%"] = _r10  # legacy alias
    except Exception:
        pass
    try:
        if len(c) >= 20:
            _r20 = round((c.iloc[-1] / c.iloc[-20] - 1) * 100, 1)
            inds["return_20d"]  = _r20
            inds["Return_20D_%"] = _r20  # legacy alias
    except Exception:
        pass
    # Bollinger Band position: 0%=lower band, 100%=upper band
    try:
        if len(c) >= 20:
            sma20 = float(c.rolling(20).mean().iloc[-1])
            std20 = float(c.rolling(20).std().iloc[-1])
            bb_upper = sma20 + 2 * std20
            bb_lower = sma20 - 2 * std20
            if bb_upper > bb_lower:
                _bbp = round((price - bb_lower) / (bb_upper - bb_lower) * 100, 1)
                inds["bb_pct"]        = _bbp
                inds["BB_position_%"] = _bbp  # legacy alias
                inds["bb_upper"]      = round(bb_upper, 2)
                inds["bb_lower"]      = round(bb_lower, 2)
    except Exception:
        pass
    # Supertrend direction (10, 3) — price above line = bullish
    try:
        if len(c) >= 11 and len(h) >= 11 and len(l) >= 11:
            _period, _mult = 10, 3.0
            _tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
            _atr = _tr.rolling(_period).mean()
            _hl2 = (h + l) / 2
            _up_raw = (_hl2 + _mult * _atr).values
            _dn_raw = (_hl2 - _mult * _atr).values
            _cv = c.values
            _n = len(_cv)
            _upper, _lower = _up_raw.copy(), _dn_raw.copy()
            _dirn = 1
            for _i in range(1, _n):
                if not (pd.isna(_up_raw[_i]) or pd.isna(_dn_raw[_i])):
                    _upper[_i] = min(_up_raw[_i], _upper[_i - 1]) if _cv[_i - 1] <= _upper[_i - 1] else _up_raw[_i]
                    _lower[_i] = max(_dn_raw[_i], _lower[_i - 1]) if _cv[_i - 1] >= _lower[_i - 1] else _dn_raw[_i]
                    if   _cv[_i] > _upper[_i - 1]: _dirn = 1
                    elif _cv[_i] < _lower[_i - 1]: _dirn = -1
            inds["supertrend"] = bool(_dirn > 0)
    except Exception:
        pass
    # Consecutive up/down days
    try:
        if len(c) >= 6:
            diffs = c.iloc[-6:].diff().dropna()
            up = dn = 0
            for d in reversed(diffs.values):
                if d > 0 and dn == 0:
                    up += 1
                elif d < 0 and up == 0:
                    dn += 1
                else:
                    break
            if up >= 2:
                _streak = f"+{up} consecutive up"
                inds["consec_days"] = _streak
                inds["Consec_days"] = _streak  # legacy alias
            elif dn >= 2:
                _streak = f"-{dn} consecutive down"
                inds["consec_days"] = _streak
                inds["Consec_days"] = _streak  # legacy alias
    except Exception:
        pass
    inds["close"] = round(price, 2)
    return inds


# ── TRIGGER FLAG EVALUATION ───────────────────────────────────────────────────

def _compute_trigger_flags(inds: dict, price: float) -> dict:
    """Evaluate which synthesis-prompt triggers fired for a given indicator snapshot.

    Uses the 1D trigger conditions as the canonical set (they represent all TFs).
    Adds 9 boolean columns: trigger_T1 … trigger_T7, trigger_B1, trigger_B2.
    """
    rsi    = inds.get("rsi14", 50.0)
    bb     = inds.get("bb_pct", 50.0)
    r10    = inds.get("return_10d", 0.0)
    r20    = inds.get("return_20d", 0.0)
    macd   = inds.get("macd_signal", 0.0)
    ema50  = inds.get("ema50")
    ema200 = inds.get("ema200")

    above_ema50  = (ema50  is not None) and (price > ema50)
    above_ema200 = (ema200 is not None) and (price > ema200)

    streak = inds.get("consec_days", "")
    consec_up = 0
    if isinstance(streak, str) and streak.startswith("+"):
        try: consec_up = int(streak.split()[0].lstrip("+"))
        except Exception: pass

    # Crash/exhaustion: stock already down heavily over 10D/20D — a falling knife, not a normal
    # dip. Matches ai_forecast._apply_trigger_guardrails' crash_exhausted flag: suppresses the
    # oversold-bounce assumption behind T4/T6/T5(5D) below.
    crash_exhausted = bool(r10 < -6.0 or r20 < -8.0)
    overbought_extreme = bool(rsi > 70)

    T1 = bool(above_ema50 and macd > 0 and not overbought_extreme)
    T2 = bool(above_ema50 and r10 > 3.0 and bb < 85.0)
    T3 = bool(above_ema50 and consec_up >= 3 and r20 > 0.0)
    T4 = bool(above_ema50 and rsi < 50 and bb < 45.0 and -2.0 < r10 < 3.0 and not crash_exhausted)   # 3% ceiling + above_ema50 added 2026-07-31 (see ai_forecast.py)
    T5 = bool(r10 > 7.0 and bb < 80.0 and rsi < 65)  # RSI<65 gate added 2026-07-31 (see ai_forecast.py)
    T6 = bool(rsi < 44 and bb < 35.0 and not crash_exhausted)
    T7 = bool(above_ema50 and 2.5 <= r20 <= 5.0 and rsi < 62.0)  # floor 1.0->2.5 2026-07-31 (see ai_forecast.py)

    # B1 removed from production (overbought reversal); kept as placeholder False for CSV schema stability
    B1 = False
    B2 = bool(
        (not above_ema50)
        and macd < 0
        and r10 < -4.0
        and rsi > 42
        and bb > 40.0
    )
    # B3: sustained decline confirmed by momentum, independent of RSI/BB — catches falling
    # knives that never satisfy B2's bb>40% condition. Mirrors ai_forecast's B3 trigger.
    B3 = bool(crash_exhausted and macd < 0)

    return {
        "trigger_T1": int(T1),
        "trigger_T2": int(T2),
        "trigger_T3": int(T3),
        "trigger_T4": int(T4),
        "trigger_T5": int(T5),
        "trigger_T6": int(T6),
        "trigger_T7": int(T7),
        "trigger_B1": int(B1),
        "trigger_B2": int(B2),
        "trigger_B3": int(B3),
    }


# ── MAIN BACKTEST ──────────────────────────────────────────────────────────────

def _build_indicator_snapshots(sc, sh, sl, sv, nc, vc):
    """Build per-(date,ticker) cached features so indicators are not recomputed every run."""
    company_names = None
    from universe import get_universe
    company_names = get_universe()

    nifty_ema200, vix_slope = _vix_nifty_series(nc, vc)
    # Anchor sample dates to Nifty50 — it only has actual NSE trading days (no holidays)
    all_dates = nc.dropna().index
    test_dates = all_dates[all_dates >= START][::STEP]
    tickers = list(sc.columns)

    features = {}
    for date in test_dates:
        try:
            vix_level = float(vc.loc[:date].iloc[-1])
            nifty_v = float(nc.loc[:date].iloc[-1])
            nifty_ema_v = float(nifty_ema200.loc[:date].iloc[-1])
            nifty_ok = nifty_v > nifty_ema_v
            vix_decl = float(vix_slope.loc[:date].iloc[-1]) < 0
            macro_ok = nifty_ok and vix_level < 20
        except Exception:
            continue

        for ticker in tickers:
            try:
                c_tk = sc[ticker].dropna()
                if date not in c_tk.index:
                    continue

                r1, r3, r5 = _fwd_returns(sc, date, ticker)
                if any(pd.isna(x) for x in (r1, r3, r5)):
                    continue
                up0, dn0, up1, dn1, up3, dn3, up5, dn5 = _fwd_intraday_moves(sc, sh, sl, date, ticker)
                if any(pd.isna(x) for x in (up1, dn1, up3, dn3, up5, dn5)):
                    continue

                price = float(c_tk.loc[:date].iloc[-1])
                inds = _compute_indicators(sc[ticker], sh[ticker], sl[ticker], sv[ticker], date, nifty_c=nc)

                idx = c_tk.index.searchsorted(date, side="right")
                ohlcv = None
                try:
                    ohlcv = pd.DataFrame({
                        "High": sh[ticker].iloc[max(0, idx-20):idx].values,
                        "Low": sl[ticker].iloc[max(0, idx-20):idx].values,
                        "Close": sc[ticker].iloc[max(0, idx-20):idx].values,
                        "Volume": sv[ticker].iloc[max(0, idx-20):idx].values,
                    }).dropna()
                except Exception:
                    pass

                key = (str(date.date()), ticker)
                features[key] = {
                    "date": date,
                    "ticker": ticker,
                    "company": company_names.get(ticker, ticker.replace(".NS", "")),
                    "price": price,
                    "inds": inds,
                    "ohlcv": ohlcv,
                    "nifty_ok": nifty_ok,
                    "macro_ok": macro_ok,
                    "vix_level": vix_level,
                    "vix_decl": vix_decl,
                    "r1": r1,
                    "r3": r3,
                    "r5": r5,
                    "up0": up0,
                    "dn0": dn0,
                    "up1": up1,
                    "dn1": dn1,
                    "up3": up3,
                    "dn3": dn3,
                    "up5": up5,
                    "dn5": dn5,
                }
            except Exception as e:
                print(f"  SKIP {ticker} @ {date}: {e}")

    return features


def build_work_items(sc, sh, sl, sv, nc, vc, feature_cache: dict | None = None, so=None):
    import ai_forecast as _aif
    from universe import get_universe

    # Use ai_forecast default model chain (gpt-4.1-mini → gpt-4o → gpt-4o-mini)
    # Do not force a specific model — let the cooldown logic handle rate limits

    company_names = get_universe()
    nifty_ema200, vix_slope = _vix_nifty_series(nc, vc)

    # Anchor sample dates to Nifty50 — it only has actual NSE trading days (no holidays)
    all_dates = nc.dropna().index
    test_dates = all_dates[all_dates >= START][::STEP]
    tickers = list(sc.columns)
    n_preds = len(test_dates) * len(tickers) * len(TIMEFRAMES)

    print(f"  {len(test_dates)} dates × {len(tickers)} tickers × {len(TIMEFRAMES)} TFs"
          f" = {n_preds} predictions  ({n_preds} API calls in fast mode)")
    print(f"  {WORKERS} parallel workers, 12 calls/min global rate → ~{n_preds//12+1} min\n")

    # Build work items
    work_items = []
    for date in test_dates:
        for ticker in tickers:
            try:
                key = (str(date.date()), ticker)
                feat = feature_cache.get(key) if feature_cache else None
                if feat is None:
                    c_tk = sc[ticker].dropna()
                    if date not in c_tk.index:
                        continue
                    try:
                        vix_level = float(vc.loc[:date].iloc[-1])
                        nifty_v = float(nc.loc[:date].iloc[-1])
                        nifty_ema_v = float(nifty_ema200.loc[:date].iloc[-1])
                        nifty_ok = nifty_v > nifty_ema_v
                        vix_decl = float(vix_slope.loc[:date].iloc[-1]) < 0
                        macro_ok = nifty_ok and vix_level < 20
                    except Exception:
                        continue

                    r1, r3, r5 = _fwd_returns(sc, date, ticker)
                    if any(pd.isna(x) for x in (r1, r3, r5)):
                        continue
                    up1, dn1, up3, dn3, up5, dn5 = _fwd_intraday_moves(sc, sh, sl, date, ticker)
                    if any(pd.isna(x) for x in (up1, dn1, up3, dn3, up5, dn5)):
                        continue
                    price = float(c_tk.loc[:date].iloc[-1])
                    inds = _compute_indicators(sc[ticker], sh[ticker], sl[ticker], sv[ticker], date, nifty_c=nc)
                    company = company_names.get(ticker, ticker.replace(".NS", ""))
                    idx = c_tk.index.searchsorted(date, side="right")
                    ohlcv = None
                    try:
                        ohlcv = pd.DataFrame({
                            "High": sh[ticker].iloc[max(0, idx-20):idx].values,
                            "Low": sl[ticker].iloc[max(0, idx-20):idx].values,
                            "Close": sc[ticker].iloc[max(0, idx-20):idx].values,
                            "Volume": sv[ticker].iloc[max(0, idx-20):idx].values,
                        }).dropna()
                    except Exception:
                        pass
                else:
                    price = feat["price"]
                    inds = feat["inds"]
                    company = feat["company"]
                    ohlcv = feat["ohlcv"]
                    nifty_ok = feat["nifty_ok"]
                    macro_ok = feat["macro_ok"]
                    vix_level = feat["vix_level"]
                    vix_decl = feat["vix_decl"]
                    r1 = feat["r1"]
                    r3 = feat["r3"]
                    r5 = feat["r5"]
                    # Backward compatibility for older indicator caches.
                    if all(k in feat for k in ("up0", "dn0", "up1", "dn1", "up3", "dn3", "up5", "dn5")):
                        up0 = feat["up0"]
                        dn0 = feat["dn0"]
                        up1 = feat["up1"]
                        dn1 = feat["dn1"]
                        up3 = feat["up3"]
                        dn3 = feat["dn3"]
                        up5 = feat["up5"]
                        dn5 = feat["dn5"]
                    else:
                        up0, dn0, up1, dn1, up3, dn3, up5, dn5 = _fwd_intraday_moves(sc, sh, sl, date, ticker)
                        if any(pd.isna(x) for x in (up1, dn1, up3, dn3, up5, dn5)):
                            continue

                # ML probability is intentionally NOT cached in indicator snapshots.
                # Recompute from cached OHLCV each run so prompt/backtest logic can evolve
                # without requiring indicator-cache invalidation.
                ml_prob = _simple_ml_prob(sc[ticker], sv[ticker], date)

                # Real INTRADAY open->close direction — also NOT cached (same rationale as
                # ml_prob above), and additive: only computed when an Open series is supplied
                # (so=None for any caller that hasn't been updated, e.g. an older cached run).
                ret_intraday_real = _entry_day_open_close(so, sc, date, ticker) if so is not None else float("nan")

                for tf in TIMEFRAMES:
                    work_items.append(dict(
                        date=date, ticker=ticker, tf=tf,
                        price=price, ml_prob=ml_prob, inds=inds,
                        company=company, ohlcv=ohlcv,
                        nifty_ok=nifty_ok, macro_ok=macro_ok,
                        vix_level=vix_level, vix_decl=vix_decl,
                        r1=r1, r3=r3, r5=r5,
                        up0=up0, dn0=dn0,
                        up1=up1, dn1=dn1, up3=up3, dn3=dn3, up5=up5, dn5=dn5,
                        ret_intraday_real=ret_intraday_real,
                    ))
            except Exception as e:
                print(f"  SKIP {ticker} @ {date}: {e}")

    print(f"  {len(work_items)} work items queued")
    return sorted(work_items, key=lambda w: (str(w["date"]), w["ticker"], w["tf"]))


def run_backtest(work_items: list[dict], csv_path: str | None = None, limit_work_items: int = 0,
                 prod_like: bool = False):
    """Run the LLM prompt-accuracy backtest.

    Every prediction uses a BOUNDED per-stock LLM attempt (one pass through available cloud
    providers + a single Ollama last-resort, ~70s cap — never the old minutes-long internal
    wait loop). Skips are eliminated at the batch level by the deferred-retry rounds below:
    a stock that can't get any provider right now is re-queued and retried after a cooldown
    (with Ollama's transient backoff reset each round), while successes stream to CSV
    immediately as partial results. This is the exact anti-skip behavior we port to the
    production watchlist / top-picks path.

    prod_like is retained for API compatibility and labels the run as the production-mirroring
    path; it no longer selects a slower wait-loop (that behavior is what caused the 10-min
    per-stock hangs and is gone).
    """
    from ai_forecast import get_ai_forecast
    # Gemini/SambaNova are now first-class providers in llm_client.py's dynamic availability sort
    # (shipped 2026-07-17, see research/PRODUCTION_DELTA.md) — no separate wiring needed here.

    from experiment_features import ExperimentContextBuilder, ExperimentalConfig

    exp_builder = ExperimentContextBuilder(
        ExperimentalConfig(
            enable_alt_sentiment=os.getenv("BACKTEST_ENABLE_ALT_SENTIMENT", "0") == "1",
            enable_fundamentals=os.getenv("BACKTEST_ENABLE_FUNDAMENTALS", "0") == "1",
        )
    )

    print(f"  Mode: {'PROD-LIKE (mirrors watchlist)' if prod_like else 'CALIBRATION (historical)'} "
          f"— bounded per-stock attempt + deferred-retry rounds (anti-skip)")
    rows = []
    done = [0]
    lock = threading.Lock()
    if limit_work_items and limit_work_items > 0:
        work_items = work_items[:limit_work_items]
        print(f"  Limiting to first {len(work_items)} work items for this run")

    if not csv_path:
        csv_path = os.path.join(os.path.dirname(__file__), "ai_prompt_accuracy.csv")
    if os.path.exists(csv_path):
        os.remove(csv_path)
    header_written = [False]

    def _evaluate_intraday_hit(direction: str, price: float, target_lo: float, target_hi: float, max_up: float, min_down: float, tf_label: str, ret_for_tf: float):
        """Return (direction_hit, target_hit) for the prediction over a timeframe."""
        direction = (direction or "NEUTRAL").upper()
        try:
            target_point = (float(target_lo) + float(target_hi)) / 2.0
            req_move = (target_point / float(price) - 1.0) * 100.0
        except Exception:
            target_point = float("nan")
            req_move = float("nan")

        if direction == "BULLISH":
            direction_hit = max_up > 0
            # Gap-up fix: if stock opens above target (min_down > req_move), it has already exceeded
            # the target at market open — only require max_up >= req_move (direction fully achieved).
            target_hit = direction_hit and (not pd.isna(req_move)) and (req_move >= 0) and (max_up >= req_move)
            return direction_hit, target_hit
        if direction == "BEARISH":
            direction_hit = min_down < 0
            # Point target must be below current price and inside realized [min_down, max_up].
            target_hit = direction_hit and (not pd.isna(req_move)) and (req_move <= 0) and (min_down <= req_move <= max_up)
            return direction_hit, target_hit
        if direction == "NEUTRAL":
            # Aligned with _NEUT_RANGE stored in ai_forecast / database:
            # INTRADAY ±0.50%, 1D ±1.5%, 3D ±1.0%, 5D ±1.0%.
            neutral_caps = {"INTRADAY": 0.50, "1D": 1.5, "3D": 1.0, "5D": 1.0}
            cap = neutral_caps.get(tf_label, 1.0)
            direction_hit = (abs(ret_for_tf) <= cap)
            target_hit = (
                direction_hit
                and (not pd.isna(req_move))
                and (abs(req_move) <= cap / 3.0)
                and (min_down <= req_move <= max_up)
            )
            return direction_hit, target_hit
        return False, False

    def _graded_hit(direction: str, price: float, target_lo: float, target_hi: float,
                    max_up: float, min_down: float) -> str:
        """Graded price-hit matching production app._evaluate_price_hit:
        MIDPOINT_HIT (touched midpoint) > RANGE_HIT (entered range) > MISS.
        max_up/min_down are the window extremes as % moves from entry price."""
        try:
            d = (direction or "NEUTRAL").upper()
            lo_pct = (float(target_lo) / float(price) - 1.0) * 100.0
            hi_pct = (float(target_hi) / float(price) - 1.0) * 100.0
            mid_pct = (lo_pct + hi_pct) / 2.0
        except Exception:
            return "MISS"
        if d in ("BULLISH", "SLIGHTLY BULLISH"):
            if max_up >= mid_pct:  return "MIDPOINT_HIT"
            if max_up >= lo_pct:   return "RANGE_HIT"
            return "MISS"
        if d in ("BEARISH", "SLIGHTLY BEARISH"):
            if min_down <= mid_pct: return "MIDPOINT_HIT"
            if min_down <= hi_pct:  return "RANGE_HIT"
            return "MISS"
        # NEUTRAL: window overlaps the flat band
        if min_down <= hi_pct and max_up >= lo_pct: return "MIDPOINT_HIT"
        return "MISS"

    # Rate-pacing: enforce ≥12s between calls → ~5/min, well under Groq's 6k TPM limit.
    # Groq llama-3.3-70b: 6,000 TPM. Each call ≈ 700-1200 tokens → max ~5-8 calls/min.
    # 12s gap → 5 calls/min → ≤6,000 TPM — safe margin.
    _llm_last_call: list[float] = [0.0]
    _llm_pace_secs: float = float(os.getenv("BACKTEST_LLM_PACE_SECS", "12"))
    _llm_pace_lock = threading.Lock()

    def _throttled_sleep():
        with _llm_pace_lock:
            elapsed = time.time() - _llm_last_call[0]
            wait = max(0.0, _llm_pace_secs - elapsed)
            if wait > 0:
                time.sleep(wait)
            _llm_last_call[0] = time.time()

    def _run_one(w):
        _throttled_sleep()
        try:
            fc = get_ai_forecast(
                ticker=w["ticker"], company=w["company"], tf_label=w["tf"],
                ml={"probability": w["ml_prob"], "upgraded": w["ml_prob"] > 0.62,
                    "score": int(w["ml_prob"] * 100), "features": {}},
                nifty_ok=w["nifty_ok"], macro_ok=w["macro_ok"],
                vix_level=w["vix_level"],
                news=exp_builder.build_news_bundle(w["ticker"], w["company"]),
                current_price=w["price"], indicators=w["inds"], ohlcv_df=w["ohlcv"],
                vix_declining=w["vix_decl"],
                _fast_mode=True,               # single synthesis call — matches watchlist bulk path
                _tight_test_ranges=False,      # use AI's own predicted ranges (realistic) — matches prod
                _forecast_date=str(w["date"].date() if hasattr(w["date"], "date") else w["date"]),  # per-date cache key (backtest evaluates many historical dates in one session)
                # Anti-skip option (b): BOUNDED per-stock attempt — one pass through available cloud
                # providers + a single Ollama last-resort (~70s cap), NOT the old long internal
                # wait+retry loop (fast_fail=False) that made each stock hang for minutes. Resilience
                # comes from the round-level deferred-retry loop below, not from waiting inside the
                # call. This is the exact behavior we port to prod: never block the batch on one stock.
                _fast_fail_on_rate_limit=True,
                _enable_backtest_openrouter=True,
            )
            src = fc.get("source", "failed")
            src_provider = fc.get("source_provider") or (src.split(":", 1)[0] if ":" in src else src)
            src_model = fc.get("source_model") or (src.split(":", 1)[1] if ":" in src else "unknown")
            # INTRADAY same-day close-to-close return ≈ 0 (entry ≈ close); the swing
            # is captured by up0/dn0 for the directional/target-touch metric.
            ret_tf = {"INTRADAY": 0.0, "1D": w["r1"], "3D": w["r3"], "5D": w["r5"]}[w["tf"]]
            max_up_tf = {"INTRADAY": w["up0"], "1D": w["up1"], "3D": w["up3"], "5D": w["up5"]}[w["tf"]]
            min_down_tf = {"INTRADAY": w["dn0"], "1D": w["dn1"], "3D": w["dn3"], "5D": w["dn5"]}[w["tf"]]
            direction_hit, target_hit = _evaluate_intraday_hit(
                fc.get("direction", "NEUTRAL"),
                w["price"],
                fc.get("target_price_lo", 0.0),
                fc.get("target_price_hi", 0.0),
                max_up_tf,
                min_down_tf,
                w["tf"],
                ret_tf,
            )
            hit_grade = _graded_hit(
                fc.get("direction", "NEUTRAL"), w["price"],
                fc.get("target_price_lo", 0.0), fc.get("target_price_hi", 0.0),
                max_up_tf, min_down_tf,
            )
            trigger_flags = _compute_trigger_flags(w.get("inds", {}), w["price"])
            _row = {
                "date":             str(w["date"].date()),
                "ticker":           w["ticker"],
                "timeframe":        w["tf"],
                "confidence":       fc.get("confidence", "LOW"),
                "direction":        fc.get("direction", "NEUTRAL"),
                "matched_strategy": fc.get("matched_strategy"),
                "ml_prob":          round(w["ml_prob"], 3),
                "vix":              round(w["vix_level"], 1),
                "nifty_ok":         w["nifty_ok"],
                "source":           src,
                "source_provider":  src_provider,
                "source_model":     src_model,
                "entry_price":      round(w["price"], 3),
                "target_price_lo":  round(float(fc.get("target_price_lo", 0.0) or 0.0), 3),
                "target_price_hi":  round(float(fc.get("target_price_hi", 0.0) or 0.0), 3),
                "ret_intraday":     0.0,
                "ret_intraday_real": round(w["ret_intraday_real"], 3) if not pd.isna(w.get("ret_intraday_real", float("nan"))) else "",
                "ret_1d":           round(w["r1"], 3),
                "ret_3d":           round(w["r3"], 3),
                "ret_5d":           round(w["r5"], 3),
                "ret_for_tf":       round(ret_tf, 3),
                "max_up_0d":        round(w["up0"], 3),
                "min_down_0d":      round(w["dn0"], 3),
                "max_up_1d":        round(w["up1"], 3),
                "min_down_1d":      round(w["dn1"], 3),
                "max_up_3d":        round(w["up3"], 3),
                "min_down_3d":      round(w["dn3"], 3),
                "max_up_5d":        round(w["up5"], 3),
                "min_down_5d":      round(w["dn5"], 3),
                "max_up_for_tf":    round(max_up_tf, 3),
                "min_down_for_tf":  round(min_down_tf, 3),
                "intraday_hit_for_tf": int(direction_hit),
                "target_hit_for_tf": int(target_hit),
                "hit_grade": hit_grade,
                "midpoint_hit_for_tf": int(hit_grade == "MIDPOINT_HIT"),
                "graded_hit_for_tf": int(hit_grade in ("MIDPOINT_HIT", "RANGE_HIT")),
                **trigger_flags,
            }
            return (_row, w)
        except Exception as e:
            # AI-unavailable / transient provider failure → return the work item so the caller
            # DEFERS + retries it in a later round instead of hard-skipping on the first miss.
            # (This is the backtest prototype of the production "never AI-unavailable" fix.)
            _msg = str(e)
            if "unavailable" not in _msg.lower():
                print(f"  data-error {w['ticker']} @ {w['date']} [{w['tf']}]: {_msg[:80]}")
            return (None, w)

    # ── Deferred-retry rounds (AI-only skip fix) ──────────────────────────────
    # A prediction that can't get ANY provider right now is NOT hard-skipped — it is deferred
    # and retried in a later round after a cooldown that lets per-minute cloud quota reset and
    # Ollama's inference-backoff clear. Successes stream to CSV immediately (partial results);
    # only items that fail EVERY round are finally skipped. This mirrors the production fix:
    # show the watchlist/top-picks cards that succeeded, re-queue the rest, fill in as capacity
    # returns — instead of blocking the whole batch and forcing a full retry.
    _MAX_ROUNDS = int(os.getenv("BACKTEST_MAX_RETRY_ROUNDS", "3"))
    _ROUND_COOLDOWN = float(os.getenv("BACKTEST_RETRY_COOLDOWN_SECS", "90"))
    _total = len(work_items)
    pending = list(work_items)
    for _round in range(_MAX_ROUNDS):
        if not pending:
            break
        if _round > 0:
            print(f"  ↻ Deferred-retry round {_round}/{_MAX_ROUNDS - 1}: {len(pending)} prediction(s) "
                  f"still need an AI forecast — waiting {_ROUND_COOLDOWN:.0f}s for provider quota / "
                  f"Ollama backoff to recover…")
            time.sleep(_ROUND_COOLDOWN)
            # Give Ollama a genuine fresh chance this round: clear its transient inference-backoff
            # + health cache so a stock deferred while Ollama was mid-backoff is actually re-tried
            # (otherwise a 120s backoff outlives a 90s cooldown and the stock defers forever).
            # Cloud daily_exhausted flags are untouched — only real midnight-IST reset clears those.
            try:
                from llm_client import reset_ollama_state
                reset_ollama_state()
            except Exception:
                pass
        _failed = []
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(_run_one, w) for w in pending]
            for fut in as_completed(futures):
                result, w = fut.result()
                with lock:
                    if result:
                        rows.append(result)
                        pd.DataFrame([result]).to_csv(
                            csv_path, mode="a", index=False, header=not header_written[0],
                        )
                        header_written[0] = True
                    else:
                        _failed.append(w)
                    done[0] += 1
                    if done[0] % 5 == 0:
                        print(f"  [round {_round}] {len(rows)}/{_total} ok, "
                              f"{len(_failed)} deferred so far…")
        pending = _failed

    if pending:
        print(f"  ⚠ {len(pending)}/{_total} prediction(s) could not get an AI forecast after "
              f"{_MAX_ROUNDS} rounds — skipped (all partial results kept).")
    else:
        print(f"  ✓ All {_total} predictions got an AI forecast (0 skips).")

    if not rows:
        print("  No rows collected.")
        return None

    df = pd.DataFrame(rows)
    print(f"\n  Stream-saved {len(df)} rows → {csv_path}")
    return df


# ── ACCURACY REPORT ────────────────────────────────────────────────────────────

def print_results(df: pd.DataFrame) -> dict:
    """Print tables and return accuracy dict keyed by (tf, direction)."""
    acc = {}

    _sep()
    print("TABLE 1 — Directional Intraday Direction-Hit Accuracy per Timeframe (target ≥90%)")
    _sep()
    print(f"{'TF':<5} {'N_Dir':>7} {'DirHit':>10} {'BullHit':>10} {'BearHit':>10} {'TgtHit':>9}  Status")
    _sep("-")
    all_met = True
    for tf in TIMEFRAMES:
        col  = _TF_COL[tf]
        sub = df[(df["timeframe"] == tf) & (df["direction"].isin(["BULLISH", "BEARISH"]))]
        bull = sub[sub["direction"] == "BULLISH"]
        bear = sub[sub["direction"] == "BEARISH"]
        if len(sub) < 3:
            print(f"{tf:<5} {len(sub):>7}  {'n/a':>10}  {'n/a':>10}  {'n/a':>10}  {'n/a':>9}  ✗ need ≥3 samples")
            acc[(tf, "ALL")] = float("nan")
            all_met = False
            continue

        dir_hit = sub["intraday_hit_for_tf"].mean() * 100
        bull_hit = _dacc(bull, "BULLISH", col) if len(bull) >= 3 else float("nan")
        bear_hit = _dacc(bear, "BEARISH", col) if len(bear) >= 3 else float("nan")
        tgt = sub["target_hit_for_tf"].mean() * 100 if len(sub) else float("nan")
        # Primary success criterion for this loop is target-hit, not direction-hit.
        ok_tgt = tgt >= 90.0
        if not ok_tgt:
            all_met = False

        acc[(tf, "ALL")] = dir_hit
        acc[(tf, "BULLISH")] = bull_hit
        acc[(tf, "BEARISH")] = bear_hit
        flag = "✓ Tgt MET" if ok_tgt else "✗ Tgt<90%"
        bull_txt = f"{bull_hit:>9.1f}%" if not np.isnan(bull_hit) else f"{'n/a':>10}"
        bear_txt = f"{bear_hit:>9.1f}%" if not np.isnan(bear_hit) else f"{'n/a':>10}"
        print(f"{tf:<5} {len(sub):>7} {dir_hit:>9.1f}% {bull_txt} {bear_txt} {tgt:>8.1f}%  {flag}")

    _sep()
    print("TABLE 2 — Direction Distribution and Confidence Mix")
    _sep()
    for tf in TIMEFRAMES:
        sub = df[df["timeframe"] == tf]
        n   = len(sub)
        b   = (sub["direction"] == "BULLISH").sum()
        br  = (sub["direction"] == "BEARISH").sum()
        nt  = (sub["direction"] == "NEUTRAL").sum()
        hi  = (sub["confidence"] == "HIGH").sum()
        print(f"  {tf}: BULL={b}({b/n*100:.0f}%)  BEAR={br}({br/n*100:.0f}%)"
              f"  NEUT={nt}({nt/n*100:.0f}%)  HIGH={hi}({hi/n*100:.0f}%)")

    _sep()
    print("TABLE 3 — Full calibration (all confidence levels, intraday hit metric)")
    _sep()
    print(f"{'TF':<5} {'Conf':<8} {'Dir':<9} {'N':>5} {'HitAcc':>10} {'TgtHit':>9}")
    _sep("-")
    for tf in TIMEFRAMES:
        col = _TF_COL[tf]
        for conf in ["HIGH", "MEDIUM", "LOW"]:
            for dirn in ["BULLISH", "BEARISH", "NEUTRAL"]:
                s = df[(df["timeframe"]==tf) & (df["confidence"]==conf) & (df["direction"]==dirn)]
                if len(s) < 3:
                    continue
                a   = _dacc(s, dirn, col)
                tgt = s["target_hit_for_tf"].mean() * 100
                print(f"{tf:<5} {conf:<8} {dirn:<9} {len(s):>5} {a:>9.1f}% {tgt:>8.1f}%")

    _sep()
    status = "✓ ALL TIMEFRAMES ≥90% — TARGET MET" if all_met else "✗ Target not yet met"
    print(f"  OVERALL: {status}")
    if "source" in df.columns:
        n_heur = (df["source"] == "heuristic").sum()
        n_unavail = (df["source"] == "ai_unavailable").sum()
        n_failed = (df["source"] == "failed").sum()
        n_llm  = len(df) - n_heur - n_unavail - n_failed
        print(f"  LLM predictions: {n_llm}  |  Heuristic: {n_heur}  |  AI unavailable: {n_unavail}  |  Failed: {n_failed}")
        if "source_provider" in df.columns:
            provider_counts = df["source_provider"].value_counts(dropna=False)
            print("  Provider mix:")
            for k, v in provider_counts.items():
                print(f"    - {k}: {v}")

    # TABLE 4 — Per-trigger accuracy breakdown (only if columns present in CSV)
    _trigger_cols = [c for c in ["trigger_T1","trigger_T2","trigger_T3","trigger_T4","trigger_T5","trigger_T6","trigger_T7","trigger_B2"] if c in df.columns]
    if _trigger_cols:
        _sep()
        print("TABLE 4 — Per-Trigger Accuracy Breakdown (how often predictions that fired each trigger were correct)")
        _sep()
        print(f"  {'Trigger':<12} {'Fired':>7} {'Correct':>9} {'HitRate':>9}  Direction")
        _sep("-")
        _dir_df = df[df["direction"].isin(["BULLISH", "BEARISH"])].copy()
        _bull_triggers = ["trigger_T1","trigger_T2","trigger_T3","trigger_T4","trigger_T5","trigger_T6","trigger_T7"]
        _bear_triggers = ["trigger_B2"]
        for col in _trigger_cols:
            fired = _dir_df[_dir_df[col] == 1]
            if len(fired) < 3:
                continue
            n_fired = len(fired)
            n_correct = int(fired["intraday_hit_for_tf"].sum())
            rate = n_correct / n_fired * 100
            dirn = "BULLISH" if col in _bull_triggers else "BEARISH"
            print(f"  {col:<12} {n_fired:>7} {n_correct:>9} {rate:>8.1f}%  {dirn}")

    # TABLE 5 — Per-regime accuracy slice (requires nifty_ok and vix columns)
    if "nifty_ok" in df.columns and "vix" in df.columns:
        _sep()
        print("TABLE 5 — Per-Regime Accuracy Slice (directional predictions only)")
        _sep()
        print(f"  {'Regime':<22} {'N':>6} {'DirHit':>9} {'TgtHit':>9}")
        _sep("-")
        _dir_df2 = df[df["direction"].isin(["BULLISH","BEARISH"])].copy()
        _dir_df2["vix_band"] = pd.cut(_dir_df2["vix"], bins=[0, 15, 20, 100], labels=["VIX<15","VIX 15-20","VIX>20"])
        for regime_label, mask in [
            ("Nifty Bull (above EMA200)", _dir_df2["nifty_ok"] == True),
            ("Nifty Bear (below EMA200)", _dir_df2["nifty_ok"] == False),
        ]:
            sub = _dir_df2[mask]
            if len(sub) < 3:
                continue
            dh = sub["intraday_hit_for_tf"].mean() * 100
            th = sub["target_hit_for_tf"].mean() * 100
            print(f"  {regime_label:<22} {len(sub):>6} {dh:>8.1f}% {th:>8.1f}%")
        for band in ["VIX<15","VIX 15-20","VIX>20"]:
            sub = _dir_df2[_dir_df2["vix_band"] == band]
            if len(sub) < 3:
                continue
            dh = sub["intraday_hit_for_tf"].mean() * 100
            th = sub["target_hit_for_tf"].mean() * 100
            print(f"  {band:<22} {len(sub):>6} {dh:>8.1f}% {th:>8.1f}%")

    # TABLE 6 — Real direction accuracy + net P&L (INTRADAY/1D only — the metric that actually
    # matters. TABLE 1-5 above all grade "did price touch the predicted band", which a low,
    # deliberately-easy-to-reach near-bound can win regardless of whether the direction call has
    # any real edge. This table answers "would trading this call have made money" instead.
    _sep()
    print("TABLE 6 — Real Direction Accuracy + Net P&L (INTRADAY/1D only, NOT band-touch)")
    _sep()
    from costs import cost_pct_for_timeframe

    def _real_move(row):
        if row["timeframe"] == "INTRADAY":
            try:
                return float(row.get("ret_intraday_real", float("nan")))
            except (TypeError, ValueError):
                return float("nan")
        return row.get("ret_for_tf", float("nan"))

    _pnl_df = df[df["timeframe"].isin(["INTRADAY", "1D"])].copy()
    _pnl_df["real_move"] = _pnl_df.apply(_real_move, axis=1)
    _dir_pnl = _pnl_df[_pnl_df["direction"].isin(["BULLISH", "BEARISH"]) & _pnl_df["real_move"].notna()].copy()

    if _dir_pnl.empty:
        print("  (no rows with a real realized move yet — re-run backtest.py to populate ret_intraday_real for INTRADAY)")
    else:
        _dir_pnl["dir_correct"] = np.where(
            _dir_pnl["direction"] == "BULLISH", _dir_pnl["real_move"] > 0, _dir_pnl["real_move"] < 0
        )
        _gross = np.where(_dir_pnl["direction"] == "BULLISH", _dir_pnl["real_move"], -_dir_pnl["real_move"])
        _dir_pnl["net_pnl"] = _gross - _dir_pnl["timeframe"].map(cost_pct_for_timeframe)

        print(f"  {'TF':<9} {'Dir':<9} {'N':>5} {'DirAcc':>9} {'AvgP&L':>9} {'WinRate':>9}")
        _sep("-")
        for tf in ["INTRADAY", "1D"]:
            for dirn in ["BULLISH", "BEARISH"]:
                s = _dir_pnl[(_dir_pnl["timeframe"] == tf) & (_dir_pnl["direction"] == dirn)]
                if len(s) < 3:
                    continue
                da = s["dir_correct"].mean() * 100
                pnl = s["net_pnl"].mean()
                wr = (s["net_pnl"] > 0).mean() * 100
                print(f"  {tf:<9} {dirn:<9} {len(s):>5} {da:>8.1f}% {pnl:>+8.3f}% {wr:>8.1f}%")

        print("\n  By confidence:")
        for tf in ["INTRADAY", "1D"]:
            for conf in ["HIGH", "MEDIUM", "LOW"]:
                s = _dir_pnl[(_dir_pnl["timeframe"] == tf) & (_dir_pnl["confidence"] == conf)]
                if len(s) < 3:
                    continue
                da = s["dir_correct"].mean() * 100
                pnl = s["net_pnl"].mean()
                print(f"    {tf:<9} {conf:<8} n={len(s):>4}  DirAcc={da:.1f}%  AvgP&L={pnl:+.3f}%")

    _write_calibration_artifact(df)
    _sep()
    return acc


def _write_calibration_artifact(df: pd.DataFrame) -> None:
    """Write a compact calibration snapshot for iteration-to-iteration tuning."""
    out = {
        "generated_rows": int(len(df)),
        "timeframes": {},
    }
    for tf in TIMEFRAMES:
        sub = df[df["timeframe"] == tf]
        if sub.empty:
            continue
        hi = sub[sub["confidence"] == "HIGH"]
        med = sub[sub["confidence"] == "MEDIUM"]
        out["timeframes"][tf] = {
            "n_total": int(len(sub)),
            "high_rate_pct": round(len(hi) / len(sub) * 100, 1),
            "high_hit_pct": round(hi["intraday_hit_for_tf"].mean() * 100, 1) if len(hi) else None,
            "medium_hit_pct": round(med["intraday_hit_for_tf"].mean() * 100, 1) if len(med) else None,
            "recommendation": (
                "promote_medium_to_high" if len(hi) < 8 and len(med) >= 10 and med["intraday_hit_for_tf"].mean() >= 0.75
                else "tighten_high_thresholds" if len(hi) >= 8 and hi["intraday_hit_for_tf"].mean() < 0.75
                else "hold"
            ),
        }

    try:
        os.makedirs(CALIBRATION_DIR, exist_ok=True)
        path = os.path.join(CALIBRATION_DIR, CALIBRATION_ARTIFACT)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        print(f"  Calibration artifact written -> {path}")
    except Exception as e:
        print(f"  Calibration artifact write failed: {e}")


def _dacc(sub, direction, col):
    if direction == "BULLISH": return sub["intraday_hit_for_tf"].mean() * 100
    if direction == "BEARISH": return sub["intraday_hit_for_tf"].mean() * 100
    neutral_caps = {"ret_intraday": 0.9, "ret_1d": 1.2, "ret_3d": 3.0, "ret_5d": 3.0}
    cap = neutral_caps.get(col, 1.0)
    return (sub[col].abs() <= cap).mean() * 100

def _sep(c="═", w=78):
    print(c * w)


# ── ENTRY POINT ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--print-only", action="store_true")
    p.add_argument("--timeframes", nargs="+", choices=TIMEFRAMES, help="Run only selected timeframe(s)")
    p.add_argument("--csv-out", default=os.path.join(os.path.dirname(__file__), "ai_prompt_accuracy.csv"), help="Output CSV path")
    p.add_argument("--limit-work-items", type=int, default=0, help="Run only first N work items (quick smoke runs)")
    p.add_argument("--eval", action="store_true",
                   help=f"Run on hold-out dates only ({HOLDOUT_START} → {HOLDOUT_END}) — never used for prompt optimization")
    p.add_argument("--start", default=None, help="Override start date (YYYY-MM-DD)")
    p.add_argument("--end",   default=None, help="Override end date (YYYY-MM-DD)")
    args = p.parse_args()

    csv_path = args.csv_out

    # Resolve date range
    if args.eval:
        _run_start = HOLDOUT_START
        _run_end   = HOLDOUT_END
        _eval_csv  = csv_path.replace(".csv", "_holdout_eval.csv")
        csv_path   = _eval_csv
        print(f"  *** HOLD-OUT EVAL MODE: {_run_start} → {_run_end} ***")
        print(f"  Output: {csv_path}")
    else:
        _run_start = args.start or START
        _run_end   = args.end   or END

    if args.print_only:
        if not os.path.exists(csv_path):
            print("No CSV found."); sys.exit(1)
        df = pd.read_csv(csv_path)
        if "timeframe" not in df.columns:
            print("CSV is from old format — re-run without --print-only"); sys.exit(1)
        print_results(df)
    else:
        _sep()
        mode_label = "HOLD-OUT EVAL" if args.eval else "TRAINING"
        print(f"LLM Backtest [{mode_label}] — {_run_start} → {_run_end}  |  fast mode  |  actual NSE data")
        _sep()

        # Temporarily override module-level START/END so build_work_items uses the right range
        _g = globals()
        _orig_start, _orig_end = _g["START"], _g["END"]
        _g["START"] = _run_start
        _g["END"]   = _run_end

        sc, sh, sl, sv, nc, vc = fetch_data(LLM_UNIVERSE, DATA_START, _run_end)
        so = fetch_open_series(LLM_UNIVERSE, DATA_START, _run_end)
        indicator_cache = _build_indicator_snapshots(sc, sh, sl, sv, nc, vc)
        work_items = build_work_items(sc, sh, sl, sv, nc, vc, feature_cache=indicator_cache, so=so)

        _g["START"] = _orig_start
        _g["END"]   = _orig_end

        if args.timeframes:
            selected = set(args.timeframes)
            work_items = [item for item in work_items if item["tf"] in selected]

        df = run_backtest(work_items, csv_path=csv_path, limit_work_items=args.limit_work_items)
        if df is not None:
            print_results(df)

    print("\nDone.")
