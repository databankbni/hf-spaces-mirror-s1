#!/usr/bin/env python3
"""
predictor_core.py — Unified Indian equity prediction engine (v2).

Integrates:
  • S1/S2/S3/MFS/NIRA/PED/SUPER signal generators (from trial_run.py)
  • ML feature scoring                     (from ml_combiner.py)
  • MacroContext gates                     (from macro_context.py)
  • Earnings calendar blackout             (yfinance + trial_run.build_earnings_blackout)
  • AI news sentiment                      (news_sentiment.py → Claude Haiku)
  • Hard VIX / Nifty EMA200 enforcement   (no longer advisory only)

Public API:
  predict_stock_v2(ticker, start_date, end_date) → dict
  rank_stocks_v2(start_date, end_date, universe, capital)  → dict
  timeframe_to_dates(tf)  → (start_date, end_date)
"""

from __future__ import annotations
import sys, os, warnings, math, time, logging, threading
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from concurrent.futures import ThreadPoolExecutor, as_completed


def _sf(v, d: int = 2, fallback=None):
    """Round float safely; return fallback if value is NaN or Inf."""
    try:
        r = round(float(v), d)
        return r if math.isfinite(r) else fallback
    except (TypeError, ValueError):
        return fallback


def _fn(v, default: float = 0.0) -> float:
    """Return v if finite, otherwise default (used to keep NaN out of sums)."""
    try:
        f = float(v)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta, date as _date_cls
from typing import Optional

# ── MULTI-SOURCE DATA FETCHER ────────────────────────────────────────────────
from data_sources import fetch_ohlcv, fetch_market_data, get_cached_ohlcv, fetch_live_price, update_cached_ohlcv

# ── REQUEST CONTEXT (for tracking data merges + validation) ───────────────────
from request_context import RequestContext

# ── STRATEGY SIGNAL GENERATORS (from trial_run.py) ───────────────────────────
from trial_run import (
    rsi, atr, obv, adx_s, macd_h,
    gen_s1, gen_s2, gen_s3, gen_mfs, gen_nira, gen_ped, gen_supertrend,
    gen_s4, gen_s5, gen_s6,
    gen_s4v2, gen_s5v2, gen_s6v2,
    gen_s7, gen_s8, gen_s9, gen_s10, gen_s11,
    gen_s_capflow, gen_s_confluence_trio, gen_s_seasonal,
    gen_s12, gen_s13, gen_s14, gen_s15, gen_s16,
    gen_s17, gen_s18, gen_s19, gen_s20,
)

# ── ML FEATURE FUNCTIONS (from ml_combiner.py) ───────────────────────────────
from ml_combiner import bollinger_position, ema_stack_score, shadow_flag

# ── MACRO CONTEXT (from macro_context.py) ────────────────────────────────────
try:
    from macro_context import MacroContext
    _HAS_MACRO = True
except ImportError:
    _HAS_MACRO = False

# ── AI NEWS SENTIMENT ─────────────────────────────────────────────────────────
from news_sentiment import fetch_and_analyze

# ── AI DIRECTIONAL FORECAST ───────────────────────────────────────────────────
from ai_forecast import get_ai_forecast

# ── SECTOR PULSE ─────────────────────────────────────────────────────────────
try:
    from sector_pulse import get_sector_pulse, get_sector_for_ticker
    _HAS_SECTOR_PULSE = True
except ImportError:
    _HAS_SECTOR_PULSE = False

# ── FUNDAMENTALS ─────────────────────────────────────────────────────────────
try:
    from fundamentals import get_fundamentals
    _HAS_FUNDAMENTALS = True
except ImportError:
    _HAS_FUNDAMENTALS = False

# ── TIMEFRAME HELPER ─────────────────────────────────────────────────────────
TIMEFRAME_DAYS: dict[str, int] = {"INTRADAY": 0, "1D": 1, "3D": 3, "5D": 5, "1W": 7}


def timeframe_to_dates(tf: str) -> tuple[str, str]:
    """Convert 'INTRADAY'/'1D'/'3D'/'5D' to (start_date, end_date) strings.

    On weekdays start_date = today (unchanged).
    On weekends/holidays start_date advances to the next trading day so
    predictions target "buy on Monday" rather than the past weekend.

    INTRADAY (n == 0) is a same-day horizon: start == end == the trading day,
    with no weekend buffer. Callers detect INTRADAY downstream via start == end.
    """
    from datetime import date
    from market_calendar import next_trading_day
    n = TIMEFRAME_DAYS.get(tf.upper(), 5)
    today = date.today()
    start = next_trading_day(today)       # no-op on trading days; Mon on Sat/Sun
    if n == 0:
        # Same-day intraday window — target is the trading day itself.
        return start.strftime("%Y-%m-%d"), start.strftime("%Y-%m-%d")
    end = start + timedelta(days=n + 2)  # weekend buffer anchored from start
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


# ── NSE UNIVERSE (dynamic — fetched from Yahoo Finance screener) ─────────────
from universe import get_universe

TICKER_NAMES: dict[str, str] = {}   # populated on first predict/rank call
DEFAULT_UNIVERSE: list[str]  = []   # populated on first predict/rank call


def _init_universe() -> None:
    """Load universe from cache (or fetch from YF) on first use."""
    global TICKER_NAMES, DEFAULT_UNIVERSE
    if not TICKER_NAMES:
        TICKER_NAMES     = get_universe()
        DEFAULT_UNIVERSE = list(TICKER_NAMES.keys())

# ── BACKTEST-DERIVED EXPECTED RETURNS (from trading_strategies_india.md v2) ──
# (win_rate, avg_win%, avg_loss%) per strategy at ~21-day horizon
_STRATEGY_STATS_DEFAULT = {
    # ══════════════════════════════════════════════════════════════════════════
    # ALL WIN RATES BELOW ARE NSE-VERIFIED (276 stocks, 2019-2024 backtest)
    # NOT from US research claims. Mode A = all signals. Mode B = VIX<18 filter.
    # Format: (win_rate, avg_win_pct, avg_loss_pct)
    # ══════════════════════════════════════════════════════════════════════════

    # ── Original strategies ──────────────────────────────────────────────────
    # S1: Shadow recovery C5 fires rarely — only 2 signals on 276 stocks; using 30-stock estimate
    "S1":    (0.63, 5.8, 3.4),   # C5 shadow recovery — ~2-3/year, 63% NSE estimate
    # S2-MFS-NIRA: all WEAK at every horizon — no genuine edge beyond market drift
    "S2":    (0.58, 12.5, 4.2),  # Momentum Breakout — 58.3% at 1M (best, N=4054)
    "S3":    (0.58, 8.0, 2.0),   # EMA Trend — 57.5% at 1M (best, N=29358)
    "MFS":   (0.60, 10.0, 4.0),  # Multi-Factor — 59.8% at 1M (best, N=54932)
    "NIRA":  (0.57, 9.0, 3.5),   # Index Reconstitution — 57.2% at 1M
    "PED":   (0.56, 4.5, 2.5),   # Post-Earnings Drift — 55.5% at 1M
    "SUPER": (0.52, 7.0, 3.5),   # Supertrend crossover — no backtest data (est.)

    # ── S4: Connors RSI(2) — NSE-verified (NOT US 77% claim) ─────────────────
    # v1 now uses RSI(2)<2 (doubleyourreturns.in NSE 2004-2017: 68-71% with <2 vs 56% with <5)
    # v2: 66.2% at 1M Mode A (N=544); expected ~70% with RSI(2)<2 threshold
    "S4":    (0.63, 3.5, 2.8),   # RSI(2)<2 v1 — upgraded from 56% to 63% (NSE-calibrated)
    "S4V2":  (0.70, 3.2, 2.5),   # RSI(2)<3 v2 — 70% Mode A (NSE doubleyourreturns.in)

    # ── S5: DMA Pullback — NSE-verified (NOT US 80% claim) ───────────────────
    # v1: 56.5% at 1M Mode A (N=42574). v2: 58.5% at 2W Mode A (N=8932)
    "S5":    (0.57, 4.2, 3.1),   # DMA Pullback v1 — 57% NSE-verified (was wrongly 80%)
    "S5V2":  (0.59, 4.0, 2.8),   # DMA Pullback v2 — 58.5% (tighter RSI5<30 filter)

    # ── S6: Momentum RSI Dip — BEST VERIFIED STRATEGY ─────────────────────────
    # Mode A 2W: 65.3% (MEDIUM confidence, N=498)
    # Mode B 3D: 70.9% (HIGH confidence, N=141, excess +11.3%) ← BREAKTHROUGH
    # Mode B 1M: 63.8% (WEAK)
    # Using Mode B 3D result as the operating win rate (VIX filter is applied at predict time)
    "S6":    (0.65, 5.5, 3.2),   # MomDip v1 — 65% Mode A, 70.9% Mode B 3D (HIGH!)

    # ── S6v2: Enhanced MomDip — NEW BEST STRATEGY ────────────────────────────
    # Mode B 1M: 76.5% (LOW confidence, N=34) — FIRST result above 75%!
    # Mode C 1D: 73.3% (MEDIUM confidence, N=15)
    # Mode C 1M: 93.3% (MEDIUM confidence, N=15) — spectacular but small N
    # Using conservative Mode B estimate; will update with live paper trades
    "S6V2":  (0.69, 5.2, 3.0),   # MomDip v2 — 69% Mode A-B blend; 76.5% Mode B 1M

    # ── S7: Multi-day Capitulation — NEW ─────────────────────────────────────
    # Mode A 1W: 59.4% (MEDIUM confidence, N=212, excess +3.8%)
    # Mode C 3D: 70.8% (MEDIUM confidence, N=24)
    "S7":    (0.61, 4.5, 2.8),   # 3-bar capitulation — 61% Mode A; 70.8% Mode C 3D

    # ── S8: RSI Triple Confluence — STATISTICALLY CONFIRMED NEW STRATEGY ─────
    # Mode A 3D: 59.2% (HIGH confidence, N=282, excess +5.7%) ← VERIFIED EDGE
    # Mode A 1D: 60.1%, Mode A 1M: 63.3% (MEDIUM)
    # Mode C 1M: 73.0% (MEDIUM confidence, N=37)
    "S8":    (0.60, 4.8, 2.9),   # RSI 3-period confluence — HIGH at 3D (N=282)

    # ── S9: MACD-ADX Momentum — WEAK, include for completeness ───────────────
    # Mode A 1M: 58.0% (WEAK). Mode B/C show no improvement.
    "S9":    (0.58, 6.0, 3.5),   # MACD-ADX crossover — 58% 1M, no real edge

    # ── S10: 20-Day Low in Uptrend — MODERATE SIGNAL ─────────────────────────
    # Mode A 2W: 61.4% (WEAK, N=2465), 1W: 60.6%, 3D: 59.8%
    # Mode B 3D: 57.4% (LOW, N=674)
    "S10":   (0.61, 5.0, 3.0),   # 20D Low Uptrend — 61% Mode A 2W; moderate signal

    # ── S11: Confluence Gate — PROMISING, SMALL N ────────────────────────────
    # Mode A 3D: 61.2% (WEAK, N=98). Mode B: ~62%. Mode C: 70.6% (N=17)
    # Small sample limits confidence; keep as high-quality rare signal
    "S11":   (0.62, 5.5, 3.0),   # S8+S6v2 confluence — 62% Mode A, 70.6% Mode C

    # ── v4 Research-derived strategies (Jun 2026 — NSE-verified Jun 2026) ───────
    # S_CAPFLOW: Capitulation 3-red + volume spike + Nifty bull. NSE backtest 378 stocks 2019-24.
    # Mode A 3D: 58.7% (N=1457, WEAK). Mode B 1M: 52.3%. Much weaker than estimated.
    "S_CAPFLOW":  (0.587, 3.2, 2.4),   # Capitulation vol-spike — 58.7% NSE-verified 3D

    # S_CTRIO: Triple RSI confluence (RSI2<5 + RSI5<30 + RSI14<35) + SMA200 + ADX>20.
    # Mode A 3D: 71.0% HIGH (N=124, excess +16.9%). Mode B 3D: 70.0% HIGH (N=70). BEST SIGNAL.
    "S_CTRIO":    (0.710, 5.8, 2.5),   # Triple RSI confluence — 71.0% NSE-verified 3D HIGH

    # S_SEASONAL: Santa Claus rally Dec20-Jan5. NSE 20-year study: 80-85%.
    # Mode A 2W: 70.8%. Mode B 1W: HIGH confidence (excess +10.2%). Mode B 1M: HIGH.
    "S_SEASONAL": (0.708, 5.2, 2.8),   # Santa rally — 70.8% NSE-verified 2W

    # ── v5 New strategies (Jun 2026 NSE-verified on 378 stocks 2019-24) ─────────
    # S12: Post-Budget seasonal. Documented 80% for Nifty index; individual stocks: 50.7%.
    # The index-level edge does NOT translate to stock-level. Signals too many stocks (N=2238).
    "S12":  (0.507, 2.0, 2.5),   # Post-Budget seasonal — 50.7% NSE-verified (weak on stocks)

    # S13: Oct-Nov seasonal. Documented 90% for Nifty; individual stocks: 57.1%. Same issue.
    "S13":  (0.571, 3.5, 2.8),   # Oct-Nov seasonal — 57.1% NSE-verified

    # S14: EMA20 touch in uptrend. Mode A 1M: 56.3%. Not as strong as designed.
    "S14":  (0.563, 3.0, 2.8),   # EMA20 dip — 56.3% NSE-verified

    # S15: NR7 Inside Bar. Mode A 1M: 55.7%. Marginal edge.
    "S15":  (0.557, 2.8, 3.0),   # NR7+IB — 55.7% NSE-verified

    # S16: StochRSI Oversold Recovery. Mode A 1W: 62.3% MEDIUM. Better than expected.
    "S16":  (0.623, 3.8, 2.8),   # StochRSI recovery — 62.3% NSE-verified 1W MEDIUM

    # ── v6 Famous Analyst Strategies (NSE-verified Jun 2026, 378-stock universe) ──
    # S17: TTM Squeeze + NR7. Best: Mode A 1M=59.6% WEAK; Mode C 1M=55.8% HIGH (N=95, excess+5.3%).
    # US strategies don't port well to NSE individual stocks at short horizons.
    "S17":  (0.596, 4.2, 2.8),   # TTM Squeeze — 59.6% Mode A 1M (WEAK on stocks; best under full macro)
    # S18: RSI Bullish Divergence. Best: Mode A 1D=54.3% LOW (N=254); Mode C 1D=61.5% LOW (N=13).
    "S18":  (0.543, 0.8, 2.5),   # RSI divergence — 54.3% Mode A 1D LOW (N=254)
    # S19: VCP — Minervini Volatility Contraction Pattern. Best: Mode A 1M=60.5% WEAK (N=806); Mode C 1W=62.5% LOW (N=48).
    "S19":  (0.605, 3.7, 3.0),   # VCP breakout — 60.5% Mode A 1M WEAK (best NSE result)
    # S20: Gap-Up + Volume Surge. Weak on NSE: Mode A 1M=58.7% WEAK; negative excess vs Nifty all horizons.
    "S20":  (0.587, 4.0, 2.8),   # Gap-up + vol surge — 58.7% Mode A 1M WEAK (negative Nifty excess)
}

# Which strategies are valid predictors for each timeframe.
# Filters active_strategies before computing expected returns to avoid
# averaging a 5D strategy's stats into a 1D prediction.
STRATEGY_TIMEFRAME_MAP: dict[str, list[str]] = {
    # INTRADAY reuses only the fastest-reacting, oversold-bounce / short-momentum
    # signals — swing-oriented strategies don't resolve within a single session.
    "INTRADAY": ["S1", "S4", "S4V2", "S8", "S16", "S_CTRIO"],
    "1D": ["S1", "S4", "S4V2", "S7", "S8", "S11", "PED",
           "S_CAPFLOW", "S_CTRIO", "S15", "S16", "S20"],
    "3D": ["S1", "S4", "S4V2", "S5", "S5V2", "S6", "S6V2", "S7", "S8", "S9", "S11", "SUPER", "PED",
           "S_CAPFLOW", "S_CTRIO", "S14", "S15", "S16", "S17", "S18", "S20"],
    "5D": ["S2", "S5", "S5V2", "S6", "S6V2", "S9", "S10", "S11", "MFS", "NIRA", "SUPER",
           "S_CAPFLOW", "S_CTRIO", "S_SEASONAL", "S12", "S13", "S14", "S15", "S16",
           "S17", "S18", "S19"],
    "1M": ["S6V2", "S_SEASONAL", "S19"],
    "1W": ["S6", "S6V2", "S9", "S10", "S11", "MFS", "SUPER",
           "S_CAPFLOW", "S_SEASONAL", "S14", "S15", "S16", "S17", "S19"],
}

# Estimated next-open slippage buffer (vs prior close) used to propose a realistic
# entry limit. This is also the default "no-chase" threshold at execution time.
ENTRY_BUFFER_BY_TIMEFRAME: dict[str, float] = {
    "INTRADAY": 0.001,  # 0.10% — tightest, entry is the live same-session price
    "1D": 0.002,  # 0.20%
    "3D": 0.003,  # 0.30%
    "5D": 0.005,  # 0.50%
    "1W": 0.007,  # 0.70% — wider buffer for longer hold
}

# INTRADAY minimum favorable move: a same-session trade must be able to clear ~1% to be worth
# the round-trip cost. Verified achievable on historical data (3.05M NSE day-rows, 3,706 series):
# a favorable intraday move >= 1% occurred on 89.2% of days (daily range >= 1% on 93.5%, median
# range 3.42%). So 1% filters only the genuinely flat setups. Env-overridable.
INTRADAY_MIN_MOVE_PCT: float = float(os.getenv("INTRADAY_MIN_MOVE_PCT", "1.0"))
# Minimum gap kept between the near and far intraday bounds after both are floored to >=1%, so the
# range never collapses to a single point (e.g. [1.00%, 1.10%]). Env INTRADAY_MIN_SPREAD_PCT.
INTRADAY_MIN_SPREAD_PCT: float = float(os.getenv("INTRADAY_MIN_SPREAD_PCT", "0.1"))

# ── TIGHT DIRECTIONAL BAND for INTRADAY + 1D (user request 2026-07-30) ────────────────────────
# A NARROW band centered on a volatility-scaled expected move so the mean/target is a single clear
# number (e.g. 1.00%–1.25%), instead of a wide [1.0, 2.0] intraday band or the flat ±1% 1D band.
# center = clamp(mult × ATR%, min_center, cap); band = [center − half, center + half]; near floored
# to `floor` (keeps the whole move >= 1%). Mirrors ai_forecast._TIGHT_BAND (same env knobs) so the
# AI path and the strategy/no-AI path produce identical bands. 3D/5D are unaffected.
_TIGHT_BAND: dict = {
    "INTRADAY": {
        "mult": float(os.getenv("INTRADAY_BAND_ATR_MULT", "0.33")),
        "min_center": float(os.getenv("INTRADAY_BAND_MIN_CENTER", "1.10")),
        "cap": float(os.getenv("INTRADAY_BAND_CAP", "2.0")),
        "half": float(os.getenv("INTRADAY_BAND_HALF_PCT", "0.125")),
        "floor": float(os.getenv("INTRADAY_MIN_MOVE_PCT", "1.0")),
    },
    "1D": {
        "mult": float(os.getenv("ONE_D_BAND_ATR_MULT", "0.45")),
        "min_center": float(os.getenv("ONE_D_BAND_MIN_CENTER", "1.10")),
        "cap": float(os.getenv("ONE_D_BAND_CAP", "2.5")),
        "half": float(os.getenv("ONE_D_BAND_HALF_PCT", "0.125")),
        "floor": float(os.getenv("ONE_D_BAND_FLOOR", "1.0")),
    },
}


def _tight_band_mag(tf_label: str, atr_pct: float):
    """Tight directional band as (near_mag, far_mag) magnitudes (near < far), or None for 3D/5D."""
    cfg = _TIGHT_BAND.get(tf_label)
    if not cfg:
        return None
    center = min(cfg["cap"], max(cfg["min_center"], cfg["mult"] * (atr_pct or 0.0)))
    h = cfg["half"]
    lo, hi = center - h, center + h
    if lo < cfg["floor"]:
        lo, hi = cfg["floor"], cfg["floor"] + 2 * h
    return round(lo, 2), round(hi, 2)

# AI range mode (see ai_forecast._AI_RANGE_MODE). "containment" (default) → do NOT tighten the
# INTRADAY/1D band; keep the wide AI/strategy prediction interval so the move lands inside the shown
# range ~85% of the time. "target" → apply the tight directional band below. Env AI_RANGE_MODE.
_AI_RANGE_MODE = os.getenv("AI_RANGE_MODE", "containment").strip().lower()

# ── 1D RANGE-ONLY POLICY ─────────────────────────────────────────────────────
# Next-day (1D) DIRECTION has a proven ~74% accuracy ceiling: no point-in-time feature (trend,
# momentum, ml_score, intraday close-strength) reliably separates hits from misses, and strong
# closes actually mean-revert. A directional 1D target is therefore structurally unreachable
# ~1-in-4 times (worse in a falling market) — the "did not reach 1D target" problem. So 1D is an
# honest RANGE-ONLY call rather than a coin-flip directional bet.
#
# The band is FLAT by policy (±1%), NOT ATR-scaled. An ATR-scaled band (the old
# max(3.5%, 1.30×ATR%)) ballooned to ±5%+ on volatile stocks — so wide the user can't bet on it
# ("somewhere between ₹10.7k and ₹11.9k" = no information) and so wide it always "hit", inflating
# the hit-rate without predicting anything. A flat ±1% band is a real, actionable "stays within 1%"
# claim and keeps 1D consistent with the NEUTRAL band everywhere else in the codebase
# (ai_forecast._NEUT_RANGE, database._SNAP_NEUT, research.range_model._NEUT_FLAT,
# ml_predictor._neutral_range). Env-overridable; set FORCE_1D_RANGE_ONLY=0 to restore directional
# 1D behaviour, or ONE_D_RANGE_HALF_PCT to widen/narrow the flat band.
FORCE_1D_RANGE_ONLY: bool = os.getenv("FORCE_1D_RANGE_ONLY", "0") != "0"
ONE_D_RANGE_HALF_PCT: float = float(os.getenv("ONE_D_RANGE_HALF_PCT", "1.0"))  # flat falsifiable half-width


def _load_live_strategy_stats() -> dict:
    """
    Override hardcoded stats with live paper trading results when a strategy
    has ≥ 30 closed trades — gives adapting win rate / avg return estimates.
    """
    stats = dict(_STRATEGY_STATS_DEFAULT)
    try:
        import database as db
        rows = db.get_signal_accuracy()
        for row in rows:
            sig = row.get("signal", "").upper()
            if sig not in stats:
                continue
            total = row.get("total", 0)
            if total < 30:
                continue
            win_rate = (row.get("win_rate") or 0) / 100.0
            avg_pnl  = row.get("avg_pnl_pct") or 0
            if win_rate <= 0:
                continue
            # Estimate avg_win / avg_loss from win_rate and avg_pnl:
            # avg_pnl = wr * avg_win - lr * avg_loss
            # Use current avg_win/avg_loss ratio to split
            old_wr, old_win, old_loss = stats[sig]
            old_rr = old_win / old_loss if old_loss else 2.0
            lr = 1 - win_rate
            # avg_pnl = wr * avg_win - lr * (avg_win / rr)
            # avg_pnl = avg_win * (wr - lr / rr)  → solve for avg_win
            denom = win_rate - (lr / old_rr)
            if abs(denom) > 1e-6:
                new_win  = max(0.5, min(avg_pnl / denom, 20.0))  # cap at 20× so corrupt rows can't inflate EV
                new_loss = max(0.1, new_win / old_rr)
                stats[sig] = (round(win_rate, 3), round(new_win, 2), round(new_loss, 2))
    except Exception:
        pass
    return stats


_STRATEGY_STATS = _load_live_strategy_stats()


# ── MARKET DATA CACHE (5-min TTL — shared across all parallel stock downloads) ─
_DATA_CACHE: dict = {}
_DATA_CACHE_TTL = 300  # seconds

# ── OHLCV CACHE (5-min TTL) ───────────────────────────────────────────────────
# When the same ticker is predicted across multiple timeframes (1D/3D/5D) in the
# watchlist flow, this prevents 3 separate Yahoo Finance downloads per ticker.
_OHLCV_CACHE: dict = {}
_OHLCV_CACHE_TTL = 300  # seconds
# Per-key fetch locks: prevent multiple parallel TF threads from racing to
# fetch the same (ticker, period) from the network simultaneously.
_OHLCV_FETCH_LOCKS: dict = {}
_OHLCV_FETCH_LOCKS_LOCK = threading.Lock()

# ── RANK RESULT CACHE (10-min TTL) ────────────────────────────────────────────
# rank_stocks_v2 scans 150 stocks — cache the full result so repeated UI hits
# (e.g. dashboard reload) don't re-run the entire scan within the same session.
_RANK_CACHE: dict = {}
_RANK_CACHE_TTL = 600  # seconds

# ── PREDICTION RESULT CACHE (5-min TTL) ───────────────────────────────────────
# Watchlist runs 3 TFs × N tickers in one parallel pool — without this cache a
# reload within 5 min re-runs every full prediction pipeline call.
_PRED_CACHE: dict = {}
_PRED_CACHE_TTL = 300  # seconds


def clear_runtime_caches() -> dict:
    """Clear in-memory caches used by ranking/prediction flows.

    Used by API-level force-refresh endpoints to guarantee a fresh recompute.
    Returns basic counts for observability/debugging.
    """
    cleared = {
        "market_cache": len(_DATA_CACHE),
        "ohlcv_cache": len(_OHLCV_CACHE),
        "rank_cache": len(_RANK_CACHE),
        "pred_cache": len(_PRED_CACHE),
    }
    _DATA_CACHE.clear()
    _OHLCV_CACHE.clear()
    _RANK_CACHE.clear()
    _PRED_CACHE.clear()
    return cleared

# ── LOG THROTTLE (avoid per-ticker warning spam) ────────────────────────────
_LAST_NIFTY_WARN_TS = 0.0
_NIFTY_WARN_TTL = 300  # seconds
_NIFTY_WARN_LOCK = threading.Lock()


def _warn_nifty_unavailable_once() -> None:
    global _LAST_NIFTY_WARN_TS
    now = time.time()
    with _NIFTY_WARN_LOCK:
        if now - _LAST_NIFTY_WARN_TS >= _NIFTY_WARN_TTL:
            logging.warning("Nifty market data unavailable — Nifty-dependent signals skipped (throttled)")
            _LAST_NIFTY_WARN_TS = now


def _get_market_cache(period: str = "1y"):
    """Return (nifty_c, vix_c) Series, cached for 5 minutes so parallel stock
    downloads don't each re-fetch a full year of Nifty + VIX data.
    Uses fetch_market_data() which tries NSE unofficial → Twelve Data → Yahoo.
    Only caches successful (non-empty) Nifty results so transient failures
    allow a retry on the next call instead of poisoning the cache."""
    key = f"mkt_{period}"
    entry = _DATA_CACHE.get(key)
    if entry and time.time() - entry["ts"] < _DATA_CACHE_TTL:
        return entry["nifty_c"], entry["vix_c"]
    days = {"1y": 365, "2y": 730}.get(period, 365)
    nifty_c, vix_c = fetch_market_data(period_days=days)
    if nifty_c is None or len(nifty_c) == 0:
        # Don't cache a failed result — allow immediate retry on next call
        logging.warning("Market data fetch returned empty Nifty — not caching, will retry")
        return pd.Series(dtype=float), vix_c
    _DATA_CACHE[key] = {"ts": time.time(), "nifty_c": nifty_c, "vix_c": vix_c}
    return nifty_c, vix_c


# ── DATA LOADER ───────────────────────────────────────────────────────────────
def _load_ticker_data(ticker: str, period: str = "1y"):
    """
    Download OHLCV for ticker using the multi-source fallback chain.
    Nifty + VIX come from the 5-min cache (fetched once across all parallel calls).
    OHLCV is also cached for 5 minutes so multiple TF predictions for the same
    ticker (watchlist 1D/3D/5D flow) share a single Yahoo Finance download.
    Returns (sc, sh, sl, sv, nifty_c, vix_c) suitable for signal generators.
    """
    nifty_c, vix_c = _get_market_cache(period)
    key = f"{ticker}_{period}"
    # Fast path: no lock needed when already cached.
    entry = _OHLCV_CACHE.get(key)
    if entry and time.time() - entry["ts"] < _OHLCV_CACHE_TTL:
        sc, sh, sl, sv = entry["ohlcv"]
        return sc, sh, sl, sv, nifty_c, vix_c
    # Slow path: serialize concurrent fetches for the same key so parallel TF
    # threads don't all hit the network at once for the same ticker.
    with _OHLCV_FETCH_LOCKS_LOCK:
        if key not in _OHLCV_FETCH_LOCKS:
            _OHLCV_FETCH_LOCKS[key] = threading.Lock()
        fetch_lock = _OHLCV_FETCH_LOCKS[key]
    with fetch_lock:
        entry = _OHLCV_CACHE.get(key)
        if entry and time.time() - entry["ts"] < _OHLCV_CACHE_TTL:
            sc, sh, sl, sv = entry["ohlcv"]
            return sc, sh, sl, sv, nifty_c, vix_c
        sc, sh, sl, sv = fetch_ohlcv(ticker, period=period)
        _OHLCV_CACHE[key] = {"ts": time.time(), "ohlcv": (sc, sh, sl, sv)}
        return sc, sh, sl, sv, nifty_c, vix_c


# ── MARKET GATES (HARD ENFORCEMENT) ─────────────────────────────────────────
def _get_vix() -> tuple[float, str]:
    _, vix_c = _get_market_cache()
    if vix_c is None or len(vix_c) == 0:
        return 18.0, "MODERATE (18.0) — VIX unavailable, using fallback"
    v = float(vix_c.iloc[-1])
    import math
    if v <= 0 or math.isnan(v):
        logging.warning("VIX value invalid (%s) — using neutral 18.0 to prevent Mode B gate misfiring", v)
        return 18.0, "MODERATE (18.0) — VIX invalid, using fallback"
    if v < 15:
        label = f"LOW ({v:.1f}) — Full size"
    elif v < 20:
        label = f"MODERATE ({v:.1f}) — Use 67% position size"
    elif v < 25:
        label = f"HIGH ({v:.1f}) — Use 50% position size"
    else:
        label = f"EXTREME ({v:.1f}) — NO NEW TRADES"
    return v, label


def _get_vix_declining() -> bool:
    """Returns True if VIX 5-day EMA slope is negative (declining trend).
    When combined with VIX<18 this is the Mode B condition that pushes
    S6 from 65% → 70.9% accuracy (HIGH confidence, N=141 in 276-stock backtest).
    """
    _, vix_c = _get_market_cache()
    if vix_c is None or len(vix_c) < 6:
        return False
    slope = float(vix_c.ewm(span=5).mean().diff().iloc[-1])
    return slope < 0


def _get_nifty_gate() -> tuple[bool, str]:
    """Returns (is_above_ema200, description).
    Fetches 2 years of Nifty data so EMA200 has ~304 warm bars (vs ~52 with 1y),
    making the current EMA200 level accurate. Requires 3 of the last 5 closes
    below the warm EMA200 to trigger CAUTION — majority-of-week rule filters noise."""
    nifty_c, _ = _get_market_cache("2y")  # 2y → EMA200 is fully warmed up
    if nifty_c is None or len(nifty_c) < 3:
        return True, "Nifty data unavailable — assuming OK"
    ema200_s = nifty_c.ewm(span=200).mean()
    ema200   = float(ema200_s.iloc[-1])
    price    = float(nifty_c.iloc[-1])
    window     = min(5, len(nifty_c))
    below_days = int((nifty_c.iloc[-window:] < ema200_s.iloc[-window:]).sum())
    above      = below_days < 3  # 3+ of 5 days below triggers defensive mode
    label      = (
        f"OK — Nifty ₹{price:,.0f} above EMA200 ₹{ema200:,.0f}"
        if above else
        f"CAUTION — Nifty ₹{price:,.0f} BELOW EMA200 ₹{ema200:,.0f} ({below_days}/5 days, defensive mode)"
    )
    return above, label


_MACRO_GATE_CACHE: dict = {"data": None, "ts": 0.0}
_MACRO_GATE_TTL = 300  # 5 minutes — macro conditions don't change intraday


def _get_macro_gate() -> tuple[bool, str]:
    """Returns (global_risk_on, description). Results cached for 5 minutes."""
    if not _HAS_MACRO:
        return True, "Macro data unavailable — assuming Risk-ON"
    now = time.time()
    if _MACRO_GATE_CACHE["data"] is not None and (now - _MACRO_GATE_CACHE["ts"]) < _MACRO_GATE_TTL:
        return _MACRO_GATE_CACHE["data"]
    end   = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    mc    = MacroContext()
    mc.load(start, end)
    # _features is shifted by 1 day so today's date is never in the index.
    # Use build_mask with ffill to get the most recent available T-1 row.
    _today_ts = pd.Timestamp.now().normalize()
    _mask = mc.build_mask(pd.DatetimeIndex([_today_ts]))
    ok    = bool(_mask.iloc[0]) if not _mask.empty else True
    # Re-fetch the full feature row for the description.
    feat  = mc.get(_today_ts - pd.Timedelta(days=1))
    if not feat:
        # Fallback: scan backwards up to 5 days for a valid row.
        for _d in range(1, 6):
            feat = mc.get(_today_ts - pd.Timedelta(days=_d))
            if feat:
                break
    parts = []
    if not feat.get("sp500_trend", True):
        parts.append("S&P500 weak")
    if not feat.get("usdinr_stable", True):
        parts.append("USD/INR volatile")
    if feat.get("crude_spike", False):
        parts.append("crude spike")
    desc = "Risk-ON" if ok else f"Risk-OFF ({', '.join(parts) or 'macro headwinds'})"
    result = (ok, desc)
    _MACRO_GATE_CACHE["data"] = result
    _MACRO_GATE_CACHE["ts"] = time.time()
    return result


# ── EARNINGS BLACKOUT ─────────────────────────────────────────────────────────
def get_earnings_status(ticker: str, window: int = 5) -> dict:
    """Check if ticker has earnings within `window` calendar days."""
    try:
        t  = yf.Ticker(ticker)
        ed = t.earnings_dates
        if ed is None or ed.empty:
            return {"next_date": None, "days_away": None, "in_blackout": False, "warning": None}

        today = datetime.now().date()
        # Sort descending so the nearest upcoming date is encountered first.
        # yfinance returns earnings_dates in undocumented order — sorting avoids
        # returning a distant date when a near one is also in the window.
        for edate in sorted(ed.index, key=lambda d: abs((d.date() - today).days) if hasattr(d, "date") else abs((pd.Timestamp(d).date() - today).days)):
            edate_d = edate.date() if hasattr(edate, "date") else pd.Timestamp(edate).date()
            days_away = (edate_d - today).days
            if -window <= days_away <= 30:
                in_blackout = abs(days_away) <= window
                warning = (
                    f"Earnings {'in' if days_away >= 0 else 'were'} "
                    f"{abs(days_away)} day{'s' if abs(days_away) != 1 else ''} "
                    f"{'away' if days_away >= 0 else 'ago'} — 5-day blackout applies"
                    if in_blackout else None
                )
                return {
                    "next_date":   str(edate_d),
                    "days_away":   days_away,
                    "in_blackout": in_blackout,
                    "warning":     warning,
                }
    except Exception:
        pass
    return {"next_date": None, "days_away": None, "in_blackout": False, "warning": None}


# ── STRATEGY SIGNAL RUNNER ────────────────────────────────────────────────────
def run_strategy_signals(
    ticker: str,
    sc: pd.DataFrame,
    sh: pd.DataFrame,
    sl: pd.DataFrame,
    sv: pd.DataFrame,
    nifty_c: pd.Series,
    lookback_days: int = 5,
    vix_c=None,
) -> dict:
    """
    Run S1–S6/MFS/NIRA/PED/SUPER on recent data.
    A signal is 'active' if it fired within the last `lookback_days` trading days.
    """
    recent = set(sc.index[-lookback_days:])

    def _fired(sigs):
        return any(d in recent and t == ticker for d, t in sigs)

    results = {}
    signal_errors: list[str] = []

    def _run(name, fn):
        try:
            results[name] = _fired(fn())
        except Exception as e:
            results[name] = False
            logging.warning("Signal %s failed for %s: %s", name, ticker, e)
            signal_errors.append(f"{name}: {e}")

    _run("S1",    lambda: gen_s1(sc, sh, sl, sv, nifty_c))
    _run("S2",    lambda: gen_s2(sc, sh, sl, sv, nifty_c))
    _run("S3",    lambda: gen_s3(sc, sh, sl, sv))
    _run("MFS",   lambda: gen_mfs(sc, sh, sl, sv, nifty_c))
    _run("NIRA",  lambda: gen_nira(sc, sh, sl, sv, nifty_c))
    _run("PED",   lambda: gen_ped(sc, sh, sl, sv))
    _run("SUPER", lambda: gen_supertrend(sc, sh, sl))
    _run("S4",    lambda: gen_s4(sc, sh, sl, sv, vix_c))
    _run("S5",    lambda: gen_s5(sc, sh, sl, sv, vix_c))
    _run("S6",    lambda: gen_s6(sc, sh, sl, sv, nifty_c, vix_c))
    # ── New high-accuracy strategies (v2 tightened + S7-S11) ─────────────────
    _run("S4V2",  lambda: gen_s4v2(sc, sh, sl, sv, nifty_c, vix_c))
    _run("S5V2",  lambda: gen_s5v2(sc, sh, sl, sv, nifty_c, vix_c))
    _run("S6V2",  lambda: gen_s6v2(sc, sh, sl, sv, nifty_c, vix_c))
    _run("S7",    lambda: gen_s7(sc, sh, sl, sv, nifty_c, vix_c))
    _run("S8",    lambda: gen_s8(sc, sh, sl, sv, nifty_c, vix_c))
    _run("S9",    lambda: gen_s9(sc, sh, sl, sv, nifty_c, vix_c))
    _run("S10",   lambda: gen_s10(sc, sh, sl, sv, nifty_c, vix_c))
    _run("S11",   lambda: gen_s11(sc, sh, sl, sv, nifty_c, vix_c))
    # ── v4 Research-derived strategies (Jun 2026) ─────────────────────────────
    _run("S_CAPFLOW",  lambda: gen_s_capflow(sc, sh, sl, sv, nifty_c, vix_c))
    _run("S_CTRIO",    lambda: gen_s_confluence_trio(sc, sh, sl, sv, nifty_c, vix_c))
    _run("S_SEASONAL", lambda: gen_s_seasonal(sc, sh, sl, sv, nifty_c, vix_c))
    # ── v5 New high-accuracy strategies (documented NSE >75% + technical) ─────
    _run("S12", lambda: gen_s12(sc, sh, sl, sv, nifty_c, vix_c))
    _run("S13", lambda: gen_s13(sc, sh, sl, sv, nifty_c, vix_c))
    _run("S14", lambda: gen_s14(sc, sh, sl, sv, nifty_c, vix_c))
    _run("S15", lambda: gen_s15(sc, sh, sl, sv, nifty_c, vix_c))
    _run("S16", lambda: gen_s16(sc, sh, sl, sv, nifty_c, vix_c))
    _run("S17", lambda: gen_s17(sc, sh, sl, sv, nifty_c, vix_c))
    _run("S18", lambda: gen_s18(sc, sh, sl, sv, nifty_c, vix_c))
    _run("S19", lambda: gen_s19(sc, sh, sl, sv, nifty_c, vix_c))
    _run("S20", lambda: gen_s20(sc, sh, sl, sv, nifty_c, vix_c))

    active = [k for k, v in results.items() if v]
    return {"signals": results, "active": active, "count": len(active),
            "signal_errors": signal_errors}


# ── ML FEATURE SCORE ──────────────────────────────────────────────────────────
def get_ml_feature_score(
    ticker:  str,
    sc:      pd.DataFrame,
    sh:      pd.DataFrame,
    sl:      pd.DataFrame,
    sv:      pd.DataFrame,
    nifty_c: pd.Series,
    vix_c:   Optional[pd.Series],
) -> dict:
    """
    Compute the 10 ml_combiner features for the current bar.
    Returns a 0–100 composite score and individual feature values.
    Higher score = historically more bullish feature state.
    """
    c = sc[ticker].dropna()
    h = sh[ticker].reindex(c.index).ffill()
    l = sl[ticker].reindex(c.index).ffill()
    v = sv[ticker].reindex(c.index).ffill()

    if len(c) < 30:
        return {"score": 50, "probability": 0.5, "features": {}}

    # ── Feature 1: RSI (inverted: low RSI = bullish for mean reversion) ────
    rsi_val = float(rsi(c).iloc[-1])
    # Rescale: RSI 20=bullish(+1), RSI 80=bearish(-1)
    rsi_feat = (50 - rsi_val) / 50  # +1 at RSI=0, -1 at RSI=100

    # ── Feature 2: Bollinger position (0=lower band, 1=upper band) ─────────
    bb_pos_val = float(bollinger_position(c).iloc[-1]) if len(c) >= 20 else 0.5
    bb_feat    = 1 - bb_pos_val  # low bb_pos = bullish (near lower band)

    # ── Feature 3: EMA stack (0–1, higher = more bullish) ──────────────────
    ema_stack_val = float(ema_stack_score(c).iloc[-1]) if len(c) >= 20 else 0.5

    # ── Feature 4: Volume ratio ─────────────────────────────────────────────
    v20 = float(v.rolling(20).mean().iloc[-1])
    vol_ratio  = float(v.iloc[-1]) / v20 if v20 > 0 else 1.0
    vol_feat   = min(vol_ratio / 2.0, 1.0)  # 2x volume = max score

    # ── Feature 5: OBV z-score ─────────────────────────────────────────────
    ob     = obv(c, v)
    ob_mu  = ob.rolling(20).mean().iloc[-1]
    ob_std = ob.rolling(20).std().iloc[-1]
    obv_z  = float((ob.iloc[-1] - ob_mu) / ob_std) if ob_std and ob_std > 0 else 0.0
    obv_feat = max(-1.0, min(1.0, obv_z / 2.0))  # normalize to -1..+1

    # ── Feature 6: Relative strength vs Nifty (3M) ─────────────────────────
    ni   = nifty_c.reindex(c.index).ffill()
    rs3m = float((c.iloc[-1] / c.iloc[-63] - 1) - (ni.iloc[-1] / ni.iloc[-63] - 1)) if len(c) >= 63 else 0.0
    rs_feat = max(-1.0, min(1.0, rs3m * 5))  # ±20% RS = ±1

    # ── Feature 7: MACD histogram sign ─────────────────────────────────────
    mh       = macd_h(c)
    macd_val = float(mh.iloc[-1]) if len(c) >= 27 else 0.0
    macd_feat = 1.0 if macd_val > 0 else 0.0

    # ── Feature 8: ADX (trend strength) ────────────────────────────────────
    adx_val = float(adx_s(h, l, c).iloc[-1]) if len(c) >= 15 else 20.0
    adx_feat = min(adx_val / 50.0, 1.0)

    # ── Feature 9: Shadow recovery (intraday bounce) ────────────────────────
    shadow_val = float(shadow_flag(c, l).iloc[-1]) if len(c) >= 20 else 0.0

    # ── Feature 10: VIX level (lower = better environment) ─────────────────
    vix_feat = 0.5
    if vix_c is not None and not vix_c.empty:
        vix_val  = float(vix_c.dropna().iloc[-1])
        vix_feat = max(0.0, 1.0 - vix_val / 30.0)  # VIX=0→1.0, VIX=30→0.0

    # ── Feature 11: Supertrend direction (price above ST line = bullish) ────
    def _st_dir_last(cs, hs, ls, period=10, mult=3.0):
        if len(cs) < period + 1:
            return 1
        atr_v  = atr(hs, ls, cs, period)   # atr(high, low, close, n)
        hl2    = (hs + ls) / 2
        up_raw = (hl2 + mult * atr_v).values
        dn_raw = (hl2 - mult * atr_v).values
        cv     = cs.values
        n      = len(cv)
        upper, lower = up_raw.copy(), dn_raw.copy()
        dirn = np.ones(n, dtype=int)
        for i in range(1, n):
            upper[i] = min(up_raw[i], upper[i-1]) if cv[i-1] <= upper[i-1] else up_raw[i]
            lower[i] = max(dn_raw[i], lower[i-1]) if cv[i-1] >= lower[i-1] else dn_raw[i]
            if   cv[i] > upper[i-1]: dirn[i] =  1
            elif cv[i] < lower[i-1]: dirn[i] = -1
            else:                     dirn[i] = dirn[i-1]
        return int(dirn[-1])

    st_feat = 1.0 if _st_dir_last(c, h, l) > 0 else 0.0

    # ── Weighted composite (weights reflect LR-like importance from backtest) ─
    weights = {
        "ema_stack":  0.22,  # trend alignment — most predictive in S2/S3
        "rs_3m":      0.17,  # relative strength — key S2/MFS filter
        "obv":        0.13,  # volume accumulation
        "macd":       0.12,  # momentum confirmation
        "vol_ratio":  0.10,  # conviction signal
        "adx":        0.08,  # trend strength
        "supertrend": 0.06,  # trend direction (Supertrend 10,3)
        "rsi":        0.05,  # oversold (S1 specific)
        "bb_pos":     0.03,  # mean reversion zone
        "vix":        0.02,  # macro environment
        "shadow":     0.02,  # S1 intraday bounce
    }
    feat_vals = {
        "ema_stack":  _fn(ema_stack_val, 0.5),
        "rs_3m":      _fn((rs_feat + 1) / 2, 0.5),
        "obv":        _fn((obv_feat + 1) / 2, 0.5),
        "macd":       _fn(macd_feat, 0.5),
        "vol_ratio":  _fn(vol_feat, 0.5),
        "adx":        _fn(adx_feat, 0.5),
        "supertrend": _fn(st_feat, 0.5),
        "rsi":        _fn((rsi_feat + 1) / 2, 0.5),
        "bb_pos":     _fn(bb_feat, 0.5),
        "vix":        _fn(vix_feat, 0.5),
        "shadow":     _fn(shadow_val, 0.0),
    }
    raw_composite = sum(weights[k] * feat_vals[k] for k in weights)
    score = int(round(raw_composite * 100))

    # Convert to probability (logistic-style, steepness=8)
    prob = 1 / (1 + math.exp(-8 * (raw_composite - 0.5)))

    # ── Two-tier gate (mirrors random_ai_test two-tier logic) ────────────────
    # Hard prerequisites: vol_ratio, macd, RSI must all be clearly bullish/bearish
    # before allowing HIGH probability. Any failure caps at 0.72 (MEDIUM ceiling).
    # This prevents the weighted composite from reaching HIGH on EMA alignment
    # alone when volume is thin or momentum has already turned.
    vol_feat_raw  = feat_vals.get("vol_ratio", 0.5)   # 0..1 (2× avg = 1.0)
    macd_feat_raw = feat_vals.get("macd", 0.5)         # 1.0=positive, 0.0=negative
    rsi_feat_raw  = feat_vals.get("rsi", 0.5)          # higher = more bullish (oversold)
    adx_feat_raw  = feat_vals.get("adx", 0.5)

    bull_hard_ok = (
        vol_feat_raw  >= 0.45  and   # vol ≥ 0.9× avg  (normalised: 0.9/2=0.45)
        macd_feat_raw >= 0.9   and   # MACD histogram positive
        adx_feat_raw  >= 0.4         # ADX > 20 (trending market)
        # Note: Nifty 5D momentum checked externally via nifty_ok in _calc_confidence
    )
    bear_hard_ok = (
        vol_feat_raw  >= 0.6   and
        macd_feat_raw <= 0.1   and   # MACD firmly negative
        adx_feat_raw  >= 0.4
    )

    if raw_composite > 0.5 and not bull_hard_ok:
        prob = min(prob, 0.72)
    elif raw_composite < 0.5 and not bear_hard_ok:
        prob = max(prob, 0.28)

    return {
        "score":       score,
        "probability": _sf(prob, 3, 0.5),
        "upgraded":    bool(prob > 0.65) if math.isfinite(prob) else False,
        "features":    {
            "rsi":        _sf(rsi_val, 1),
            "bb_pos":     _sf(bb_pos_val, 2),
            "ema_stack":  _sf(ema_stack_val, 2),
            "vol_ratio":  _sf(vol_ratio, 2),
            "obv_z":      _sf(obv_z, 2),
            "rs_3m_pct":  _sf(rs3m * 100, 1),
            "macd_pos":   bool(macd_val > 0) if math.isfinite(macd_val) else None,
            "adx":        _sf(adx_val, 1),
            "shadow":     bool(shadow_val),
            "supertrend": bool(st_feat),
        },
    }


# ── DIRECTIONAL PRICE FORECAST (ML-based, independent of signal layer) ────────
def _directional_forecast(
    ml_probability: float,
    tf_label: str,
    nifty_ok: bool,
    vix_level: float,
) -> dict:
    """
    Predicts price direction (BULLISH / BEARISH / NEUTRAL) from the ML feature
    probability. This is a price forecast — separate from the trade recommendation
    (direction field, which requires a buy signal to fire).

    Returns a dict with predicted_direction, predicted_return_lo, predicted_return_hi.
    """
    tf_scale   = {"INTRADAY": 0.20, "1D": 0.35, "3D": 0.65, "5D": 1.0, "1W": 1.3}.get(tf_label, 1.0)
    regime_mult = 0.7 if not nifty_ok else 1.0
    vix_mult    = 0.8 if vix_level > 20 else 1.0

    p_bull = ml_probability
    p_bear = 1.0 - ml_probability

    if p_bull >= 0.60:
        strength = (p_bull - 0.60) / 0.40          # 0→1 as probability goes 0.60→1.00
        lo = round((0.5 + strength * 2.0) * tf_scale * regime_mult * vix_mult, 2)
        hi = round((1.5 + strength * 5.0) * tf_scale * regime_mult * vix_mult, 2)
        return {"predicted_direction": "BULLISH", "predicted_return_lo": lo, "predicted_return_hi": hi}
    elif p_bear >= 0.60:
        strength = (p_bear - 0.60) / 0.40
        # Bearish returns are negative; regime dampener not applied (bear markets can be fast)
        hi = round(-(0.5 + strength * 2.0) * tf_scale, 2)
        lo = round(-(1.5 + strength * 5.0) * tf_scale, 2)
        return {"predicted_direction": "BEARISH", "predicted_return_lo": lo, "predicted_return_hi": hi}
    else:
        lo = round(-0.5 * tf_scale, 2)
        hi = round(0.5 * tf_scale, 2)
        return {"predicted_direction": "NEUTRAL", "predicted_return_lo": lo, "predicted_return_hi": hi}


# ── EXPECTED RETURN CALCULATOR ────────────────────────────────────────────────
def _calc_expected_return(
    active_strategies: list[str],
    ml_upgraded:       bool,
    n_trading_days:    int,
    nifty_ok:          bool,
    macro_ok:          bool,
    vix_level:         float,
) -> tuple[float, float, str, dict]:
    """
    Returns (lo%, hi%, direction, backtest_stats) based on actual backtest stats.
    backtest_stats contains raw (undampened) historical performance for UI display.
    """
    scale = 1.0

    if not active_strategies:
        return 0.0, 0.0, "NO TRADE", {}

    # Compute weighted EV from each active strategy's backtest stats
    evs, win_rates, avg_wins, avg_losses = [], [], [], []
    for s in active_strategies:
        if s in _STRATEGY_STATS:
            wr, avg_win, avg_loss = _STRATEGY_STATS[s]
            ev = wr * avg_win - (1 - wr) * avg_loss
            evs.append(ev)
            win_rates.append(wr)
            avg_wins.append(avg_win)
            avg_losses.append(avg_loss)

    if not evs:
        return 0.0, round(3.0 * scale, 2), "SLIGHTLY BULLISH", {}

    avg_ev   = sum(evs) / len(evs)
    avg_wr   = sum(win_rates) / len(win_rates)
    raw_avg_win  = sum(avg_wins) / len(avg_wins)
    raw_avg_loss = sum(avg_losses) / len(avg_losses)

    # Signal count multiplier (more convergent signals = wider expected range)
    n_sig = len(active_strategies)
    signal_mult = 1.0 + 0.15 * (n_sig - 1)  # +15% per additional signal

    # ML upgrade adds 10%
    ml_mult = 1.10 if ml_upgraded else 1.0

    # Nifty below EMA200 = reduce by 40%
    nifty_mult = 0.60 if not nifty_ok else 1.0

    # Macro risk-off = reduce by 20%
    macro_mult = 0.80 if not macro_ok else 1.0

    # VIX adjustment
    vix_mult = 1.0 if vix_level < 20 else 0.70

    adjusted_ev = avg_ev * signal_mult * ml_mult * nifty_mult * macro_mult * vix_mult * scale

    lo = round(min(adjusted_ev * 0.4, adjusted_ev * 1.8), 2)  # conservative bound
    hi = round(max(adjusted_ev * 0.4, adjusted_ev * 1.8), 2)  # optimistic bound

    if avg_wr >= 0.60 and n_sig >= 2:
        direction = "BULLISH"
    elif avg_wr >= 0.50 or n_sig >= 1:
        direction = "SLIGHTLY BULLISH"
    else:
        direction = "NEUTRAL"

    # Downgrade if regime is adverse
    if not nifty_ok or vix_level > 20:
        direction = "SLIGHTLY BULLISH" if direction == "BULLISH" else "NEUTRAL"

    # Build dampener description for UI
    dampeners = []
    if not nifty_ok:
        dampeners.append("Nifty<EMA200 −40%")
    if not macro_ok:
        dampeners.append("Macro risk-off −20%")
    if vix_level >= 20:
        dampeners.append("VIX≥20 −30%")
    total_dampener = round((1 - nifty_mult * macro_mult * vix_mult) * 100)

    backtest_stats = {
        "win_rate_pct":    round(avg_wr * 100, 1),
        "avg_win_pct":     round(raw_avg_win, 2),
        "avg_loss_pct":    round(raw_avg_loss, 2),
        "dampener_pct":    total_dampener,
        "dampeners":       dampeners,
        "signals_used":    [s for s in active_strategies if s in _STRATEGY_STATS],
    }

    return lo, hi, direction, backtest_stats


def _calc_confidence(
    n_signals: int,
    ml_upgraded: bool,
    news_label: str,
    nifty_ok: bool,
    vix_level: float,
    active_strategies: list | None = None,
    vix_declining: bool = False,
    ml_probability: float = 0.5,
    nifty_trending: bool = False,
    qm_score: float = 0.0,
    stage2_breadth: float = 0.5,
    fii_regime: str = "NEUTRAL",
    pcr: float | None = None,
    macro_ok: bool = False,
) -> tuple[str, dict]:
    """
    Confidence scoring with VIX-gated Mode B and Mode S (strict) bonuses.
    Returns (confidence_label, breakdown_dict).

    Mode B (VIX<18+declining): backtest-verified boost.
      S6 Mode B 3D = 70.9% HIGH (N=141, excess +11.3%)
      S8 Mode A 3D = HIGH (N=282, excess +5.7%)
      S6v2 Mode B 1M = 76.5% — first above-75% result

    Mode S (strict): VIX<15 + Nifty trending + ML>0.62 + 2+ signals.
      Adds +4 bonus (vs Mode B's +3) to push reliable HIGH above 75% threshold.

    S17 Quality-Momentum: normalized 12M return/vol > 1.5 adds +2 bonus.
      BacktestIndia.com 18.5yr study: 78% annual win rate.

    Weinstein Stage 2 breadth gate: <30% stocks advancing = bear market penalty.
    FII flow and PCR contrarian adjustments for institutional regime.
    """
    active_strategies = active_strategies or []
    breakdown: dict = {}

    base = 0
    base += n_signals * 2
    base += 3 if ml_upgraded else 0
    base += 2 if news_label == "BULLISH" else (-1 if news_label == "BEARISH" else 0)
    base -= 3 if not nifty_ok else 0
    base -= 2 if vix_level > 20 else 0
    breakdown["base"] = base
    score = base

    # S_CTRIO=71% HIGH, S6=68.3% Mode B HIGH, S8=59.3% HIGH, S_SEASONAL=70.8% NSE-verified
    # S17/S18/S19/S20 verified WEAK-LOW on NSE stocks (none reached Mode B ≥65%)
    high_acc_signals = {"S6", "S6V2", "S8", "S11", "S7", "S_CTRIO", "S_SEASONAL", "S16"}
    has_high_acc = bool(set(active_strategies) & high_acc_signals)

    # ── Mode B bonus (VIX<18 + declining) ──────────────────────────────────────
    vix_mode_b = vix_level < 18 and vix_declining
    mode_b_bonus = 3 if (vix_mode_b and has_high_acc) else 0
    score += mode_b_bonus
    breakdown["mode_b"] = mode_b_bonus

    # ── Mode S bonus (strict: VIX<15 + Nifty trending up + ML>0.62 + 2+ signals) ──
    vix_mode_s = vix_level < 15 and nifty_ok and nifty_trending
    mode_s_bonus = 4 if (vix_mode_s and n_signals >= 2 and ml_probability > 0.62 and has_high_acc) else 0
    score += mode_s_bonus
    breakdown["mode_s"] = mode_s_bonus

    # ── S_CTRIO extra (71.0% HIGH, excess +16.9% vs Nifty — system's best verified signal) ──
    ctrio_bonus = 3 if ("S_CTRIO" in active_strategies and (vix_mode_b or vix_mode_s)) else 0
    score += ctrio_bonus
    breakdown["ctrio_bonus"] = ctrio_bonus

    # ── Quality-Momentum bonus (BacktestIndia 18.5yr: 78% annual win rate) ──
    qm_bonus = 2 if (qm_score > 1.5 and nifty_ok) else 0
    score += qm_bonus
    breakdown["qm_bonus"] = qm_bonus

    # ── Weinstein Stage 2 breadth gate ─────────────────────────────────────────
    if stage2_breadth < 0.30:
        breadth_adj = -3   # bear market: <30% of stocks in Stage 2 (advancing)
    elif stage2_breadth > 0.60:
        breadth_adj = 1    # strong bull
    else:
        breadth_adj = 0
    score += breadth_adj
    breakdown["breadth_adj"] = breadth_adj

    # ── FII flow regime bonus/penalty ──────────────────────────────────────────
    fii_adj = {"FII_STRONG_BUY": 2, "FII_BUY": 1, "NEUTRAL": 0,
               "FII_SELLING_DII_ABSORBING": 0, "RISK_OFF": -2}.get(fii_regime, 0)
    score += fii_adj
    breakdown["fii_adj"] = fii_adj

    # ── PCR contrarian adjustment ───────────────────────────────────────────────
    if pcr is not None:
        pcr_adj = 1 if pcr > 1.25 else (-1 if pcr < 0.80 else 0)
    else:
        pcr_adj = 0
    score += pcr_adj
    breakdown["pcr_adj"] = pcr_adj

    # ── Mode C bonus (full macro alignment: VIX<18 declining + macro_ok + HIGH signal) ──
    # Mode C results: S4v2=78.5%, S8=73.3%, S11=76.2%, S6v2=87.5%, SCT=75.0%
    mode_c_bonus = 2 if (macro_ok and vix_mode_b and has_high_acc) else 0
    score += mode_c_bonus
    breakdown["mode_c"] = mode_c_bonus

    breakdown["total"] = score

    if score >= 7 and nifty_ok:
        label = "HIGH"
    elif score >= 3:
        label = "MEDIUM"
    else:
        label = "LOW"
    return label, breakdown


# ── MAIN PREDICTION API ───────────────────────────────────────────────────────
def predict_stock_v2(ticker: str, start_date: str, end_date: str,
                     _market_ctx: dict | None = None,
                     _run_ai_forecast: bool = False,
                     _ai_fast_mode: bool = False,
                     _ai_fast_fail_on_rate_limit: bool = False,
                     _skip_fresh_fetch: bool = False,
                     _skip_news: bool = False) -> dict:
    """
    Full prediction for one NSE ticker over [start_date, end_date].
    Pass _market_ctx (from rank_stocks_v2) to skip redundant market gate fetches.
    Pass _run_ai_forecast=True (from watchlist) to call Claude with strategy context.
    Pass _skip_fresh_fetch=True to use cached OHLCV + live price (avoids network timeouts).
    """
    _init_universe()
    company = TICKER_NAMES.get(ticker, ticker.replace(".NS", "").replace(".BO", ""))

    # ── Prediction cache (5-min TTL) — skip full pipeline on rapid reloads ───
    _pred_key = (
        f"{ticker}|{start_date}|{end_date}|{int(_run_ai_forecast)}"
        f"|{int(_ai_fast_mode)}|{int(_ai_fast_fail_on_rate_limit)}"
    )
    _pred_hit = _PRED_CACHE.get(_pred_key)
    if _pred_hit and time.time() - _pred_hit["ts"] < _PRED_CACHE_TTL:
        return _pred_hit["result"]

    # ── Request context (tracks data merges, validation, timing) ───────────────
    ctx = RequestContext(ticker)
    cache_age_days = None

    def _normalize_news_payload(news_obj: object) -> dict:
        """Guarantee a stable news payload shape for downstream fields."""
        if not isinstance(news_obj, dict):
            news_obj = {}

        label = str(news_obj.get("label") or "NEUTRAL").upper()
        if label not in ("BULLISH", "BEARISH", "NEUTRAL"):
            label = "NEUTRAL"

        try:
            score = int(news_obj.get("score", 0))
        except Exception:
            score = 0

        summary = str(news_obj.get("summary") or "No recent news found.")
        key_headline = str(news_obj.get("key_headline") or "")
        headlines = news_obj.get("headlines")
        if not isinstance(headlines, list):
            headlines = []
        headlines_dated = news_obj.get("headlines_dated")
        if not isinstance(headlines_dated, list):
            headlines_dated = []
        latest_date = str(news_obj.get("latest_date") or "")
        source = str(news_obj.get("source") or "none")

        return {
            "label": label,
            "score": score,
            "summary": summary,
            "key_headline": key_headline,
            "headlines": headlines,
            "headlines_dated": headlines_dated,
            "latest_date": latest_date,
            "source": source,
        }

    # ── Trading days in range ────────────────────────────────────────────────
    try:
        s = datetime.strptime(start_date, "%Y-%m-%d")
        e = datetime.strptime(end_date,   "%Y-%m-%d")
        n_trading = max(1, int((e - s).days * 5 / 7))
    except Exception:
        n_trading = 10

    # ── Market gates (HARD enforcement) ─────────────────────────────────────
    if _market_ctx:
        vix_level   = _market_ctx["vix_level"]
        vix_label   = _market_ctx["vix_label"]
        nifty_ok    = _market_ctx["nifty_ok"]
        nifty_label = _market_ctx["nifty_label"]
        macro_ok    = _market_ctx["macro_ok"]
        macro_label = _market_ctx["macro_label"]
    else:
        vix_level, vix_label   = _get_vix()
        nifty_ok,  nifty_label = _get_nifty_gate()
        macro_ok,  macro_label = _get_macro_gate()

    # Hard block: VIX > 25
    if vix_level > 25:
        return {
            "ticker": ticker, "company": company,
            "start_date": start_date, "end_date": end_date,
            "direction": "NO TRADE", "confidence": "BLOCKED",
            "no_trade_reason": "vix_block",
            "reason": f"India VIX {vix_level:.1f} > 25 — risk rules prohibit new positions",
            "expected_return_range": "N/A", "ret_lo": 0, "ret_hi": 0, "midpoint": 0,
            "signal_count": 0,
            "vix": {"level": vix_level, "label": vix_label},
            "nifty_gate": nifty_label, "macro": macro_label,
            "signals": {}, "active_strategies": [],
            "ml": {}, "news": {}, "earnings": {}, "price": None,
        }

    # ── Download data ─────────────────────────────────────────────────────────
    try:
        sc, sh, sl, sv, nifty_c, vix_c = _load_ticker_data(ticker, period="2y")
        if ticker not in sc.columns or sc[ticker].dropna().empty:
            return {"ticker": ticker, "error": "No price data available"}
        bars = sc[ticker].dropna()
        if len(bars) < 200:
            return {"ticker": ticker, "error": f"Insufficient history: {len(bars)} bars (need 200+)"}
        if nifty_c is None or len(nifty_c) == 0:
            # Degrade gracefully: Nifty-dependent signals will return False,
            # but price-only signals (S3, PED, SUPER, etc.) still run.
            _warn_nifty_unavailable_once()
            nifty_c = pd.Series(dtype=float)
        price = float(bars.iloc[-1])
        # Production predictions: start_date == today. Backtest passes historical dates.
        # start_date is a "YYYY-MM-DD" string — parse to a date before comparing.
        if isinstance(start_date, str):
            _start_d = datetime.strptime(start_date, "%Y-%m-%d").date()
        elif isinstance(start_date, datetime):
            _start_d = start_date.date()
        else:
            _start_d = start_date
        _is_today_prediction = (_start_d >= _date_cls.today())
    except Exception as ex:
        return {"ticker": ticker, "error": str(ex)}

    # ── Run strategy signals ──────────────────────────────────────────────────
    sig_result = run_strategy_signals(ticker, sc, sh, sl, sv, nifty_c, vix_c=vix_c)

    # ── ML feature score ──────────────────────────────────────────────────────
    ml = get_ml_feature_score(ticker, sc, sh, sl, sv, nifty_c, vix_c)

    # ── Parallel I/O: news + FII/PCR + intraday (concurrent network calls) ─────
    def _fetch_news_io():
        if _skip_news:
            return {"label": "NEUTRAL", "score": 0, "source": "skip", "summary": "", "headlines": [], "key_headline": ""}
        return fetch_and_analyze(ticker, company)

    def _fetch_fii_io():
        try:
            from fii_flow import get_fii_dii_flow, get_nifty_pcr
            _fii = get_fii_dii_flow()
            _regime = _fii.get("regime", "NEUTRAL")
            _data = {"fii_net": _fii.get("fii_net"), "dii_net": _fii.get("dii_net"), "regime": _regime}
            _pcr = get_nifty_pcr()
            return _regime, _data, (float(_pcr) if _pcr is not None else None)
        except Exception:
            return "NEUTRAL", {"fii_net": None, "dii_net": None, "regime": "NEUTRAL"}, None

    def _fetch_intraday_io():
        try:
            from intraday_live import get_live_intraday_context
            return get_live_intraday_context(ticker)
        except Exception as _id_err:
            logging.debug("intraday_live failed for %s: %s", ticker, _id_err)
            return {"data_available": False, "reason": "import or download failed"}

    def _fetch_sector_io():
        if not _HAS_SECTOR_PULSE:
            return None
        try:
            return get_sector_pulse()
        except Exception as _sp_err:
            logging.debug("sector_pulse failed: %s", _sp_err)
            return None

    # Fundamentals are expensive and yfinance-backed. Restrict by default to
    # AI/watchlist flows so universe ranking does not hammer the provider.
    _fetch_fundamentals_enabled = _run_ai_forecast or (os.getenv("ENABLE_FUNDAMENTALS_ON_RANK", "0") == "1")

    def _fetch_fundamentals_io():
        if not _fetch_fundamentals_enabled:
            return None
        if not _HAS_FUNDAMENTALS:
            return None
        try:
            return get_fundamentals(ticker)
        except Exception as _fu_err:
            logging.debug("fundamentals failed for %s: %s", ticker, _fu_err)
            return None

    def _fetch_earnings_io():
        return get_earnings_status(ticker)

    def _fetch_live_price_io():
        # Only meaningful for live/today predictions; backtest always returns None.
        if not _is_today_prediction:
            return None
        try:
            lp = fetch_live_price(ticker, allow_delayed=True)
            return float(lp) if lp and lp > 0 else None
        except Exception:
            return None

    _io_workers = 5 + (1 if _fetch_fundamentals_enabled else 0) + 1  # +1 for live price
    _IO_TIMEOUT = 10  # single wall-clock cap for the whole set (not per-future)
    with ThreadPoolExecutor(max_workers=_io_workers) as _pool:
        _f_news         = _pool.submit(_fetch_news_io)
        _f_fii          = _pool.submit(_fetch_fii_io)
        _f_intraday     = _pool.submit(_fetch_intraday_io)
        _f_sector       = _pool.submit(_fetch_sector_io)
        _f_earnings     = _pool.submit(_fetch_earnings_io)
        _f_fundamentals = _pool.submit(_fetch_fundamentals_io) if _fetch_fundamentals_enabled else None
        _f_live         = _pool.submit(_fetch_live_price_io)

        # Single wall-clock wait instead of 6 sequential result(timeout=10) calls.
        # Previously worst-case was 6 × 10s = 60s; now it's _IO_TIMEOUT seconds total.
        _all_futs = [f for f in [_f_news, _f_fii, _f_intraday, _f_sector, _f_earnings, _f_fundamentals, _f_live] if f]
        import concurrent.futures as _cf
        _cf.wait(_all_futs, timeout=_IO_TIMEOUT)

        def _safe_result(fut, default):
            if fut is None:
                return default
            try:
                return fut.result(timeout=0)
            except Exception:
                return default

        news             = _safe_result(_f_news, {"label": "NEUTRAL", "score": 0, "summary": "No recent news found.", "source": "none"})
        fii_regime, fii_data, pcr_value = _safe_result(_f_fii, ("NEUTRAL", {}, None))
        intraday_dict    = _safe_result(_f_intraday, {})
        sector_pulse_data = _safe_result(_f_sector, None)
        earnings         = _safe_result(_f_earnings, {"in_blackout": False, "days_to_earnings": None})
        fund_data        = _safe_result(_f_fundamentals, None)
        _live_price      = _safe_result(_f_live, None)

    # For production predictions, use live price as the AI's price anchor so the model
    # sees the current market level (not yesterday's close). Signals and stop-loss
    # calculations still use the OHLCV price — only the AI context is updated.
    _ai_current_price = _live_price if _live_price else price

    news = _normalize_news_payload(news)

    # Sector position — is this ticker's sector leading or lagging?
    _ticker_sector = get_sector_for_ticker(ticker) if _HAS_SECTOR_PULSE else None
    _sector_leading = False
    _sector_lagging = False
    if sector_pulse_data and _ticker_sector:
        _sector_leading = _ticker_sector in sector_pulse_data.get("leading_sectors", [])
        _sector_lagging = _ticker_sector in sector_pulse_data.get("lagging_sectors", [])

    # ── Compute prediction ────────────────────────────────────────────────────
    # Filter to strategies that are appropriate for this timeframe to avoid
    # diluting 1D predictions with 5D strategy stats and vice versa.
    # n_trading=2 is still a 1D pick — timeframe_to_dates adds a 2-day weekend buffer.
    # A same-day window (start == end) is the INTRADAY horizon — timeframe_to_dates
    # emits start == end only for INTRADAY, so this uniquely identifies it.
    if start_date == end_date:
        _tf_label = "INTRADAY"
    else:
        _tf_label = "1D" if n_trading <= 2 else ("3D" if n_trading <= 4 else ("5D" if n_trading <= 6 else "1W"))
    _relevant = STRATEGY_TIMEFRAME_MAP.get(_tf_label, sig_result["active"])
    _active_for_ev = [s for s in sig_result["active"] if s in _relevant]

    ret_lo, ret_hi, direction, backtest_stats = _calc_expected_return(
        _active_for_ev, ml["upgraded"],
        n_trading, nifty_ok, macro_ok, vix_level,
    )

    # Directional price forecast — independent of whether a buy signal fired
    price_forecast = _directional_forecast(ml["probability"], _tf_label, nifty_ok, vix_level)

    # ── Pre-compute context needed by AI forecast prompt ─────────────────────
    # VIX declining check — required for Mode B confidence bonus
    vix_declining = _get_vix_declining()

    # Nifty 5D trending check (for Mode S strict gate)
    try:
        nifty_trending = bool(nifty_c.iloc[-1] > nifty_c.iloc[-5])
    except Exception:
        nifty_trending = False

    # S17 Quality-Momentum score (risk-adjusted 12M momentum, BacktestIndia 18.5yr 78% WR)
    try:
        _c = sc[ticker].dropna()
        _ret_12m  = float(_c.iloc[-1] / _c.iloc[-252] - 1) if len(_c) >= 252 else 0.0
        _vol_12m  = float(_c.pct_change().tail(252).std() * (252 ** 0.5))
        qm_score  = _ret_12m / _vol_12m if _vol_12m > 0 else 0.0
    except Exception:
        qm_score = 0.0

    # Stage 2 breadth: would require the full universe sc DataFrame.
    # predict_stock_v2 only has the single-ticker sc, so we default to neutral (0.5)
    # and skip the breadth adjustment. rank_stocks_v2 could pre-compute this separately.
    stage2_breadth = 0.5

    if stage2_breadth < 0.30:
        breadth_regime = "BEAR"
    elif stage2_breadth > 0.60:
        breadth_regime = "BULL"
    else:
        breadth_regime = "NEUTRAL"

    # Mode C: full macro alignment — VIX<18 declining + macro_ok (all global macro favorable)
    _vix_mode_b_pre = vix_level < 18 and vix_declining
    mode_c_active = bool(macro_ok and _vix_mode_b_pre)
    mode_c_label  = (
        "FULL MACRO ALIGNMENT (Mode C) — 73-87% accuracy on HIGH signals"
        if mode_c_active else ""
    )

    # AI directional forecast — runs for all watchlist predictions when _run_ai_forecast=True
    ai_forecast: dict | None = None
    _af_err_msg: str | None = None
    _ai_soft_fail = False  # True when the AI outage is transient (provider will reset soon / Ollama up)
    if _run_ai_forecast:
        try:
            # Build indicator snapshot in ₹ for Claude context
            _c = sc[ticker].dropna()
            _h = sh[ticker].dropna()
            _lo = sl[ticker].dropna()
            # INTRADAY: the daily OHLCV series ends at yesterday's close, so RSI / Bollinger /
            # momentum computed off it would describe YESTERDAY — not today's intraday move.
            # Append the live price as today's provisional bar so the indicators the AI reasons
            # about reflect the current session (e.g. a stock that has already dropped intraday
            # shows a lower RSI / BB position). INTRADAY-only and only when the live price differs
            # from the last close; backtest (no live price) and 1D/3D are unaffected.
            if _tf_label == "INTRADAY" and _live_price and len(_c) >= 1:
                try:
                    _last_close = float(_c.iloc[-1])
                    if _last_close > 0 and abs(_live_price - _last_close) / _last_close > 0.001:
                        _today_ts = pd.Timestamp.now().normalize()
                        if len(_c.index) == 0 or _c.index[-1] != _today_ts:
                            # Use today's intraday high/low when available, else the live price.
                            _t_hi = _live_price
                            _t_lo = _live_price
                            if isinstance(intraday_dict, dict) and intraday_dict.get("data_available"):
                                _oh = intraday_dict.get("orb_high")
                                _ol = intraday_dict.get("orb_low")
                                if _oh:
                                    _t_hi = max(_live_price, float(_oh))
                                if _ol:
                                    _t_lo = min(_live_price, float(_ol))
                            _c  = pd.concat([_c,  pd.Series([_live_price], index=[_today_ts])])
                            _h  = pd.concat([_h,  pd.Series([_t_hi], index=[_today_ts])]) if len(_h) else _h
                            _lo = pd.concat([_lo, pd.Series([_t_lo], index=[_today_ts])]) if len(_lo) else _lo
                except Exception as _iv_err:
                    logging.debug("intraday live-bar append failed for %s: %s", ticker, _iv_err)
            _indicators = {}
            _ohlcv_df = None
            try:
                # Keys must match what ai_forecast._build_context_block() reads
                _indicators["close"]   = round(float(_c.iloc[-1]), 2) if len(_c) >= 1 else None
                _indicators["rsi14"]   = round(float(rsi(_c, 14).iloc[-1]), 1) if len(_c) >= 14 else None
                _indicators["rsi5"]    = round(float(rsi(_c, 5).iloc[-1]), 1) if len(_c) >= 5 else None
                _indicators["rsi2"]    = round(float(rsi(_c, 2).iloc[-1]), 1) if len(_c) >= 2 else None
                # Bollinger Bands (20, 2σ)
                _bb_sma = _c.rolling(20).mean()
                _bb_std = _c.rolling(20).std()
                _indicators["bb_lower"] = round(float((_bb_sma - 2 * _bb_std).iloc[-1]), 2)
                _indicators["bb_mid"]   = round(float(_bb_sma.iloc[-1]), 2)
                _indicators["bb_upper"] = round(float((_bb_sma + 2 * _bb_std).iloc[-1]), 2)
                _indicators["ema20"]   = round(float(_c.ewm(span=20).mean().iloc[-1]), 2)
                _indicators["ema50"]   = round(float(_c.ewm(span=50).mean().iloc[-1]), 2) if len(_c) >= 50 else None
                _indicators["ema200"]  = round(float(_c.ewm(span=200).mean().iloc[-1]), 2) if len(_c) >= 200 else None
                # atr signature: atr(h, l, c, n=14)
                _atr_s = atr(_h, _lo, _c, 14)
                _indicators["atr14"]   = round(float(_atr_s.iloc[-1]), 2)
                # ADX (trend strength)
                if len(_c) >= 15:
                    _indicators["adx14"] = round(float(adx_s(_h, _lo, _c).iloc[-1]), 1)
                # Volume ratio
                _vol20 = sv[ticker].rolling(20).mean().iloc[-1] if ticker in sv.columns else None
                _vol_now = sv[ticker].iloc[-1] if ticker in sv.columns else None
                if _vol20 and _vol_now:
                    _indicators["vol_ratio"] = round(float(_vol_now) / (float(_vol20) + 1e-9), 2)
                # MACD signal (histogram = MACD line - signal line)
                _macd_line = _c.ewm(span=12).mean() - _c.ewm(span=26).mean()
                _indicators["macd_signal"] = round(float((_macd_line - _macd_line.ewm(span=9).mean()).iloc[-1]), 4)
                # OBV trend
                if ticker in sv.columns and len(_c) >= 10:
                    _obv_series = obv(_c, sv[ticker].dropna())
                    _obv_slope = _obv_series.diff(5).iloc[-1]
                    _indicators["obv_trend"] = "rising" if _obv_slope > 0 else ("falling" if _obv_slope < 0 else "flat")
                # Short-term momentum — critical direction signals used by synthesis prompt
                _price_now = float(_c.iloc[-1])
                if len(_c) >= 10:
                    _indicators["return_10d"] = round((_price_now / float(_c.iloc[-10]) - 1) * 100, 1)
                if len(_c) >= 20:
                    _indicators["return_20d"] = round((_price_now / float(_c.iloc[-20]) - 1) * 100, 1)
                if len(_c) >= 63:
                    _indicators["return_90d"] = round((_price_now / float(_c.iloc[-63]) - 1) * 100, 1)
                if len(_c) >= 252:
                    _hi52 = float(_c.iloc[-252:].max())
                    _indicators["Dist_from_52W_High_%"] = round((_price_now / _hi52 - 1) * 100, 1)
                # Bollinger Band position: 0% = lower band, 100% = upper band
                if len(_c) >= 20:
                    _bb_u = float((_bb_sma + 2 * _bb_std).iloc[-1])
                    _bb_l = float((_bb_sma - 2 * _bb_std).iloc[-1])
                    if _bb_u > _bb_l:
                        _indicators["bb_pct"] = round((_price_now - _bb_l) / (_bb_u - _bb_l) * 100, 1)
                # Consecutive up/down days
                if len(_c) >= 6:
                    _diffs = _c.iloc[-6:].diff().dropna()
                    _up = _dn = 0
                    for _d in reversed(_diffs.values):
                        if _d > 0 and _dn == 0:
                            _up += 1
                        elif _d < 0 and _up == 0:
                            _dn += 1
                        else:
                            break
                    if _up >= 2:
                        _indicators["consec_days"] = f"+{_up} consecutive up"
                    elif _dn >= 2:
                        _indicators["consec_days"] = f"-{_dn} consecutive down"
            except Exception as _ind_err:
                logging.debug("indicator build for ai_forecast failed: %s", _ind_err)

            # Inject live intraday context so AI knows today's price vs yesterday's close.
            # Only added when there's a meaningful gap (>0.1%) and we have a live price.
            if _live_price and abs(_live_price - price) / price > 0.001:
                _indicators["live_price"] = round(_live_price, 2)
                _indicators["prev_close"] = round(price, 2)
                _indicators["intraday_change_pct"] = round((_live_price - price) / price * 100, 2)

            # Build OHLCV DataFrame for Claude
            try:
                _ohlcv_df = pd.DataFrame({
                    "High":   sh[ticker].dropna(),
                    "Low":    sl[ticker].dropna(),
                    "Close":  sc[ticker].dropna(),
                    "Volume": sv[ticker].dropna() if ticker in sv.columns else pd.Series(dtype=float),
                }).dropna().tail(252)
            except Exception:
                _ohlcv_df = None

            ai_forecast = get_ai_forecast(
                ticker, company, _tf_label, ml,
                nifty_ok, macro_ok, vix_level, news,
                current_price=_ai_current_price,
                indicators=_indicators,
                ohlcv_df=_ohlcv_df,
                mode_c_active=mode_c_active,
                vix_declining=vix_declining,
                market_breadth={
                    "stage2_pct": round(stage2_breadth * 100, 1),
                    "regime":     breadth_regime,
                },
                fii_pcr={
                    "fii_net":    fii_data.get("fii_net"),
                    "dii_net":    fii_data.get("dii_net"),
                    "fii_regime": fii_regime,
                    "pcr":        round(pcr_value, 2) if pcr_value is not None else None,
                },
                fundamentals=fund_data,
                _fast_mode=_ai_fast_mode,
                _fast_fail_on_rate_limit=_ai_fast_fail_on_rate_limit,
            )
        except Exception as _af_err:
            _af_err_msg = str(_af_err)
            logging.warning("ai_forecast skipped for %s: %s", ticker, _af_err)
            # Classify the outage: a provider that is only per-minute rate-limited (or Ollama)
            # will recover shortly, so mark it retryable rather than a hard failure.
            try:
                from llm_client import unavailability_is_recoverable
                _ai_soft_fail = unavailability_is_recoverable()
            except Exception:
                _ai_soft_fail = False

    # AI forecast supersedes the ML directional forecast when it ran successfully.
    # Skip ai_unavailable results — they are not real predictions.
    _ai_real = ai_forecast and ai_forecast.get("source") != "ai_unavailable"
    if _ai_real and ai_forecast.get("direction") in ("BULLISH", "BEARISH", "NEUTRAL"):
        price_forecast["predicted_direction"] = ai_forecast["direction"]
        if ai_forecast.get("predicted_return_lo") is not None:
            price_forecast["predicted_return_lo"] = ai_forecast["predicted_return_lo"]
        if ai_forecast.get("predicted_return_hi") is not None:
            price_forecast["predicted_return_hi"] = ai_forecast["predicted_return_hi"]

    # AI-led mode: for timeframe prediction paths, use AI direction/returns as
    # the primary trade call instead of strategy-gated NO TRADE logic.
    # Do NOT override when AI was unavailable — fall back to no_trade instead.
    # Compute consecutive down days for post-selloff gate (used below regardless of AI)
    _consec_down = 0
    try:
        _close_tail = sc[ticker].dropna().diff().iloc[-5:]
        for _d in reversed(_close_tail.values):
            if _d < 0:
                _consec_down += 1
            else:
                break
    except Exception:
        pass

    if _run_ai_forecast and _ai_real and ai_forecast.get("direction") in ("BULLISH", "BEARISH", "NEUTRAL"):
        direction = ai_forecast["direction"]
        if ai_forecast.get("predicted_return_lo") is not None:
            ret_lo = round(float(ai_forecast["predicted_return_lo"]), 2)
        if ai_forecast.get("predicted_return_hi") is not None:
            ret_hi = round(float(ai_forecast["predicted_return_hi"]), 2)
        # Bear-market gate: Nifty below EMA200 → structural headwind.
        # Downgrade BULLISH → SLIGHTLY BULLISH (not NEUTRAL): top5 accepts SLIGHTLY BULLISH,
        # and the confidence penalty (-3 pts when nifty_ok=False) already filters weak setups.
        # Forcing NEUTRAL blocked all picks even when Nifty is only marginally below EMA200.
        if not nifty_ok and direction == "BULLISH":
            direction = "SLIGHTLY BULLISH"
        # Symmetric bear-market BEARISH gate (3D only): in a confirmed bear market, individual stocks
        # are just as likely to bounce as continue falling — BEARISH calls are 50/50 on NSE.
        # Data: 22/24 3D BEARISH misses on 2026-06-24 had nifty_ok=False (5/5 days below EMA200).
        # Force NEUTRAL for 3D BEARISH when market structure is bearish to avoid coin-flip BEARISH.
        if not nifty_ok and _tf_label == "3D" and direction == "BEARISH":
            direction = "NEUTRAL"
        # Post-selloff BEARISH gate: after 3+ consecutive down days, NSE stocks strongly mean-revert.
        # Data: 29/29 3D BEARISH misses had window_low > entry (stocks bounced after multi-day selloff).
        # Force NEUTRAL — this is valid for all TFs because a falling stock past 3 days tends to bounce.
        if _consec_down >= 3 and direction == "BEARISH":
            direction = "NEUTRAL"

    # Earnings blackout dampens expected return
    if earnings["in_blackout"]:
        ret_lo = round(ret_lo * 0.5, 2)
        ret_hi = round(ret_hi * 0.5, 2)
        direction = "NEUTRAL"  # override during blackout

    midpoint = round((ret_lo + ret_hi) / 2, 2)
    # target_price_lo/hi and expected_target_price are computed later, after
    # entry_price (open-buffer estimate) is finalised, so R:R stays consistent.

    confidence, confidence_breakdown = _calc_confidence(
        sig_result["count"], ml["upgraded"],
        news["label"], nifty_ok, vix_level,
        active_strategies=sig_result["active"],
        vix_declining=vix_declining,
        ml_probability=ml.get("probability", 0.5),
        nifty_trending=nifty_trending,
        qm_score=qm_score,
        stage2_breadth=stage2_breadth,
        fii_regime=fii_regime,
        pcr=pcr_value,
        macro_ok=macro_ok,
    )

    # ── Loophole-based confidence downgrades ──────────────────────────────────
    # Apply loophole penalties to catch and mitigate risky predictions
    loophole_penalty = 0
    loophole_flags = []

    # 1. NO_STRATEGY_SIGNALS: cap at MEDIUM if signals < 2
    if sig_result["count"] < 2 and confidence in ("HIGH", "MEDIUM"):
        confidence = "MEDIUM" if sig_result["count"] > 0 else "LOW"
        loophole_flags.append("NO_STRATEGY_SIGNALS")
        loophole_penalty += 2

    # 2. RSI_OVERBOUGHT: penalize HIGH if RSI > 65
    if confidence == "HIGH" and direction == "BULLISH":
        rsi_val = ml.get("features", {}).get("rsi")
        if rsi_val and rsi_val > 65:
            confidence = "MEDIUM"
            loophole_flags.append("RSI_OVERBOUGHT")
            loophole_penalty += 1
            confidence_breakdown["rsi_overbought"] = -1

    # 3. BELOW_EMA50: downgrade BULLISH if price < EMA50 and RSI not oversold
    if direction == "BULLISH":
        rsi_val = ml.get("features", {}).get("rsi", 50)
        _ema50_raw = sc[ticker].dropna()
        _ema50_val = float(_ema50_raw.ewm(span=50).mean().iloc[-1]) if len(_ema50_raw) >= 50 else None
        if price and _ema50_val and price < _ema50_val and rsi_val >= 30:
            confidence = "LOW"
            loophole_flags.append("BELOW_EMA50")
            loophole_penalty += 2

    # 4. BEARISH_NEWS vs BULLISH_CALL: downgrade if news conflicts strongly
    if direction == "BULLISH" and news.get("score", 0) <= -8 and confidence in ("HIGH", "MEDIUM"):
        confidence = "LOW" if confidence == "MEDIUM" else "MEDIUM"
        loophole_flags.append("BEARISH_NEWS_CONFLICT")
        loophole_penalty += 1
        confidence_breakdown["news_conflict"] = -1

    # 5. UNCERTAIN_ML: penalize if probability near 0.5 (50–50 chance)
    ml_prob = ml.get("probability", 0.5)
    if 0.48 <= ml_prob <= 0.52 and confidence in ("HIGH", "MEDIUM"):
        confidence = "MEDIUM" if confidence == "HIGH" else "LOW"
        loophole_flags.append("UNCERTAIN_ML")
        loophole_penalty += 1
        confidence_breakdown["uncertain_ml"] = -1

    confidence_breakdown["loophole_penalty"] = loophole_penalty
    if loophole_flags:
        confidence_breakdown["loopholes_found"] = loophole_flags

    if _run_ai_forecast:
        if _ai_real and ai_forecast.get("confidence") in ("LOW", "MEDIUM", "HIGH"):
            confidence = ai_forecast["confidence"]
        else:
            confidence = None  # AI unavailable — no_trade_reason drives display, no fake value

    # ── EMA key levels & ATR14 stop loss ─────────────────────────────────────
    c = sc[ticker].dropna()
    h = sh[ticker].dropna()
    lo = sl[ticker].dropna()

    key_levels = {
        "ema20":  round(float(c.ewm(span=20).mean().iloc[-1]), 2),
        "ema50":  round(float(c.ewm(span=50).mean().iloc[-1]), 2) if len(c) >= 50 else None,
        "ema200": round(float(c.ewm(span=200).mean().iloc[-1]), 2) if len(c) >= 200 else None,
    }

    # ATR14-based stop loss, scaled to the holding period.
    # Full 1.5× is calibrated for 5D swing trades; shorter holds use a tighter multiplier
    # so the min R:R target aligns with the shorter predicted return range.
    try:
        atr14_series = atr(h, lo, c, 14)
        atr14_val    = float(atr14_series.iloc[-1])
        # ATR multiplier and R:R target keyed to _tf_label (not raw n_trading)
        # so the 1D weekend-buffer inflation (n_trading=2) doesn't bleed into 3D sizing.
        atr_mult  = {"INTRADAY": 0.4, "1D": 0.7, "3D": 1.1, "5D": 1.5, "1W": 1.8}.get(_tf_label, 1.5)
        sl_risk   = atr_mult * atr14_val
        # Final SL/target/R:R are computed later after entry_price is finalized
        # and with direction-aware logic (LONG vs SHORT).
        sl_price  = None
        sl_pct    = None
        sl_target = None
        actual_rr = None
    except Exception:
        atr14_val = None
        sl_risk   = None
        sl_price  = None
        sl_pct    = None
        sl_target = None
        actual_rr = None

    no_trade_reason = (
        "no_signal"       if sig_result["count"] == 0 else
        "wrong_timeframe" if not _active_for_ev else
        None
    )

    if _run_ai_forecast and _ai_real:
        # In AI-led timeframe prediction mode, expose directional call directly
        # from AI and do not suppress with strategy horizon gates.
        no_trade_reason = None
    elif _run_ai_forecast and not _ai_real:
        # AI was unavailable this pass. The ML forecast already renders instantly beside the
        # AI slot (ML-vs-AI), so the card is never empty — therefore we NEVER emit a terminal
        # 'ai_unavailable'. The AI cell always stays in the retryable 'timeout' state so the
        # frontend keeps refetching and the forecast fills in the moment a provider (or Ollama)
        # frees up. No ML value is substituted into the AI slot; the two stay independent.
        # (_ai_soft_fail is still computed above for logging/diagnostics but no longer gates
        # the reason — even a hard outage is treated as retryable, since providers reset.)
        no_trade_reason = "timeout"

    # NEUTRAL calls have no directional edge — midpoint = 0 → target = entry = current price,
    # making the risk block misleading. Suppress as no-trade regardless of AI availability.
    if direction == "NEUTRAL" and no_trade_reason is None:
        no_trade_reason = "neutral_signal"

    # ── Tight directional band for INTRADAY + 1D (user request 2026-07-30) ───
    # A NARROW band centered on a volatility-scaled expected move so the mean/target is a single
    # clear number (e.g. 1.00%–1.25%), instead of a wide [1.0, 2.0] intraday band or a flat ±1% 1D
    # band. Reshapes ret_lo/ret_hi for BOTH the AI path (already tight from ai_forecast — idempotent)
    # and the strategy/no-AI path (whose _price_forecast bands are wide, e.g. 0.3–0.8%). 3D/5D keep
    # their existing wider bands. Only applies to actionable directional calls.
    if (no_trade_reason is None and _tf_label in _TIGHT_BAND
            and _AI_RANGE_MODE != "containment"
            and direction in ("BULLISH", "SLIGHTLY BULLISH", "BEARISH", "SELL")):
        _atr_pct = ((_indicators.get("atr14") or 0.0) / price * 100.0) if price else 0.0
        _tb = _tight_band_mag(_tf_label, _atr_pct)
        if _tb:
            _lo_mag, _hi_mag = _tb
            if direction in ("BULLISH", "SLIGHTLY BULLISH"):
                ret_lo, ret_hi = _lo_mag, _hi_mag
            else:
                ret_lo, ret_hi = -_hi_mag, -_lo_mag
            midpoint = round((ret_lo + ret_hi) / 2, 2)

    # ── 1D range-only policy (proven direction-ceiling fix) ──────────────────
    # See FORCE_1D_RANGE_ONLY / ONE_D_RANGE_HALF_PCT at module top. 1D next-day DIRECTION caps
    # at ~74% accuracy, so a directional 1D target is unreachable ~1-in-4 times. Convert every
    # 1D call into an honest RANGE-ONLY (NEUTRAL) call with a FLAT ±1% falsifiable band — a real
    # "stays within 1%" claim the user can act on, not a ±5% ATR band that's unbettable. Applied
    # regardless of AI availability. Blocking states (VIX gate, AI timeout, data error) are left
    # untouched; only a directional call or the plain neutral_signal suppression is replaced.
    range_bound = False
    if (FORCE_1D_RANGE_ONLY and _tf_label == "1D"
            and no_trade_reason in (None, "neutral_signal")):
        direction = "NEUTRAL"
        _half_1d = round(ONE_D_RANGE_HALF_PCT, 2)
        ret_lo, ret_hi = -_half_1d, _half_1d
        midpoint = 0.0
        range_bound = True
        no_trade_reason = None  # range-only IS the informative call, not a suppressed no-trade

    # ── Realistic open-price entry estimate ─────────────────────────────────
    # price = yesterday's close. Next-day entry happens at market open, which
    # often gaps. Use a TF-aware buffer so the plan is executable and can also
    # be used as the no-chase threshold at execution time.
    _entry_buffer = ENTRY_BUFFER_BY_TIMEFRAME.get(_tf_label, 0.003)

    # If reversal risk is high (low ML score, low confidence), increase buffer
    # so entry price is lower = more SL margin before hitting max loss.
    _ml_score = ml.get("score", 50)
    if _ml_score < 40 or confidence == "LOW":
        _entry_buffer = _entry_buffer * 1.5  # 50% more conservative
    elif _ml_score < 50:
        _entry_buffer = _entry_buffer * 1.2  # 20% more conservative

    _is_actionable_buy  = direction in ("BULLISH", "SLIGHTLY BULLISH") and no_trade_reason is None
    _is_actionable_sell = direction in ("SELL", "BEARISH")             and no_trade_reason is None
    # When a live price is available (market open / intraday view), 1D/3D now anchor to it just
    # like INTRADAY: the realistic entry is the CURRENT live price and targets/SL are measured
    # from NOW, not from yesterday's close + an open-gap buffer. This keeps a BULLISH target ABOVE
    # the live price on a gap-up day (previously the close-anchored target could render BELOW the
    # shown live price) and matches the AI-forecast targets, which already anchor to the live price.
    # Backtest has no live price (_live_price is None) → falls back to the prior close, so
    # historical behaviour is unchanged.
    _has_live = _live_price is not None and _live_price > 0
    _use_live = _has_live and _tf_label in ("INTRADAY", "1D", "3D")

    # NOTE: a "gapped past target" flag used to be computed here by comparing the live price to a
    # target derived from the PRIOR CLOSE. It was removed because 1D/3D targets are now re-anchored
    # to the live price (see _target_anchor below), so the displayed target always sits ahead of the
    # live price — making a close-anchored "already passed" warning contradict the visible target.
    gapped_past_target = False

    if _use_live:
        entry_price = round(_live_price, 2)
        entry_basis = "live"
    elif _is_actionable_buy:
        entry_price = round(price * (1 + _entry_buffer), 2)
        entry_basis = "est_open_conservative" if _ml_score < 50 else "est_open"
    elif _is_actionable_sell:
        entry_price = round(price * (1 - _entry_buffer), 2)
        entry_basis = "est_open_conservative" if _ml_score < 50 else "est_open"
    else:
        entry_price = round(price, 2)
        entry_basis = "last_close"

    # Recompute targets from the anchor so price-range, SL and R:R are all internally consistent
    # with the achievable entry. Anchor = live price when available (INTRADAY/1D/3D), else the
    # prior close (backtest / market closed).
    _target_anchor = _live_price if _use_live else price
    target_price_lo    = round(_target_anchor * (1 + ret_lo   / 100), 2)
    target_price_hi    = round(_target_anchor * (1 + ret_hi   / 100), 2)
    expected_target_price = round(_target_anchor * (1 + midpoint / 100), 2)

    # For a 1D range-only call, keep the embedded AI-forecast sub-line consistent: no directional
    # arrow, no BUY/SKIP chip, no "Target ₹<current>" — just the NEUTRAL band. Otherwise the
    # secondary AI line (and ML-vs-AI agreement) would still show the LLM's discarded directional
    # bet, contradicting the range-only main call.
    if isinstance(ai_forecast, dict) and ai_forecast.get("source") != "ai_unavailable":
        ai_forecast = dict(ai_forecast)
        if range_bound:
            ai_forecast["direction"] = "NEUTRAL"
            ai_forecast["should_buy"] = None
            ai_forecast["range_bound"] = True
        # ALWAYS keep the AI sub-object's return band + ₹ targets in lockstep with the headline
        # ret_lo/ret_hi/midpoint (same anchor, same band). The frontend rescales the AI range from
        # af.predicted_return_lo/hi but the headline "Target" from midpoint — if those drift apart
        # (e.g. the tight-band reshape updated ret_lo/ret_hi but the AI kept its own slightly
        # different band), the Target renders OUTSIDE the range ("Target ₹1,611" under a
        # ₹1,621–₹1,627 range). Syncing here makes that impossible by construction.
        ai_forecast["predicted_return_lo"] = ret_lo
        ai_forecast["predicted_return_hi"] = ret_hi
        ai_forecast["target_price_lo"] = target_price_lo
        ai_forecast["target_price_hi"] = target_price_hi
        ai_forecast["expected_target_price"] = expected_target_price

    # Recalculate stop-loss from entry_price so risk % and R:R reflect actual cost.
    # SL ALWAYS below entry (max loss level). Direction affects target/gain only.
    if atr14_val and entry_price and sl_risk:
        sl_price = round(entry_price - sl_risk, 2)
        sl_pct = round(sl_risk / entry_price * 100, 1)

        # Target and R:R are direction-aware
        is_short_bias = direction in ("SELL", "BEARISH")
        if is_short_bias:
            # SHORT: gain when price goes DOWN from entry to target_lo
            sl_target = target_price_lo if ret_lo is not None and ret_lo < 0 else None
            _target_gain = (entry_price - target_price_lo) if target_price_lo else 0
        else:
            # LONG: gain when price goes UP from entry to target_hi
            sl_target = target_price_hi if ret_hi is not None and ret_hi > 0 else None
            _target_gain = (target_price_hi - entry_price) if target_price_hi else 0

        actual_rr = round(_target_gain / sl_risk, 1) if sl_risk > 0 and _target_gain > 0 else None

    # If there's no trade setup (no signal), suppress the directional forecast.
    # Don't show BULLISH/BEARISH when there's no actionable setup.
    if no_trade_reason:
        price_forecast = {
            "predicted_direction": None,
            "predicted_return_lo": None,
            "predicted_return_hi": None,
        }
        ai_forecast = None  # Suppress AI forecast direction only when no trade setup
    # ── Phase 6: Price targets (Camarilla / ATR / PDH) ──────────────────────────
    try:
        from price_targets import get_price_targets
        _strategy_bias = "BULLISH" if direction in ("BULLISH", "SLIGHTLY BULLISH") else (
                  "BEARISH" if direction in ("SELL", "BEARISH") else "NEUTRAL")
        price_targets_dict = get_price_targets(ticker, sc, sh, sl, _strategy_bias, confidence)
    except Exception as _pt_err:
        logging.debug("price_targets failed for %s: %s", ticker, _pt_err)
        price_targets_dict = None

    # ── Net-of-cost reality check (price prediction ≠ profitable trading) ──────
    # A predicted move that can't clear NSE round-trip fees is not a tradeable edge
    # (the "tomorrow ≈ today" trap: tiny ±0.07% bands always "hit" but net a loss).
    try:
        from costs import cost_pct_for_timeframe, net_return_pct, clears_costs as _clears
        _cost_pct = cost_pct_for_timeframe(_tf_label)
        _best_case_move = max(abs(ret_lo), abs(ret_hi))  # most favourable bound
        _net_expected = net_return_pct(midpoint, _tf_label)
        _clears_costs = bool(_clears(_best_case_move, _tf_label)) and direction not in ("NEUTRAL", "NO TRADE")
    except Exception:
        _cost_pct, _net_expected, _clears_costs = None, None, None

    _pred_result = {
        "ticker":        ticker,
        "company":       company,
        "start_date":    start_date,
        "end_date":      end_date,
        "trading_days":  n_trading,
        "price":         round(price, 2),
        "round_trip_cost_pct":     _cost_pct,
        "net_expected_return_pct": _net_expected,
        "clears_costs":            _clears_costs,
        "timeframe":     _tf_label,
        "direction":     direction,
        "confidence":    confidence,
        "no_trade_reason": no_trade_reason,
        "range_bound":   range_bound,
        "ai_disclaimer": (
            f"AI unavailable — direction and targets are from strategy/ML math only. Error: {_af_err_msg}"
            if (_run_ai_forecast and _af_err_msg) else None
        ),
        "expected_return_range": f"{ret_lo:+.2f}% to {ret_hi:+.2f}%",
        "ret_lo":        ret_lo,
        "ret_hi":        ret_hi,
        "midpoint":      midpoint,
        "target_price_lo": target_price_lo,
        "target_price_hi": target_price_hi,
        "expected_target_price": expected_target_price,
        "expected_entry_price": entry_price,
        "entry_basis":           entry_basis,
        "entry_buffer_pct":      round(_entry_buffer * 100, 2),
        "max_chase_pct":         round(_entry_buffer * 100, 2),
        "gapped_past_target":    gapped_past_target,
        "predicted_direction":   price_forecast["predicted_direction"],
        "predicted_return_lo":   price_forecast["predicted_return_lo"],
        "predicted_return_hi":   price_forecast["predicted_return_hi"],
        "active_strategies": [] if _run_ai_forecast else sig_result["active"],
        "signal_count":  sig_result["count"],
        "signals":       {} if _run_ai_forecast else sig_result["signals"],
        "signal_errors": [] if _run_ai_forecast else sig_result.get("signal_errors", []),
        "ml": {
            "score":     ml["score"],
            "probability": ml["probability"],
            "upgraded":  ml["upgraded"],
            "features":  ml["features"],
        },
        "news": {
            "label":        news["label"],
            "score":        news["score"],
            "summary":      news["summary"],
            "key_headline": news.get("key_headline", ""),
            "headlines":    news.get("headlines", []),
            "headlines_dated": news.get("headlines_dated", []),
            "latest_date":  news.get("latest_date", ""),
            "source":       news.get("source", "keywords"),
        },
        "earnings":  earnings,
        "key_levels": key_levels,
        "risk": {
            "atr14":        round(atr14_val, 2) if atr14_val else None,
            "stop_loss":    sl_price,
            "stop_loss_pct": sl_pct,
            "min_target":   sl_target,
            "actual_rr":    actual_rr,
        },
        "trade_plan": {
            "expected_entry_price": entry_price,
            "entry_basis":          entry_basis,
            "entry_buffer_pct":     round(_entry_buffer * 100, 2),
            "max_chase_pct":        round(_entry_buffer * 100, 2),
            "gapped_past_target":   gapped_past_target,
            "expected_target_price": expected_target_price,
            "target_price_lo": target_price_lo,
            "target_price_hi": target_price_hi,
            "expected_return_range": f"{ret_lo:+.2f}% to {ret_hi:+.2f}%",
            "stop_loss": sl_price,
            "stop_loss_pct": sl_pct,
            "risk_reward": actual_rr,
            "holding_timeframe": _tf_label,
        },
        "market": {
            "vix_level":   round(vix_level, 1),
            "vix_label":   vix_label,
            "nifty_ok":    nifty_ok,
            "nifty_label": nifty_label,
            "macro_ok":    macro_ok,
            "macro_label": macro_label,
        },
        "confidence_breakdown": confidence_breakdown,
        "market_breadth": {
            "stage2_pct":  round(stage2_breadth * 100, 1),
            "regime":      breadth_regime,
        },
        "fii_pcr": {
            "fii_net":   fii_data.get("fii_net"),
            "dii_net":   fii_data.get("dii_net"),
            "fii_regime": fii_regime,
            "pcr":       round(pcr_value, 2) if pcr_value is not None else None,
        },
        "ai_forecast": ai_forecast,
        "backtest_stats": backtest_stats,
        "mode_c_active": mode_c_active,
        "mode_c_label":  mode_c_label,
        "price_targets": price_targets_dict,
        "intraday":      intraday_dict,
        "sector": {
            "name":     _ticker_sector,
            "leading":  _sector_leading,
            "lagging":  _sector_lagging,
            "rotation": sector_pulse_data.get("rotation_signal") if sector_pulse_data else None,
        },
        "fundamentals": {
            "score":          fund_data.get("fundamental_score") if fund_data else None,
            "pe_relative":    fund_data.get("pe_relative") if fund_data else None,
            "debt_level":     fund_data.get("debt_level") if fund_data else None,
            "revenue_trend":  fund_data.get("revenue_trend") if fund_data else None,
            "roe_pct":        fund_data.get("roe_pct") if fund_data else None,
            "summary":        fund_data.get("summary") if fund_data else None,
        },
        "metadata": {
            "request_id": ctx.request_id,
            "elapsed_ms": int(ctx.elapsed() * 1000),
            "cache_age_days": cache_age_days,
            "data_source": "cached+live" if _skip_fresh_fetch else "fresh_fetch",
        },
    }

    # ── Save prediction snapshot for audit trail ────────────────────────────────
    # Save when AI ran successfully (source="watchlist") or when AI was unavailable
    # but signals exist (source="watchlist_heuristic") — so the validation tab always
    # shows something for stocks that were actually evaluated.
    if _run_ai_forecast and direction not in ("NO TRADE", "HOLD"):
        _snap_source = "watchlist" if _ai_real else "watchlist_heuristic"
        try:
            from database import save_prediction_snapshot
            import json
            save_prediction_snapshot(
                ticker=ticker,
                timeframe=_tf_label,
                direction=direction,
                confidence=confidence,
                target_price_lo=target_price_lo,
                target_price_hi=target_price_hi,
                predicted_return_lo=ret_lo,
                predicted_return_hi=ret_hi,
                current_price=price,
                snapshot_source=_snap_source,
                snapshot_data=json.dumps({
                    "signals_active": sig_result.get("active", []),
                    "ml_score": ml.get("score"),
                    "news_score": news.get("score"),
                    "vix_level": vix_level,
                    "nifty_status": nifty_label,
                    "ai_unavailable": not _ai_real,
                }),
            )
        except Exception as _snap_err:
            logging.debug("Failed to save prediction snapshot for %s: %s", ticker, _snap_err)

    _PRED_CACHE[_pred_key] = {"ts": time.time(), "result": _pred_result}
    return _pred_result


# ── UNIVERSE RANKING ──────────────────────────────────────────────────────────
def rank_stocks_v2(
    start_date: str,
    end_date:   str,
    universe:   Optional[list[str]] = None,
    capital:    Optional[float]     = None,
) -> dict:
    """Rank all stocks in universe for the date range. Returns sorted results dict."""
    _init_universe()
    tickers = list(dict.fromkeys(universe or DEFAULT_UNIVERSE))

    # Return cached result if still fresh (avoids re-scanning 150 stocks on repeated UI hits)
    _cache_key = (start_date, end_date, tuple(tickers), capital)
    _cached = _RANK_CACHE.get(_cache_key)
    if _cached and time.time() - _cached["ts"] < _RANK_CACHE_TTL:
        return _cached["result"]

    vix_level, vix_label   = _get_vix()
    nifty_ok,  nifty_label = _get_nifty_gate()
    macro_ok,  macro_label = _get_macro_gate()

    market_ctx = {
        "vix_level": vix_level, "vix_label": vix_label,
        "nifty_ok": nifty_ok, "nifty_label": nifty_label,
        "macro_ok": macro_ok, "macro_label": macro_label,
    }

    results, errors = [], []

    def _predict_one(t):
        return predict_stock_v2(t, start_date, end_date, _market_ctx=market_ctx)

    # Keep concurrency moderate to avoid memory pressure / kill -9 (137)
    # when multiple expensive scans overlap (dashboard refresh + top5 calls).
    max_workers = min(len(tickers), 8)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_predict_one, t): t for t in tickers}
        for fut in as_completed(futures):
            try:
                pred = fut.result()
            except Exception as exc:
                errors.append(f"{futures[fut]}: {exc}")
                continue
            if "error" in pred:
                errors.append(f"{pred['ticker']}: {pred['error']}")
            else:
                results.append(pred)

    # Sort: NO TRADE last, then by confidence tier, then by midpoint desc
    conf_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "BLOCKED": 9}
    dir_order  = {"BULLISH": 0, "SLIGHTLY BULLISH": 1, "NEUTRAL": 2,
                  "SLIGHTLY BEARISH": 3, "BEARISH": 4, "NO TRADE": 9}
    results.sort(key=lambda x: (
        conf_order.get(x["confidence"], 5),
        dir_order.get(x["direction"], 5),
        -x["midpoint"],
    ))

    for i, r in enumerate(results):
        r["rank"] = i + 1

    # Capital allocation for top bullish picks
    buys = [r for r in results if r["direction"] in ("BULLISH", "SLIGHTLY BULLISH") and r["confidence"] != "BLOCKED"]
    if capital and capital > 0 and buys:
        top = buys[:6]
        per = round(capital / len(top), 0)
        for p in top:
            p["suggested_allocation"] = per
            shares = int(per / p["price"]) if p.get("price") and p["price"] > 0 else 0
            p["suggested_shares"]  = shares
            p["allocation_value"]  = round(shares * p["price"], 2)

    out = {
        "start_date":    start_date,
        "end_date":      end_date,
        "capital":       capital,
        "total_scanned": len(tickers),
        "total_scored":  len(results),
        "errors":        errors,
        "ranked":        results,
        "market": {
            "vix_level":   round(vix_level, 1),
            "vix_label":   vix_label,
            "nifty_ok":    nifty_ok,
            "nifty_label": nifty_label,
            "macro_ok":    macro_ok,
            "macro_label": macro_label,
        },
    }
    _RANK_CACHE[_cache_key] = {"ts": time.time(), "result": out}
    return out


# ── SMOKE TEST ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Running smoke test on RELIANCE.NS...")
    p = predict_stock_v2("RELIANCE.NS", "2026-06-15", "2026-06-30")
    print(f"Direction   : {p['direction']}")
    print(f"Confidence  : {p['confidence']}")
    print(f"Expected    : {p['expected_return_range']}")
    print(f"Signals     : {p['active_strategies']} ({p['signal_count']} active)")
    print(f"ML Score    : {p['ml']['score']}/100  prob={p['ml']['probability']}")
    print(f"News        : {p['news']['label']} ({p['news']['source']})")
    print(f"Earnings    : {p['earnings']}")
    print(f"Market VIX  : {p['market']['vix_label']}")
    print(f"Nifty Gate  : {p['market']['nifty_label']}")
    print("SMOKE TEST PASSED")
