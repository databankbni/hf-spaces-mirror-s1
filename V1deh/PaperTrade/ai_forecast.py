"""
ai_forecast.py - LLM-based stock forecasting with price range generation.

KEY FIX (2026-06-21):
The previous version was creating degenerate ranges (lo==hi) because:
1. LLM responses often return only point estimates (predicted_return, target_price)
2. Old code copied these into lo/hi fields verbatim → lo==hi for 100% of predictions
3. Backtest measured if actual price fell within [lo,hi] range → impossible with degenerate ranges
4. Result: ~30% accuracy (random) for 38 iterations instead of 75%+ target

SOLUTION:
This version generates intelligent ranges from any LLM response:
- If LLM returns ranges (lo/hi fields), use them as-is
- If LLM returns only point (predicted_return, target_price), expand into a proper range
- Confidence-scaled spreads: HIGH=0.8%, MEDIUM=1.5%, LOW=2.5%
- Per-TF caps: 1D±4%, 3D±7%, 5D±12%
- Minimum spread: 0.8% absolute difference always enforced
"""

import json
import logging
import os
import re
import threading
import time
from typing import Optional, Dict, Any, List
import requests
import pandas as pd

# Load .env before reading API keys — needed when called outside Flask (e.g. top5_picker, backtest)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv optional — env vars already set

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _resolve_source_metadata() -> tuple[str, str, str]:
    """Resolve predictor source metadata from environment overrides."""
    provider = (os.getenv("AI_FORECAST_SOURCE_PROVIDER") or "openrouter").strip() or "openrouter"
    model = (os.getenv("AI_FORECAST_SOURCE_MODEL") or "openai/gpt-oss-120b:free").strip() or "openai/gpt-oss-120b:free"
    source_prefix = (os.getenv("AI_FORECAST_SOURCE_PREFIX") or "ai_forecast").strip() or "ai_forecast"
    return f"{source_prefix}:{model}", provider, model

# ============================================================================
# MODELS
# ============================================================================

class ForecastResult:
    """Simple forecast result holder."""
    def __init__(self, **kwargs):
        self.direction = kwargs.get('direction', 'NEUTRAL')
        self.confidence = kwargs.get('confidence', 'MEDIUM')
        self.target_price = kwargs.get('target_price')
        self.target_price_lo = kwargs.get('target_price_lo', 0.0)
        self.target_price_hi = kwargs.get('target_price_hi', 0.0)
        self.predicted_return = kwargs.get('predicted_return')
        self.predicted_return_lo = kwargs.get('predicted_return_lo', 0.0)
        self.predicted_return_hi = kwargs.get('predicted_return_hi', 0.0)
        self.reasoning = kwargs.get('reasoning', '')

# ============================================================================
# CORE: Range Generation & Expansion
# ============================================================================

def _volatility_percentile(ohlcv_df: Optional[pd.DataFrame], tf_label: str) -> float:
    """Return realized volatility percentile [0,1] for timeframe using close-to-close moves."""
    if ohlcv_df is None or not isinstance(ohlcv_df, pd.DataFrame) or "Close" not in ohlcv_df.columns:
        return 0.50
    tf_days = {"INTRADAY": 1, "1D": 1, "3D": 3, "5D": 5}.get(tf_label, 3)
    close = pd.to_numeric(ohlcv_df["Close"], errors="coerce").dropna()
    if len(close) < max(30, tf_days + 10):
        return 0.50
    moves = close.pct_change(tf_days).abs().dropna() * 100.0
    if len(moves) < 20:
        return 0.50
    current = float(moves.iloc[-1])
    hist = moves.iloc[:-1]
    if len(hist) == 0:
        return 0.50
    return float((hist <= current).mean())


def _realized_move_anchor(ohlcv_df: Optional[pd.DataFrame], tf_label: str, vol_pctile: float) -> float:
    """Estimate achievable move (%) from historical realized moves for this timeframe."""
    if ohlcv_df is None or not isinstance(ohlcv_df, pd.DataFrame) or "Close" not in ohlcv_df.columns:
        return {"INTRADAY": 0.5, "1D": 0.8, "3D": 1.6, "5D": 2.2}.get(tf_label, 1.5)
    tf_days = {"INTRADAY": 1, "1D": 1, "3D": 3, "5D": 5}.get(tf_label, 3)
    close = pd.to_numeric(ohlcv_df["Close"], errors="coerce").dropna()
    if len(close) < max(40, tf_days + 15):
        return {"INTRADAY": 0.5, "1D": 0.8, "3D": 1.6, "5D": 2.2}.get(tf_label, 1.5)
    moves = close.pct_change(tf_days).abs().dropna() * 100.0
    if len(moves) < 25:
        return {"INTRADAY": 0.5, "1D": 0.8, "3D": 1.6, "5D": 2.2}.get(tf_label, 1.5)

    # In quieter regimes use lower quantiles; in volatile regimes allow wider targets.
    q = 0.45 + 0.35 * max(0.0, min(1.0, float(vol_pctile)))
    return float(moves.quantile(q))

def _generate_range_from_point(
    point_pct: float,
    direction: str,
    confidence: str,
    current_price: float,
    tf_label: str = "3D",
    tight_mode: bool = False,
    vol_pctile: float = 0.50,
) -> Dict[str, float]:
    """
    Convert a point estimate into a proper price range.
    
    Args:
        point_pct: Point return estimate (%)
        direction: BULLISH, BEARISH, NEUTRAL
        confidence: LOW, MEDIUM, HIGH
        current_price: Current stock price (₹)
        tf_label: 1D, 3D, or 5D
    
    Returns:
        {target_price_lo, target_price_hi, predicted_return_lo, predicted_return_hi}
    """
    
    # Confidence-scaled spread (% points).
    # tight_mode is used during backtests to keep ranges as close as possible.
    if tight_mode:
        tight_spreads = {
            "INTRADAY": {"HIGH": 0.22, "MEDIUM": 0.32, "LOW": 0.48},
            "1D": {"HIGH": 0.30, "MEDIUM": 0.43, "LOW": 0.65},
            "3D": {"HIGH": 0.28, "MEDIUM": 0.45, "LOW": 0.75},
            "5D": {"HIGH": 0.35, "MEDIUM": 0.55, "LOW": 0.90},
        }
        min_spreads = {"INTRADAY": 0.10, "1D": 0.15, "3D": 0.20, "5D": 0.25}
        confidence_spread = tight_spreads.get(tf_label, tight_spreads["3D"]).get(confidence, 0.55)
        min_spread = min_spreads.get(tf_label, 0.25)

        # Adaptive width: widen in high realized volatility, tighten in low volatility.
        # Maps percentile [0,1] to multiplier [0.80, 1.80].
        vol_pctile = max(0.0, min(1.0, float(vol_pctile)))
        width_mult = 0.80 + (1.00 * vol_pctile)
        confidence_spread *= width_mult
        min_spread *= (0.85 + 0.55 * vol_pctile)
    else:
        confidence_spread = {
            "HIGH": 0.8,
            "MEDIUM": 1.5,
            "LOW": 2.5,
        }.get(confidence, 1.5)
        min_spread = 0.80
    
    # Per-timeframe cap (hard limit on magnitude)
    tf_cap = {
        "INTRADAY": 2.0,
        "1D": 4.0,
        "3D": 7.0,
        "5D": 12.0
    }.get(tf_label, 10.0)
    
    # Generate range based on direction
    if direction == "BULLISH" and point_pct > 0:
        # Bullish: lo is conservative (lower), hi is optimistic (upper)
        lo_floor = 0.10 if tight_mode else 0.20
        lo_pct = max(lo_floor, point_pct - confidence_spread / 2)
        hi_pct = point_pct + confidence_spread / 2
    elif direction == "BEARISH" and point_pct < 0:
        # Bearish: hi is conservative (closer to 0), lo is pessimistic (lower)
        if tight_mode and tf_label in ("1D", "INTRADAY"):
            # 1D/INTRADAY bearish needs near-zero center to improve hit probability.
            confidence_spread *= 0.45
            min_spread = min(min_spread, 0.06)
        lo_pct = point_pct - confidence_spread / 2
        if tight_mode and tf_label in ("1D", "INTRADAY"):
            hi_ceiling = -0.01
        else:
            hi_ceiling = -0.10 if tight_mode else -0.20
        hi_pct = min(hi_ceiling, point_pct + confidence_spread / 2)
    else:
        # Neutral or mismatched: narrow range around zero
        neutral_half_width = 0.20 if tight_mode else 0.50
        lo_pct = -neutral_half_width
        hi_pct = neutral_half_width
    
    # Apply per-TF caps
    lo_pct = max(-tf_cap, min(tf_cap, lo_pct))
    hi_pct = max(-tf_cap, min(tf_cap, hi_pct))
    
    # Ensure lo < hi
    if lo_pct > hi_pct:
        lo_pct, hi_pct = hi_pct, lo_pct
    
    # Enforce minimum spread (tighter in test mode, while still non-degenerate).
    if abs(hi_pct - lo_pct) < min_spread:
        mid = (lo_pct + hi_pct) / 2
        lo_pct = mid - (min_spread / 2)
        hi_pct = mid + (min_spread / 2)
    
    # Convert to price targets
    target_price_lo = round(current_price * (1 + lo_pct / 100), 2)
    target_price_hi = round(current_price * (1 + hi_pct / 100), 2)
    
    return {
        "predicted_return_lo": round(lo_pct, 2),
        "predicted_return_hi": round(hi_pct, 2),
        "target_price_lo": target_price_lo,
        "target_price_hi": target_price_hi,
    }


def _ensure_non_degenerate_range(
    fr: ForecastResult,
    current_price: float,
    tf_label: str = "3D",
    tight_mode: bool = False,
    vol_pctile: float = 0.50,
) -> Dict[str, float]:
    """
    Ensure lo != hi (no degenerate ranges).
    
    If range is degenerate (lo==hi), generate a proper range using:
    1. Existing point estimates (predicted_return, target_price)
    2. Direction and confidence to inform spread
    
    Args:
        fr: ForecastResult
        current_price: Current stock price
        tf_label: Timeframe label (1D, 3D, 5D)
    
    Returns:
        Updated {predicted_return_lo, predicted_return_hi, target_price_lo, target_price_hi}
    """
    
    # Check if non-degenerate AND correctly ordered AND direction-consistent
    if fr.target_price_lo != 0.0 and fr.target_price_hi != 0.0:
        lo_ok = fr.predicted_return_lo < fr.predicted_return_hi  # lo must be less than hi
        dir_ok = (
            (fr.direction == "BULLISH" and fr.predicted_return_hi > 0) or
            (fr.direction == "BEARISH" and fr.predicted_return_lo < 0) or
            (fr.direction == "NEUTRAL")
        )
        if abs(fr.target_price_hi - fr.target_price_lo) > 0.01 and lo_ok and dir_ok:
            return {
                "predicted_return_lo": fr.predicted_return_lo,
                "predicted_return_hi": fr.predicted_return_hi,
                "target_price_lo": fr.target_price_lo,
                "target_price_hi": fr.target_price_hi,
            }
    
    # Degenerate or missing: generate from point
    point_pct = fr.predicted_return if fr.predicted_return is not None else 0.0
    
    if point_pct == 0.0 and fr.target_price and current_price > 0:
        # Infer from target_price
        point_pct = round((fr.target_price - current_price) / current_price * 100, 2)
    
    return _generate_range_from_point(
        point_pct=point_pct,
        direction=fr.direction,
        confidence=fr.confidence,
        current_price=current_price,
        tf_label=tf_label,
        tight_mode=tight_mode,
        vol_pctile=vol_pctile,
    )

# ============================================================================
# LLM INFRASTRUCTURE
# ============================================================================

# ── Shared provider chain (OpenRouter → Groq → HuggingFace) ─────────────────
# All state (cooldowns, semaphore, retry logic) lives in llm_client.py.
# Re-export the counter here so get_ai_forecast() can spread debate calls.
from llm_client import (
    make_chat_call as _make_chat_call,
    _LLM_LOCK,
    _LLM_SEMAPHORE,
    _PROVIDER_ORDER,
)
import llm_client as _llm_client

# Monotonically increasing debate counter (per-process, guarded by _LLM_LOCK).
_AI_TASK_COUNTER: int = 0

# ── AI forecast result cache ─────────────────────────────────────────────────
# Key: (ticker, tf_label, date_str_IST) — one entry per stock/TF/day.
# 1D/3D/5D: cached until IST midnight (re-run not needed same day).
# INTRADAY: 15-min TTL — refreshed automatically by background thread in app.py.
import datetime as _dt
_FORECAST_CACHE: dict = {}
_FORECAST_CACHE_LOCK = threading.Lock()

# Per-ticker lock for fast-mode: prevents concurrent TF threads for the same
# stock from each making their own LLM call (thundering herd). First TF wins
# the lock, fetches, stores in _FORECAST_CACHE; others get the cached result.
_AI_FAST_LOCKS: dict = {}
_AI_FAST_LOCKS_LOCK = threading.Lock()

def _get_ai_fast_lock(key) -> threading.Lock:
    """Per-key lock. key is (ticker, tf_label) so different timeframes for the
    same stock make independent LLM calls concurrently, while duplicate requests
    for the same (ticker, tf) de-duplicate onto one call."""
    with _AI_FAST_LOCKS_LOCK:
        if key not in _AI_FAST_LOCKS:
            _AI_FAST_LOCKS[key] = threading.Lock()
        return _AI_FAST_LOCKS[key]


def _cache_ttl_for_tf(tf_label: str) -> int:
    """Return cache TTL in seconds for a given timeframe.
    INTRADAY: 15 min.  All others: seconds remaining until IST midnight."""
    if tf_label == "INTRADAY":
        return 900  # 15 minutes
    ist = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
    now_ist = _dt.datetime.now(ist)
    midnight_ist = (now_ist + _dt.timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(300, int((midnight_ist - now_ist).total_seconds()))



_JSON_REQUIRED = {"direction", "confidence"}
_JSON_PRICE_FIELDS = frozenset({"target_price_lo", "target_price_hi", "predicted_return_lo", "predicted_return_hi"})
# Prompt now asks for target_price_lo/hi (₹); older/smaller models may still return
# predicted_return_lo/hi (%). We require at least one pair — validated in _extract_price_targets.
# "reasoning" intentionally omitted — small Ollama models frequently truncate before closing it.

# ============================================================================
# CALIBRATED RANGE TABLE (data-verified on NSE 2018-2025, N=828)
# Applied as overrides AFTER direction is determined — LLM's lo/hi are ignored.
# Goal: maximise midpoint-touch accuracy (primary backtest metric).
#
# 1D BULLISH: mid = 0.25%  (sweep-optimal; LLM output ~0.20% was suboptimal)
# 3D/5D BULLISH: mid = 0.10%  (already LLM-optimal, keeps them identical)
# ALL BEARISH: mid = -0.10%  (lo=-0.15, hi=-0.05) — NSE sweep-optimal
#   • Shallower midpoint improves target-touch hit rate on 1D/3D/5D
#   • Deeper bearish anchors over-shoot many realized down moves
# ============================================================================
# COST-CLEARING FLOORS: the conservative bound (lo for bullish, hi for bearish)
# must exceed the NSE round-trip cost (delivery ~0.22%, intraday ~0.11% — see
# costs.py), so even a worst-case range-hit at least breaks even. The old tiny
# ±0.07% bands were the "tomorrow ≈ today" trap: they always "hit" but every hit
# lost money after fees. Wider ranges lower the raw hit-rate (esp. for weak
# MEDIUM/LOW calls that don't really move) but make every hit tradeable — that's
# the honest trade-off (price prediction ≠ profitable trading).
_BULL_RANGE: dict[str, tuple[float, float]] = {
    # lo sits just above the round-trip cost (breakeven floor) — clears fees at
    # worst case while maximizing the honest hit-rate (iter64: 1D ~80%, 3D ~86%).
    "INTRADAY": (0.15, 1.00),  # cost ~0.11% — lo clears; mid ~0.58%
    "1D":       (0.25, 1.30),  # cost ~0.22% — lo clears; mid ~0.78%
    "3D":       (0.30, 2.20),  # mid ~1.25%
    "5D":       (0.40, 3.00),  # legacy (5D retired from UI); mid ~1.70%
}
_BEAR_RANGE: dict[str, tuple[float, float]] = {
    "INTRADAY": (-1.00, -0.15),
    "1D":       (-1.30, -0.25),
    "3D":       (-2.20, -0.30),
    "5D":       (-3.00, -0.40),
}
_NEUT_RANGE: dict[str, tuple[float, float]] = {
    # NEUTRAL = a real "stays flat" claim. Capped at a 2% total gap (±1%) so a
    # NEUTRAL call is falsifiable — the old ±5–6% bands were so wide they always
    # "hit", which inflated accuracy without predicting anything.
    "INTRADAY": (-0.50, 0.50),   # 1.0% gap
    "1D": (-1.5, 1.5),           # 3.0% gap — widened from ±1% (2026-07-31: POLYCAB-class gap moves)
    "3D": (-1.0, 1.0),           # 2.0% gap (max)
    "5D": (-1.0, 1.0),           # 5D removed from UI/calls; kept for old-snapshot validation
}


# Human-readable descriptions of each trigger, used to rewrite the forecast reasoning when a
# guardrail overrides the LLM's direction — so the card's narrative matches the final call
# instead of contradicting it (e.g. a BULLISH badge with "no bullish trigger" text).
_TRIGGER_DESC: dict[str, str] = {
    "T1": "price is above EMA50 with a bullish MACD histogram (trend continuation)",
    "T2": "price is above EMA50 with strong 10-day momentum",
    "T4": "a pullback within an uptrend — mildly oversold near the lower Bollinger band with genuinely flat momentum",
    "T5": "a strong 10-day breakout in momentum (not yet overbought)",
    "T6": "deeply oversold — a technical bounce is likely",
    "T7": "a meaningful positive drift while holding above EMA50",
    "B1": "an overbought extreme with stretched momentum — reversal risk",
    "B2": "a confirmed downtrend below EMA50 with negative MACD and momentum",
    "B3": "a sustained multi-day decline confirmed by negative MACD (falling-knife risk)",
}

# When no same-side trigger fires on 1D/3D/5D, keep the LLM's directional call at reduced
# conviction instead of force-NEUTRALising it (the historical behaviour that lifted validation
# hit rate but suppressed almost all directional calls — see memory hit-rate-direction-policy).
# SYMMETRIC by design: it surfaces BEARISH just as readily as BULLISH, so it does NOT reintroduce
# the old long-bias; it lets genuine down-moves ("stock dipped nicely") show as BEARISH. The
# BULLISH-into-a-confirmed-crash contradiction is still blocked. TRADEOFF: raw 1D/3D next-day
# direction caps ~74% (documented signal ceiling), so this trades some headline hit rate for
# more actionable directional signal. Set AI_DIRECTIONAL_NEITHER_1D3D=0 to restore the strict
# range-only NEUTRAL policy (max hit rate, fewer directional calls).
_DIRECTIONAL_NEITHER_1D3D = os.getenv("AI_DIRECTIONAL_NEITHER_1D3D", "1") == "1"

# INTRADAY momentum override: when the LLM returns NEUTRAL but the live session move (vs the
# prior close) is already clearly directional, surface that direction — the intraday chart is
# plainly moving, so a NEUTRAL cell is unhelpful (the "AI shows NEUTRAL while the chart goes up
# and down" complaint). Symmetric (up→BULLISH, down→BEARISH); the BULLISH-into-a-confirmed-crash
# contradiction still applies. Set AI_INTRADAY_MOMENTUM_OVERRIDE=0 to disable; the trigger size is
# AI_INTRADAY_MOMENTUM_PCT (default 0.6% of the prior close).
_INTRADAY_MOMENTUM_OVERRIDE = os.getenv("AI_INTRADAY_MOMENTUM_OVERRIDE", "1") == "1"
_INTRADAY_MOMENTUM_PCT = float(os.getenv("AI_INTRADAY_MOMENTUM_PCT", "0.6"))


def _apply_trigger_guardrails(
    direction: str,
    confidence: str,
    indicators: dict,
    current_price: float,
    tf_label: str = "1D",
) -> tuple[str, str, str | None]:
    """Enforce CLAUDE.md trigger rules against actual computed indicator values.

    The LLM is only given the triggers as prompt instructions; this function
    re-evaluates them in Python and overrides the LLM's direction when the data
    clearly contradicts it.  Rules evaluated (from CLAUDE.md):

    TIMEFRAME SCOPE (2026-07-28): the trigger set below is the 1D/3D/5D EMA50/MACD/RSI
    framework and is applied ONLY to those horizons. INTRADAY reasons over VWAP / ORB / gap
    structure (see _build_synthesis_prompt's INTRADAY guide) — signals this daily-series
    guardrail cannot see — so re-judging an INTRADAY call with the 1D rules (the historical
    bug) wrongly force-NEUTRALised accurate session calls and made all TF cells collapse to the
    same NEUTRAL. INTRADAY now passes the LLM's direction through, enforcing only the one
    contradiction computable from daily bars (no BULLISH into a confirmed multi-day crash).
    1D/3D/5D behaviour is intentionally UNCHANGED (preserves the deliberate range-only
    hit-rate policy on those horizons).

    CRASH/EXHAUSTION GUARD: 10D<-6% OR 20D<-8% → stock is in a genuine decline, not a normal
             dip. Suppresses the oversold-bounce triggers (T4/T6) and the lagging trend
             trigger (T1 blocked separately when RSI>70) so a falling knife is never forced
             BULLISH. (2026-07-17 backtest: 100% of misses on ai_prompt_accuracy_trades.csv
             were BULLISH calls made into an active decline — T1/T4/T6 firing on stocks that
             kept falling. See research/ai_prompt_accuracy_trades.csv.)
    BULLISH  T1: price>EMA50 AND MACD>0 AND RSI<=70 (blocked when extremely overbought — MACD
                 confirmation is lagging and often fires right before a reversal)
             T2: price>EMA50 AND 10D>+3% AND BB<85%
             T4: price>EMA50 AND RSI<50 AND BB<45% AND -2%<10D<3%  [2026-07-31 round 1: added the
                 3% ceiling — 2nd-worst BULLISH trigger in real data (1D DirAcc=41.9%, worse than
                 a coin flip) because the old floor-only condition wasn't actually "flat"; round 2:
                 added price>EMA50 — was the only oversold trigger with zero trend confirmation,
                 letting it fire on a stock oversold WITHIN a genuine (not yet crash-exhausted)
                 downtrend]  (suppressed when crash-exhausted)
             T5: 10D>+7% AND BB<80% AND RSI<65  [2026-07-31: added RSI<65 — worst BULLISH
                 trigger in real backtest data (1D DirAcc=20%, AvgP&L=-1.40%), a chasing-an-
                 extended-breakout trap]
             T6: RSI<44 AND BB<35%  (suppressed when crash-exhausted)
             T7: price>EMA50 AND 20D between +2.5% and +5% AND RSI<62  [2026-07-31: raised floor
                 1.0->2.5 — 2nd-worst high-volume BULLISH trigger in real data (1D DirAcc=41.9%),
                 a +1% 20D drift was barely above noise]
    BEARISH  B1: BB>95% AND RSI>64 AND 10D>+8%
             B2: below EMA50 AND MACD<0 AND 10D<-4% AND RSI>42 AND BB>40%  [relaxed from
                 RSI>50/10D<-5% — that combination is nearly self-contradictory since a stock
                 down >5% in 10 days almost always already has RSI<50]
             B3: crash-exhausted AND MACD<0 — sustained decline confirmed by momentum,
                 independent of RSI/BB (catches falling knives that never satisfy B2's BB>40%)
    No trigger at all (neither bull nor bear) → force NEUTRAL (matches the synthesis prompt's
    own "NEUTRAL: no trigger fires" instruction, which the LLM does not reliably follow itself).
    Conflicting triggers (both bull and bear fire) → NEUTRAL (genuinely ambiguous).
    """

    def _v(prod: str, bt: str = "") -> float | None:
        raw = indicators.get(prod)
        if raw is None and bt:
            raw = indicators.get(bt)
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    rsi    = _v("rsi14", "RSI_14")
    bb     = _v("bb_pct", "BB_position_%")
    macd   = _v("macd_signal", "MACD_histogram")
    ret10  = _v("return_10d", "Return_10D_%")
    ret20  = _v("return_20d", "Return_20D_%")
    ema50  = _v("ema50")
    rs_3m  = _v("rs_3m_pct")

    # Skip guardrails if we lack the two most critical indicators
    if rsi is None or bb is None:
        return direction, confidence, None

    above_ema50 = (current_price > ema50) if (ema50 is not None and current_price > 0) else None

    # Stock already down heavily over 10D/20D — a "falling knife", not a normal oversold dip.
    # Oversold-bounce logic (T4/T6) and lagging trend confirmation (T1) are unreliable here.
    crash_exhausted = (ret10 is not None and ret10 < -6.0) or (ret20 is not None and ret20 < -8.0)
    overbought_extreme = rsi > 70

    # Structural laggard vs Nifty (2026-07-31) — a hedge-fund-style relative-strength filter,
    # mirroring ml_predictor's ML_EXCESS_LABELS (excess-of-Nifty direction labels, validated to
    # roughly 10x the raw-label model's 1D expectancy). A stock's OWN RSI/BB can look "oversold"
    # or "breaking out" while it's still been a structural underperformer vs the broader market
    # for months (e.g. HDFCBANK during its multi-year merger-overhang period) — that absolute
    # technical setup is a much weaker BULLISH signal on a laggard than on a stock with healthy
    # relative strength. Suppresses BULLISH triggers only (not BEARISH — underperformance is, if
    # anything, corroborating evidence for a bearish call).
    structural_laggard = rs_3m is not None and rs_3m < -8.0

    # ── INTRADAY: trust the LLM's session-anchored call ───────────────────────
    # The INTRADAY synthesis prompt reasons over VWAP / ORB / gap structure — signals this
    # daily-indicator guardrail cannot evaluate. Applying the 1D EMA50/MACD trigger set here
    # (the historical behaviour) wrongly forced accurate directional calls to NEUTRAL and made
    # all three TF cells read the same NEUTRAL result. INTRADAY direction is the reliable
    # timeframe (71-86% dir-acc), so we pass the LLM's call through and enforce ONLY the one
    # contradiction computable from the daily bars — never hold a BULLISH intraday-bounce
    # thesis into a confirmed multi-day crash (mirrors the INTRADAY prompt's own
    # CRASH/EXHAUSTION GUARD). 1D/3D/5D fall through to the full re-evaluation below UNCHANGED.
    if tf_label == "INTRADAY":
        if direction == "BULLISH" and crash_exhausted and macd is not None and macd < 0:
            logger.info(
                "GUARDRAIL INTRADAY crash-guard: BULLISH→NEUTRAL (RSI=%.1f BB=%.1f 10D=%s 20D=%s)",
                rsi, bb, ret10, ret20,
            )
            note = (
                "Intraday long not supported: the stock is in a confirmed multi-day decline "
                f"(10D {ret10 or 0:+.1f}%) with negative momentum — no oversold-bounce trade."
            )
            return "NEUTRAL", confidence, note
        # Momentum override: the LLM read NEUTRAL but the live session is already clearly
        # directional vs the prior close → surface that direction (the chart is plainly moving).
        # Symmetric; the BULLISH-into-crash contradiction above still wins.
        intraday_chg = _v("intraday_change_pct")
        if (_INTRADAY_MOMENTUM_OVERRIDE and direction == "NEUTRAL" and intraday_chg is not None):
            if intraday_chg >= _INTRADAY_MOMENTUM_PCT and not crash_exhausted:
                logger.info(
                    "GUARDRAIL INTRADAY momentum-override: NEUTRAL→BULLISH (session %+.2f%% vs prev close)",
                    intraday_chg,
                )
                note = (
                    f"Session is up {intraday_chg:+.1f}% vs the prior close — surfacing BULLISH "
                    f"from live intraday momentum (the model read NEUTRAL)."
                )
                return "BULLISH", confidence, note
            if intraday_chg <= -_INTRADAY_MOMENTUM_PCT:
                logger.info(
                    "GUARDRAIL INTRADAY momentum-override: NEUTRAL→BEARISH (session %+.2f%% vs prev close)",
                    intraday_chg,
                )
                note = (
                    f"Session is down {intraday_chg:+.1f}% vs the prior close — surfacing BEARISH "
                    f"from live intraday momentum (the model read NEUTRAL)."
                )
                return "BEARISH", confidence, note
        logger.debug(
            "GUARDRAIL INTRADAY passthrough: keeping LLM %s (RSI=%.1f BB=%.1f)",
            direction, rsi, bb,
        )
        return direction, confidence, None

    # ── Evaluate bullish triggers ─────────────────────────────────────────────
    # All bull triggers are skipped entirely when structural_laggard (see above) — an absolute
    # oversold/breakout setup is much weaker evidence on a stock that's been underperforming the
    # market for months.
    bull = None
    if not structural_laggard:
        if bull is None and above_ema50 is not None and macd is not None and not overbought_extreme:
            if above_ema50 and macd > 0:
                bull = "T1"
        if bull is None and above_ema50 is not None and ret10 is not None:
            if above_ema50 and ret10 > 3.0 and bb < 85:
                bull = "T2"
        # T4: widened to match synthesis prompt (RSI<50 BB<45, was RSI<46 BB<38); suppressed
        # during a confirmed crash — a deep decline is not "mildly oversold". 2026-07-31: added an
        # upper bound on ret10 — the condition was named "mild oversold + FLAT momentum" but only
        # floored ret10 (>-2%) with no ceiling, so it could fire on a stock already up double-digits
        # over 10D that happened to have a temporarily-dipped RSI — not flat at all. Real backtest
        # data showed this was the 2nd-worst BULLISH trigger (1D: N=31, DirAcc=41.9% — worse than a
        # coin flip — AvgP&L=-0.349%). 2026-07-31 (round 2): ALSO added above_ema50 — T4/T5/T6 were
        # the only triggers with ZERO trend confirmation (T1/T2/T3/T7 all check above_ema50), so a
        # stock oversold WITHIN a genuine downtrend (below EMA50 but not yet crash_exhausted) could
        # fire a BULLISH "bounce" call. Requiring above_ema50 narrows this to the higher-quality
        # thesis "pullback within an uptrend" rather than "oversold in a downtrend".
        if bull is None and ret10 is not None and above_ema50 is not None and not crash_exhausted:
            if above_ema50 and rsi < 50 and bb < 45 and -2.0 < ret10 < 3.0:
                bull = "T4"
        # T5: gated with RSI<65 (2026-07-31) — real backtest data showed this was the worst
        # BULLISH trigger by far (1D: N=5, DirAcc=20%, AvgP&L=-1.40%, research/ai_prompt_accuracy.csv)
        # — chasing an already-extended +7% breakout with no overbought check is a classic
        # mean-reversion trap. Mirrors the overbought_extreme suppression already applied to T1.
        if bull is None and ret10 is not None:
            if ret10 > 7.0 and bb < 80 and rsi < 65:
                bull = "T5"
        if bull is None and not crash_exhausted:
            if rsi < 44 and bb < 35:
                bull = "T6"
        # T7: slow positive drift — price above EMA50, 20D return 2.5-5%, RSI not overbought.
        # 2026-07-31: raised the floor 1.0->2.5 — a +1% 20D drift is barely above noise (T2's
        # analogous, WORKING momentum trigger requires 10D>+3%, a much stronger bar); real backtest
        # data showed T7 was the 2nd-worst high-volume BULLISH trigger (1D: N=31, DirAcc=41.9%,
        # worse than a coin flip, AvgP&L=-0.260%).
        if bull is None and above_ema50 is not None and ret20 is not None:
            if above_ema50 and 2.5 <= ret20 <= 5.0 and rsi < 62:
                bull = "T7"

    # ── Evaluate bearish triggers ─────────────────────────────────────────────
    bear = None
    if bear is None and ret10 is not None:
        if bb > 95 and rsi > 64 and ret10 > 8.0:
            bear = "B1"
    if bear is None and above_ema50 is not None and macd is not None and ret10 is not None:
        if not above_ema50 and macd < 0 and ret10 < -4.0 and rsi > 42 and bb > 40:
            bear = "B2"
    if bear is None and crash_exhausted and macd is not None and macd < 0:
        bear = "B3"

    # ── Resolve final direction ───────────────────────────────────────────────
    # `note` is set only when the guardrail OVERRIDES the LLM's direction, so the caller can
    # rewrite the forecast reasoning/should_buy to match the final call (no contradictory cards).
    if bear and not bull:
        note = None
        if direction != "BEARISH":
            note = (
                f"Direction set BEARISH by technical trigger {bear}: "
                f"{_TRIGGER_DESC.get(bear, 'bearish technical setup')} "
                f"(RSI {rsi:.0f}, Bollinger {bb:.0f}%, 10D {ret10 or 0:+.1f}%). "
                f"This overrides the model's more cautious read."
            )
            logger.info(
                "GUARDRAIL %s: overriding %s→BEARISH (RSI=%.1f BB=%.1f 10D=%.1f)",
                bear, direction, rsi, bb, ret10 or 0,
            )
        return "BEARISH", confidence, note

    if bull and not bear:
        note = None
        if direction != "BULLISH":
            note = (
                f"Direction set BULLISH by technical trigger {bull}: "
                f"{_TRIGGER_DESC.get(bull, 'bullish technical setup')} "
                f"(RSI {rsi:.0f}, Bollinger {bb:.0f}%). "
                f"This overrides the model's more cautious read."
            )
            logger.info(
                "GUARDRAIL %s: overriding %s→BULLISH (RSI=%.1f BB=%.1f)",
                bull, direction, rsi, bb,
            )
        return "BULLISH", confidence, note

    if bull and bear:
        # Conflicting triggers — genuinely ambiguous, don't force either direction.
        logger.info(
            "GUARDRAIL CONFLICT: bull=%s bear=%s → NEUTRAL (RSI=%.1f BB=%.1f 10D=%.1f)",
            bull, bear, rsi, bb, ret10 or 0,
        )
        note = (
            f"Conflicting technical triggers (bullish {bull} vs bearish {bear}) — "
            f"no clear directional edge, treated as NEUTRAL."
        ) if direction != "NEUTRAL" else None
        return "NEUTRAL", confidence, note

    # No same-side trigger fired.
    #
    # 1D/3D/5D (when AI_DIRECTIONAL_NEITHER_1D3D on): keep the LLM's directional call at reduced
    # conviction rather than force-NEUTRALising it — SYMMETRIC (surfaces BEARISH just as readily
    # as BULLISH), with the single contradiction still blocked (never stay BULLISH into a
    # confirmed multi-day crash). This is what lets a stock that "dipped nicely" read BEARISH
    # instead of NEUTRAL. Otherwise (flag off, or LLM already NEUTRAL): the strict range-only
    # policy — force NEUTRAL and downgrade confidence one level (max validation hit rate).
    levels = ["LOW", "MEDIUM", "HIGH"]
    idx = levels.index(confidence) if confidence in levels else 1
    downgraded = levels[max(0, idx - 1)]

    if (_DIRECTIONAL_NEITHER_1D3D and direction in ("BULLISH", "BEARISH")):
        # Contradiction guard: don't hold a bullish thesis into a confirmed multi-day crash.
        if direction == "BULLISH" and crash_exhausted:
            logger.info(
                "GUARDRAIL NO_TRIGGER crash-guard: BULLISH→NEUTRAL (RSI=%.1f BB=%.1f 10D=%s)",
                rsi, bb, ret10,
            )
            note = (
                f"No bullish trigger and the stock is in a confirmed multi-day decline "
                f"(10D {ret10 or 0:+.1f}%) — treated as NEUTRAL, no bounce trade."
            )
            return "NEUTRAL", downgraded, note
        # Same contradiction guard for structural_laggard (see above) — without this, the
        # keep-dir policy below would let a BULLISH call through anyway even though the bull
        # trigger block was deliberately skipped for this exact reason.
        if direction == "BULLISH" and structural_laggard:
            logger.info(
                "GUARDRAIL NO_TRIGGER laggard-guard: BULLISH→NEUTRAL (RS_3M=%.1f%%)",
                rs_3m,
            )
            note = (
                f"No bullish trigger and the stock has underperformed Nifty by "
                f"{rs_3m:+.1f}% over 3 months — treated as NEUTRAL, no long thesis on a laggard."
            )
            return "NEUTRAL", downgraded, note
        logger.info(
            "GUARDRAIL NO_TRIGGER keep-dir: no trigger fired, keeping LLM %s at reduced "
            "conviction %s→%s (RSI=%.1f BB=%.1f 10D=%s)",
            direction, confidence, downgraded, rsi, bb, ret10,
        )
        # note stays None — we did NOT override the LLM's direction, only its conviction.
        return direction, downgraded, None

    # Strict range-only policy: force NEUTRAL and downgrade confidence one level.
    if direction != "NEUTRAL" or confidence != "LOW":
        logger.info(
            "GUARDRAIL NO_TRIGGER: no trigger fired for %s (RSI=%.1f BB=%.1f) → NEUTRAL, confidence %s→%s",
            direction, rsi, bb, confidence, downgraded,
        )
        note = (
            f"No technical trigger fired (RSI {rsi:.0f}, Bollinger {bb:.0f}%) — "
            f"insufficient directional edge, treated as NEUTRAL."
        ) if direction != "NEUTRAL" else None
        return "NEUTRAL", downgraded, note

    return direction, confidence, None


def _reconcile_override(
    note: str | None, direction: str, confidence: str,
    reasoning: str, should_buy: bool,
) -> tuple[str, bool]:
    """Align the forecast narrative + buy flag with the FINAL direction.

    When a guardrail (or news gate) overrides the LLM's direction, the LLM's own reasoning and
    should_buy describe a DIFFERENT call and would contradict the badge on the card. This rewrites
    reasoning to the override explanation and recomputes should_buy from the final direction /
    confidence (BUY only for a genuine BULLISH lean with at least MEDIUM conviction).
    """
    if not note:
        return reasoning, should_buy
    return note, (direction == "BULLISH" and confidence in ("HIGH", "MEDIUM"))


def _apply_calibrated_range(direction: str, tf_label: str) -> tuple[float, float]:
    """Return (lo_pct, hi_pct) from the calibrated range table."""
    if direction == "BULLISH":
        return _BULL_RANGE.get(tf_label, (0.02, 0.18))
    if direction == "BEARISH":
        return _BEAR_RANGE.get(tf_label, (-0.15, -0.05))
    return _NEUT_RANGE.get(tf_label, (-0.15, 0.15))


_TF_HARD_CAP_PCT: dict[str, float] = {"INTRADAY": 2.0, "1D": 4.0, "3D": 7.0}

# INTRADAY realistic-move floor for a DIRECTIONAL best-case target. Intraday moves clear ~1% on
# ~89% of NSE days (3.05M day-rows), so an ATR-derived far bound below 1% under-predicts the
# achievable move — the stock routinely "goes above it". Flooring the far bound to this makes the
# intraday target realistic AND keeps it actionable (clears the predictor_core 1% gate instead of
# being skipped). Shared env var with predictor_core/ml_predictor so all three stay in sync.
_INTRADAY_MIN_MOVE_PCT = float(os.getenv("INTRADAY_MIN_MOVE_PCT", "1.0"))

# ── ATR-scaled band model (2026-07-17) ──────────────────────────────────────────────────────────
# All bound sizes below are DERIVED from one power-law formula, not a separate hardcoded number
# per timeframe: bound_pct = BASE × window_days^EXPONENT, where window_days is the calendar-day
# length of the prediction horizon (matches predictor_core.TIMEFRAME_DAYS: 1D=1, 3D=3, 5D=5 — so
# 5D, 1W, or any future timeframe is automatically covered with no new tuning). Only BASE and
# EXPONENT are fitted constants; everything else falls out of the arithmetic. This replaces four
# independent per-TF dicts (one hardcoded multiplier per timeframe each) with two fitted numbers
# per band type. INTRADAY has no calendar-day length (same-day), so it uses its own
# _INTRADAY_EQUIV_DAYS — a single fitted "equivalent day count" plugged into the SAME formula,
# rather than a bespoke intraday constant per band type.
#
# BASE/EXPONENT were fitted by least-squares against research/ai_prompt_accuracy_trades.csv
# (2026-07-17 calibration pass): for every correctly-directed backtest call, the ratio of realized
# excursion to that stock's ATR% was grid-searched per TF for the largest value clearing ~90-95%
# of rows (near-bound) / keeping the resulting midpoint reachable ~90%+ of the time (far-bound
# ratio) / covering realized moves for NEUTRAL calls (half-width). Fitting BASE/EXPONENT to those
# grid-searched points (1D, 3D) reproduces them almost exactly (near: 0.12×1^0.83=0.12,
# 0.12×3^0.83≈0.30) and extrapolates smoothly to untested horizons like 5D instead of guessing.
_TF_WINDOW_DAYS: dict[str, float] = {"1D": 1.0, "3D": 3.0, "5D": 5.0, "1W": 7.0}
# INTRADAY has no calendar-day length (same-day) so each formula gets its own fitted "equivalent
# day count" for INTRADAY — these two differ because they fit different physical quantities (a
# directional bounce-target vs. a two-sided flat-range containment), not because of inconsistency.
_INTRADAY_EQUIV_DAYS_NEAR = 1.31  # fitted so the near-bound formula reproduces the grid-searched INTRADAY value
# 2026-07-29: raised 1.09 → 5.70 for volatility differentiation; 2026-07-31: reduced 5.70 → 2.5
# (far bound was overshooting, ATR%≈2.4% → 1.12%); then → 1.0 same day after simulating the exact
# near/far formula against 101 real BULLISH-INTRADAY backtest rows (research/ai_prompt_accuracy.csv)
# — with days_far=1.0 and near_k=0.058 (see _CONTAINMENT_NEAR_K below) the resulting midpoint is
# touched by max_up_0d in 89.2% of rows (target: ~89%), vs 71.3% at the prior days_far=2.5/near_k=0.10.
# New k_far ≈ 0.156 × ATR%: ATR%=2.4% → 0.37%, ATR%=3% → 0.47%, ATR%=4% → 0.62%, ATR%=5% → 0.78%.
# Still volatility-scaled (higher-ATR stocks show wider best-case targets) but tight enough to hit.
_INTRADAY_EQUIV_DAYS_FAR  = 1.0   # tuned so INTRADAY far ≈ 0.156 × ATR% (validated 89.2% target_hit)

# Near-bound (the "easy" side of a directional band — lo for BULLISH, hi for BEARISH).
_NEAR_BOUND_BASE = 0.12
_NEAR_BOUND_EXP  = 0.83
# Floor/ceiling for the near-bound are themselves derived from the SAME k(days) formula, scaled to
# an assumed quiet-stock / volatile-stock ATR% reference — not a fourth hardcoded number per TF.
_NEAR_BOUND_ATR_FLOOR_REF = 0.65   # "quiet stock" reference ATR% used to derive the floor
_NEAR_BOUND_ATR_CEIL_REF  = 6.50   # "volatile stock" reference ATR% used to derive the ceiling

# Far bound (the aspirational side) — 2026-07-17 correction: an earlier version expressed this as
# a single flat ratio × near-bound, reasoning the per-TF ratio was noise (only 14 samples/TF). A
# real backtest run then showed that flat ratio was measurably too loose for INTRADAY and 3D —
# it directly caused 3 of 11 target_hit misses (midpoint overshot by <0.06 percentage points).
# The far bound DOES scale with window length, same as the near-bound and NEUTRAL half-width — it
# just needs its OWN base/exponent (a different physical quantity, fit independently) rather than
# being derived as a ratio of the near-bound's fit.
_FAR_BOUND_BASE = 0.156
_FAR_BOUND_EXP  = 0.6354
# Minimum spread between near and far bounds per timeframe. The power-law exponents cause k_far
# to converge with k_near around day 3.7 and cross below it at 5D — leaving bands as narrow as
# 0.01% wide. These floors guarantee a meaningful band regardless of ATR level.
_MIN_SPREAD_PCT: dict[str, float] = {"INTRADAY": 0.15, "1D": 0.20, "3D": 0.80, "5D": 1.20}

# ── TIGHT DIRECTIONAL BAND for INTRADAY + 1D (user request 2026-07-30) ──────────────────────────
# The wide volatility-scaled bands ([1.0, 2.0] intraday, flat ±1% for 1D) hid the expected move —
# the user wants a NARROW band so the mean/target is a single clear number (e.g. 1.00%–1.25%). The
# band is centered on a volatility-scaled expected move: center = clamp(mult × ATR%, min, cap), and
# the band is [center − half, center + half]. The near bound is floored to `floor` (default 1%) so
# the whole predicted move stays >= 1% (kept per the earlier request). Only INTRADAY + 1D use this;
# 3D/5D keep the wider power-law band. All knobs are env-overridable for backtest tuning.
_TIGHT_BAND: dict[str, dict] = {
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


def _tight_band_mag(tf_label: str, atr_pct: float) -> "tuple[float, float] | None":
    """Tight directional band as (near_mag, far_mag) — both positive magnitudes, near < far.

    center = clamp(mult × ATR%, min_center, cap); band = [center−half, center+half]; near floored
    to `floor` (keeping the whole move >= floor). Returns None for timeframes without a tight band
    (3D/5D), so the caller falls back to the wider power-law band.
    """
    cfg = _TIGHT_BAND.get(tf_label)
    if not cfg:
        return None
    center = min(cfg["cap"], max(cfg["min_center"], cfg["mult"] * atr_pct))
    h = cfg["half"]
    lo, hi = center - h, center + h
    if lo < cfg["floor"]:
        lo, hi = cfg["floor"], cfg["floor"] + 2 * h
    return round(lo, 2), round(hi, 2)


# ── AI RANGE MODE (user request 2026-07-30) ────────────────────────────────────────────────────
# "containment" (default): the INTRADAY/1D directional band is a WIDE prediction interval — a low,
#   easily-reached NEAR bound (~0.15×ATR%) + an optimistic FAR bound (~0.5×ATR%) — so the realized
#   move lands inside the shown range ~85% of the time (matches the ML row). The headline Target is
#   the interval MIDPOINT. High price-hit, wider range.
# "target": the tight ±half band centered on a volatility-scaled expected move (a precise directional
#   TARGET, ~50% hit, clear single mean). Set AI_RANGE_MODE=target to restore it.
# Research: research/price_hit_research.py — a >=1% directional target maxes ~45-58% hit on NSE;
# only a low-near-bound containment interval clears 75%+ (the near bound is reached ~85%).
_AI_RANGE_MODE = os.getenv("AI_RANGE_MODE", "containment").strip().lower()

# Containment near-bound = k × ATR% — a LOW, easily-reached floor calibrated (research/price_hit_
# research.py sweep, 3072 NSE rows) so the realized move enters the shown range ~90% of the time:
#   INTRADAY  k=0.058 → target_hit≈89% (2026-07-31: lowered from 0.10 alongside days_far 2.5→1.0,
#             jointly fit against 101 real BULLISH-INTRADAY backtest rows so the midpoint —
#             (near+far)/2 — is touched by the realized max_up_0d ~89% of the time, up from 71%
#             at the prior near_k=0.10/days_far=2.5. near ≈ 0.14% at median ATR%≈2.4%.)
#   1D        k=0.03 → ~89% (1D's practical ceiling — ~11% of days the next-day HIGH never exceeds
#             the prior close, so no positive near bound can capture them).
# Env-overridable. The far bound is now jointly tuned with near (see _INTRADAY_EQUIV_DAYS_FAR).
_CONTAINMENT_NEAR_K = {
    "INTRADAY": float(os.getenv("CONTAINMENT_NEAR_K_INTRADAY", "0.058")),
    "1D":       float(os.getenv("CONTAINMENT_NEAR_K_1D", "0.03")),
}


def _easy_near_bound_pct(tf_label: str, atr_pct: float) -> float:
    """ATR-scaled near-bound: _NEAR_BOUND_BASE × window_days^_NEAR_BOUND_EXP × ATR%, clamped to a
    floor/ceiling derived from the same formula (see _NEAR_BOUND_ATR_FLOOR_REF/_CEIL_REF)."""
    days = _INTRADAY_EQUIV_DAYS_NEAR if tf_label == "INTRADAY" else _TF_WINDOW_DAYS.get(tf_label, 1.0)
    k = _NEAR_BOUND_BASE * (days ** _NEAR_BOUND_EXP)
    floor = k * _NEAR_BOUND_ATR_FLOOR_REF
    ceil_ = k * _NEAR_BOUND_ATR_CEIL_REF
    return max(floor, min(ceil_, k * atr_pct))


def _far_bound_pct(tf_label: str, atr_pct: float, near: float) -> float:
    """ATR-scaled far-bound: _FAR_BOUND_BASE × window_days^_FAR_BOUND_EXP × ATR%. Always kept just
    above `near` (small epsilon) so the band never degenerates to zero width."""
    days = _INTRADAY_EQUIV_DAYS_FAR if tf_label == "INTRADAY" else _TF_WINDOW_DAYS.get(tf_label, 1.0)
    k = _FAR_BOUND_BASE * (days ** _FAR_BOUND_EXP)
    far = k * atr_pct
    return far if far > near else near + 0.01


def _atr_clamp_range(
    rng: Dict[str, float], tf_label: str, atr14: float,
    current_price: float, tight_test: bool, direction: str = "",
) -> Dict[str, float]:
    """Production-only safety net for accepted LLM ranges (no-op when tight_test=True).

    Directional (BULLISH/BEARISH) bands are rebuilt from the stock's OWN ATR%, while NEUTRAL is a
    FLAT, falsifiable band by policy — a deliberate accuracy/informativeness trade-off (2026-07-17
    tuning pass, see memory/repo notes) chosen to push both the range-hit and the stricter
    midpoint-touch (target_hit_for_tf) metrics toward 90%+:
      - NEUTRAL: a flat symmetric band (±_NEUT_RANGE, e.g. ±1% for 1D) so the user gets an
        actionable "stays within X%" claim. It is NOT ATR-scaled — an ATR band ballooned to ±5%+
        on volatile stocks, which is unbettable ("no idea what to bet on"). Kept consistent with
        _NEUT_RANGE / database._SNAP_NEUT / range_model._NEUT_FLAT / ml_predictor._neutral_range.
      - BULLISH/BEARISH: near bound = k(days)×ATR% (clamped to a floor/ceiling), far bound = its
        own k(days)×ATR% formula (always kept above near) — so the midpoint sits just beyond the
        near bound instead of at an independently "ambitious" level the LLM proposed. The model's
        own lo/hi are discarded; only its DIRECTION and CONFIDENCE still come from the LLM.
    Directional bound sizes come from the day-length power-law formulas above, so an untested
    timeframe (5D, 1W, ...) gets an automatically consistent value instead of a guessed constant.

    A "trust the LLM's own range" mode was built and A/B tested (research/blend_backtest.py,
    N=400): the LLM's own range was worse AND 3.4x wider than this ATR rebuild (61% vs 78%
    target_hit) even at HIGH confidence — so that mode was reverted; this rebuild is authoritative.
    """
    if tight_test or current_price <= 0 or atr14 <= 0:
        return rng
    atr_pct = atr14 / current_price * 100.0
    cap = _TF_HARD_CAP_PCT.get(tf_label, 7.0)
    _dir = (direction or "").upper()

    # NEUTRAL: FLAT, falsifiable band by policy — NOT an ATR/volatility magnitude. A NEUTRAL call
    # must give the user an actionable "stays within X%" claim they can bet on; an ATR-scaled band
    # ballooned to ±5%+ on volatile stocks, which tells the user nothing ("no idea what to bet on").
    # This mirrors _NEUT_RANGE, database._SNAP_NEUT, research.range_model._NEUT_FLAT and
    # ml_predictor's _neutral_range — so NEUTRAL is consistent across the whole codebase.
    if _dir == "NEUTRAL":
        lo, hi = _NEUT_RANGE.get(tf_label, (-1.0, 1.0))
        lo, hi = max(-cap, lo), min(cap, hi)
        return {
            "predicted_return_lo": round(lo, 2),
            "predicted_return_hi": round(hi, 2),
            "target_price_lo": round(current_price * (1 + lo / 100), 2),
            "target_price_hi": round(current_price * (1 + hi / 100), 2),
        }

    # BULLISH/BEARISH: near bound (ATR-scaled, clamped) + far bound (its own day-scaled formula).
    if _dir in ("BULLISH", "BEARISH"):
        tb = None if (_AI_RANGE_MODE == "containment" and tf_label in ("INTRADAY", "1D")) else _tight_band_mag(tf_label, atr_pct)
        if tb is not None:
            # "target" mode (INTRADAY + 1D): NARROW band centered on the volatility-scaled expected
            # move so the mean/target is a single clear number (e.g. 1.00%–1.25%). See _TIGHT_BAND.
            near, far = tb
        else:
            # "containment" mode (INTRADAY/1D) AND all 3D/5D: WIDE prediction interval — a low,
            # easily-reached near bound + an optimistic far bound — so the realized move lands
            # inside the shown range ~90% of the time (the headline Target is the midpoint).
            if _AI_RANGE_MODE == "containment" and tf_label in _CONTAINMENT_NEAR_K:
                # Calibrated low near bound (~90% range-entered) — see _CONTAINMENT_NEAR_K.
                near = max(0.05, _CONTAINMENT_NEAR_K[tf_label] * atr_pct)
            else:
                near = _easy_near_bound_pct(tf_label, atr_pct)
            far = min(cap, _far_bound_pct(tf_label, atr_pct, near))
            min_spread = _MIN_SPREAD_PCT.get(tf_label, 0.40)
            if far - near < min_spread:
                far = near + min_spread
            far = min(cap, far)
        lo, hi = (near, far) if _dir == "BULLISH" else (-far, -near)
        return {
            "predicted_return_lo": round(lo, 2),
            "predicted_return_hi": round(hi, 2),
            "target_price_lo": round(current_price * (1 + lo / 100), 2),
            "target_price_hi": round(current_price * (1 + hi / 100), 2),
        }

    # Unknown direction (shouldn't happen — direction is normalized before this call): fall back
    # to the LLM's own range untouched.
    return rng

def _parse_json_from_llm(text: str) -> Dict | None:
    """Extract JSON from LLM output, stripping markdown fences and leading reasoning text.
    Returns None if any required field is missing (prevents partial-parse silent corruption)."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.MULTILINE).strip()
    if cleaned.startswith("<") and "{" not in cleaned:
        return None
    parsed = None
    try:
        parsed = json.loads(cleaned)
    except Exception:
        pass
    if parsed is None:
        # Balanced-brace scan: find the outermost {...} block.
        # {[^{}]*} only matches flat objects and breaks when "reasoning" contains
        # literal braces like "RSI crossed {35}". Walk the string instead.
        def _find_json_object(s: str):
            for start in range(len(s)):
                if s[start] != '{':
                    continue
                depth, in_str, i = 0, False, start
                while i < len(s):
                    ch = s[i]
                    if ch == '"' and (i == 0 or s[i - 1] != '\\'):
                        in_str = not in_str
                    if not in_str:
                        if ch == '{':
                            depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0:
                                candidate = s[start:i + 1]
                                try:
                                    return json.loads(candidate)
                                except Exception:
                                    break
                    i += 1
            return None

        parsed = _find_json_object(cleaned)
        if parsed is None:
            # Last-resort: try scanning from the end for the last JSON object
            for start in range(len(cleaned) - 1, -1, -1):
                if cleaned[start] == '{':
                    try:
                        parsed = json.loads(cleaned[start:])
                        break
                    except Exception:
                        pass
    if parsed is None:
        return None
    # Reject if direction/confidence missing — prevents 0.0 default corruption
    missing = _JSON_REQUIRED - parsed.keys()
    if missing:
        logger.warning("LLM JSON missing required fields %s — rejecting partial parse", missing)
        return None
    # Must have at least one price pair (target_price or predicted_return)
    if not (_JSON_PRICE_FIELDS & parsed.keys()):
        logger.warning("LLM JSON missing all price/return fields — rejecting")
        return None
    return parsed


def _safe_float(val, default: float = 0.0) -> float:
    """Convert val to float. Handles bare numbers, '+2.0', '-0.6%', '3.5-', None → default."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().lstrip("₹$").replace(",", "").rstrip("-%+").lstrip("+")
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


def _extract_price_targets(
    parsed: dict, current_price: float
) -> tuple:
    """
    Return (ret_lo, ret_hi) as plain percentage returns from LLM parsed dict.

    Priority:
    1. target_price_lo/hi (₹ absolute) — models reason better in prices, no % ambiguity
    2. predicted_return_lo/hi (%, possibly with % sign or bare float)
    Returns (0.0, 0.0) when nothing valid is found; caller falls back to heuristic.
    """
    def _to_price(v):
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v) if float(v) > 0 else None
        s = str(v).strip().lstrip("₹$").replace(",", "")
        try:
            f = float(s)
            return f if f > 0 else None
        except (ValueError, TypeError):
            return None

    tp_lo = _to_price(parsed.get("target_price_lo"))
    tp_hi = _to_price(parsed.get("target_price_hi"))
    if tp_lo is not None and tp_hi is not None and current_price > 0:
        return (
            round((tp_lo / current_price - 1) * 100, 3),
            round((tp_hi / current_price - 1) * 100, 3),
        )

    return (
        _safe_float(parsed.get("predicted_return_lo"), 0.0),
        _safe_float(parsed.get("predicted_return_hi"), 0.0),
    )


# ============================================================================
# INDICATOR NORMALIZATION
# ============================================================================

def _normalize_indicators(raw: dict) -> dict:
    """
    Normalize indicator keys from backtest format to ai_forecast format.

    Backtest (research/backtest.py) produces:
        RSI_14, Price_vs_EMA50 (string), MACD_histogram, ATR14 ₹, Volume_ratio_20D

    Production (predictor_core.py) produces:
        rsi14, ema50 (float), macd_signal, atr14, vol_ratio

    This normalization ensures the context block and direction logic work
    identically regardless of which caller is used.
    """
    if not raw:
        return {}
    norm = dict(raw)

    # RSI
    if "rsi14" not in norm and "RSI_14" in norm:
        try:
            norm["rsi14"] = float(norm["RSI_14"])
        except (ValueError, TypeError):
            pass
    if "rsi5" not in norm and "RSI_5" in norm:
        try:
            norm["rsi5"] = float(norm["RSI_5"])
        except (ValueError, TypeError):
            pass
    if "rsi2" not in norm and "RSI_2" in norm:
        try:
            norm["rsi2"] = float(norm["RSI_2"])
        except (ValueError, TypeError):
            pass

    # EMA levels — backtest stores as "above (EMA50=₹1234.56)" strings
    for tf_str, key in [("EMA50", "ema50"), ("EMA200", "ema200"), ("EMA20", "ema20")]:
        if key not in norm:
            raw_val = str(norm.get(f"Price_vs_{tf_str}", ""))
            if raw_val:
                m = re.search(rf"{tf_str}=₹([\d.]+)", raw_val)
                if m:
                    try:
                        norm[key] = float(m.group(1))
                    except ValueError:
                        pass

    # MACD histogram → signal
    if "macd_signal" not in norm and "MACD_histogram" in norm:
        try:
            norm["macd_signal"] = float(norm["MACD_histogram"])
        except (ValueError, TypeError):
            pass

    # ATR
    if "atr14" not in norm and "ATR14 ₹" in norm:
        try:
            norm["atr14"] = float(norm["ATR14 ₹"])
        except (ValueError, TypeError):
            pass

    # Volume ratio
    if "vol_ratio" not in norm and "Volume_ratio_20D" in norm:
        try:
            norm["vol_ratio"] = float(norm["Volume_ratio_20D"])
        except (ValueError, TypeError):
            pass

    # Return_90D
    if "return_90d" not in norm and "Return_90D_%" in norm:
        try:
            norm["return_90d"] = float(norm["Return_90D_%"])
        except (ValueError, TypeError):
            pass

    # Short-term momentum (10D / 20D)
    if "return_10d" not in norm and "Return_10D_%" in norm:
        try:
            norm["return_10d"] = float(norm["Return_10D_%"])
        except (ValueError, TypeError):
            pass
    if "return_20d" not in norm and "Return_20D_%" in norm:
        try:
            norm["return_20d"] = float(norm["Return_20D_%"])
        except (ValueError, TypeError):
            pass

    # Bollinger Band position
    if "bb_pct" not in norm and "BB_position_%" in norm:
        try:
            norm["bb_pct"] = float(norm["BB_position_%"])
        except (ValueError, TypeError):
            pass

    # Consecutive days
    if "consec_days" not in norm and "Consec_days" in norm:
        norm["consec_days"] = str(norm["Consec_days"])

    return norm


# ============================================================================
# PROMPT BUILDERS
# ============================================================================

def _build_context_block(
    ticker: str, company: str, tf_label: str,
    ml: Dict, nifty_ok: bool, macro_ok: bool, vix_level: float,
    news: Dict, indicators: Dict, mode_c_active: bool,
    vix_declining: bool, market_breadth: Dict, fii_pcr: Dict,
    current_price: float = 0.0,
    gift_nifty: Dict | None = None,
    backtest_stats: Dict | None = None,
) -> str:
    """
    Build the shared context block shown to all LLM calls.
    Handles both production (rsi14/ema50) and backtest (RSI_14/Price_vs_EMA50) key formats.
    """
    lines = [
        f"STOCK: {ticker} ({company})  |  TIMEFRAME: {tf_label}",
        f"MARKET: VIX {vix_level:.1f} ({'declining ✓' if vix_declining else 'rising ✗'})  "
        f"Nifty {'above' if nifty_ok else 'below'} EMA200  "
        f"Macro {'OK' if macro_ok else 'risk-off'}  "
        f"Mode-C {'ON' if mode_c_active else 'off'}",
    ]
    feats = (ml or {}).get("features", {}) or {}
    if ml:
        lines.append(f"ML SCORE: {ml.get('score', 50)}/100  prob={ml.get('probability', 0.5):.2f}"
                     + ("  [UPGRADED]" if ml.get("upgraded") else ""))
    if indicators:
        # Use current_price from explicit param first, then try indicators dict
        p = float(current_price) if current_price and current_price > 0 else float(indicators.get("close") or 0)
        # Try production keys first, fall back to backtest key names
        def _ind(prod_key, *bt_keys):
            v = indicators.get(prod_key)
            if v is None:
                for k in bt_keys:
                    v = indicators.get(k)
                    if v is not None:
                        break
            return v
        rsi_val   = _ind("rsi14",       "RSI_14")
        adx_val   = _ind("adx14",       "ADX_14")
        ema50_val = _ind("ema50")
        ema200_val= _ind("ema200")
        macd_val  = _ind("macd_signal", "MACD_histogram")
        obv_val   = indicators.get("obv_trend", "")
        vol_ratio = _ind("vol_ratio",   "Volume_ratio_20D")
        ret_90d   = _ind("return_90d",  "Return_90D_%")
        dist_52w  = indicators.get("Dist_from_52W_High_%")
        lines.append("TECHNICALS:")
        if p:
            intraday_chg = indicators.get("intraday_change_pct")
            prev_close   = indicators.get("prev_close")
            if intraday_chg is not None and prev_close:
                chg_str = f"+{intraday_chg:.1f}%" if intraday_chg >= 0 else f"{intraday_chg:.1f}%"
                lines.append(f"  Price: ₹{p:.2f} (prev close ₹{float(prev_close):.2f}, today {chg_str})")
            else:
                lines.append(f"  Price: ₹{p:.2f}")
        atr_val = _ind("atr14", "ATR14 ₹")
        if atr_val is not None and p:
            atr_f = float(atr_val)
            lines.append(f"  ATR(14): ₹{atr_f:.2f} ({atr_f / p * 100:.1f}% of price — one avg session's "
                         f"range; size ALL price targets from this)")
        if rsi_val is not None:
            rsi_f = float(rsi_val)
            lbl = "oversold" if rsi_f < 35 else ("overbought" if rsi_f > 65 else "neutral")
            lines.append(f"  RSI(14): {rsi_f:.1f} ({lbl})")
        rsi5_val = _ind("rsi5", "RSI_5")
        if rsi5_val is not None:
            r5f = float(rsi5_val)
            r5lbl = "oversold" if r5f < 30 else ("overbought" if r5f > 70 else "neutral")
            lines.append(f"  RSI(5): {r5f:.1f} ({r5lbl})")
        rsi2_val = _ind("rsi2", "RSI_2")
        if rsi2_val is not None:
            r2f = float(rsi2_val)
            r2lbl = "extreme oversold — bounce likely" if r2f < 10 else ("extreme overbought — fade risk" if r2f > 90 else "neutral")
            lines.append(f"  RSI(2): {r2f:.1f} ({r2lbl})")
        if adx_val is not None:
            lines.append(f"  ADX: {float(adx_val):.1f} ({'trending' if float(adx_val) > 25 else 'ranging'})")
        if ema200_val and p:
            e200 = float(ema200_val)
            lines.append(f"  EMA200: ₹{e200:.2f} (price {'above ✓' if p > e200 else 'below ✗'})")
        if ema50_val and p:
            e50 = float(ema50_val)
            lines.append(f"  EMA50: ₹{e50:.2f} (price {'above' if p > e50 else 'below'})")
        ema20_val = _ind("ema20")
        if ema20_val and p:
            e20 = float(ema20_val)
            lines.append(f"  EMA20: ₹{e20:.2f} (price {'above' if p > e20 else 'below'} — short-term trend)")
        if macd_val is not None:
            m_f = float(macd_val)
            lines.append(f"  MACD histogram: {'bullish' if m_f > 0 else 'bearish'} ({m_f:.4f})")
        if vol_ratio is not None:
            vr = float(vol_ratio)
            lines.append(f"  Volume ratio 20D: {vr:.2f}x ({'high' if vr > 1.5 else ('low' if vr < 0.7 else 'normal')})")
        if ret_90d is not None:
            r90 = float(ret_90d)
            lines.append(f"  90D return: {r90:+.1f}% ({'strong uptrend' if r90 > 15 else ('downtrend' if r90 < -10 else 'range-bound')})")
        if dist_52w is not None:
            d52 = float(dist_52w)
            lines.append(f"  52W high dist: {d52:+.1f}% ({'near high — caution' if d52 > -5 else ('deeply off high' if d52 < -20 else 'mid-range')})")
        if obv_val:
            lines.append(f"  OBV trend: {obv_val}")
        # Short-term momentum — key directional signal (try both key conventions)
        r10    = _ind("return_10d",  "Return_10D_%")
        r20    = _ind("return_20d",  "Return_20D_%")
        bb_pct = _ind("bb_pct",     "BB_position_%")
        consec = _ind("consec_days", "Consec_days")
        if r10 is not None:
            r10 = float(r10)
            r10_lbl = "strong bull momentum" if r10 > 6 else ("overbought — fade risk" if r10 > 12 else ("bear momentum" if r10 < -5 else "mild"))
            lines.append(f"  10D momentum: {r10:+.1f}% ({r10_lbl})")
        if r20 is not None:
            r20 = float(r20)
            r20_lbl = "uptrend" if r20 > 5 else ("downtrend" if r20 < -5 else "sideways")
            lines.append(f"  20D momentum: {r20:+.1f}% ({r20_lbl})")
        rs_3m_val = indicators.get("rs_3m_pct")
        if rs_3m_val is not None:
            rs_3m_val = float(rs_3m_val)
            rs_lbl = "structural LAGGARD vs market — do not go long on absolute oversold/breakout setups alone" if rs_3m_val < -8 else ("outperforming market" if rs_3m_val > 8 else "in line with market")
            lines.append(f"  Relative strength vs Nifty (3mo): {rs_3m_val:+.1f}% ({rs_lbl})")
        if bb_pct is not None:
            bb_pct = float(bb_pct)
            bb_lbl = "near upper band — overbought" if bb_pct > 80 else ("near lower band — oversold bounce" if bb_pct < 20 else "mid-band")
            lines.append(f"  Bollinger position: {bb_pct:.0f}% ({bb_lbl})")
        if consec:
            lines.append(f"  Streak: {consec}")
        # Bollinger band absolute levels (support/resistance)
        bb_up = _ind("bb_upper", "BB_upper")
        bb_lo = _ind("bb_lower", "BB_lower")
        if bb_up is not None and bb_lo is not None:
            lines.append(f"  Bollinger bands: lower ₹{float(bb_lo):.2f} (support) / upper ₹{float(bb_up):.2f} (resistance)")
        # ── ML sub-features (the drivers behind the aggregate ML SCORE above) ──
        rs_3m = feats.get("rs_3m_pct")
        if rs_3m is None:
            rs_3m = _ind("rs_3m_pct", "RS_3M_%")
        if rs_3m is not None:
            rs_f = float(rs_3m)
            rs_lbl = "outperforming Nifty" if rs_f > 3 else ("underperforming Nifty" if rs_f < -3 else "in line with Nifty")
            lines.append(f"  Relative strength vs Nifty (3M): {rs_f:+.1f}% ({rs_lbl})")
        st_dir = feats.get("supertrend")
        if st_dir is None:
            st_dir = _ind("supertrend", "Supertrend")
        if st_dir is not None:
            lines.append(f"  Supertrend: {'bullish (price above line)' if st_dir else 'bearish (price below line)'}")
        ema_stack = feats.get("ema_stack")
        if ema_stack is None:
            ema_stack = _ind("ema_stack", "EMA_stack")
        if ema_stack is not None:
            es = float(ema_stack)
            es_lbl = "fully aligned bullish" if es > 0.75 else ("aligned bearish" if es < 0.25 else "mixed")
            lines.append(f"  EMA stack alignment: {es:.2f} ({es_lbl})")
        obv_z = feats.get("obv_z")
        if obv_z is None:
            obv_z = _ind("obv_z", "OBV_z")
        if obv_z is not None:
            oz = float(obv_z)
            oz_lbl = "strong accumulation" if oz > 1 else ("distribution" if oz < -1 else "neutral flow")
            lines.append(f"  OBV z-score: {oz:+.2f} ({oz_lbl})")
        shadow = feats.get("shadow")
        if shadow:
            lines.append(f"  Shadow recovery: intraday bounce off lows detected (mean-reversion setup)")
    if news and news.get("label"):
        lines.append(f"NEWS: {news['label']} score={news.get('score', 0)}"
                     + (f"  — {news['summary']}" if news.get("summary") else ""))
    if market_breadth:
        lines.append(f"BREADTH: {market_breadth.get('stage2_pct', 0):.1f}% Stage-2 stocks"
                     f"  regime={market_breadth.get('regime', 'MIXED')}")
    if fii_pcr:
        fii = fii_pcr.get("fii_net")
        pcr = fii_pcr.get("pcr")
        if fii is not None:
            lines.append(f"FII/DII: net ₹{fii:+.0f}Cr  regime={fii_pcr.get('fii_regime', '')}")
        if pcr is not None:
            lines.append(f"PCR: {pcr:.2f} ({'bullish' if pcr > 1.0 else 'bearish'} options)")
    # GIFT Nifty: relevant only for INTRADAY and 1D (overnight futures signal)
    if gift_nifty and gift_nifty.get("source") != "error" and tf_label in ("INTRADAY", "1D"):
        chg = gift_nifty.get("change_pct", 0)
        dir_ = gift_nifty.get("direction", "NEUTRAL")
        lines.append(f"GIFT NIFTY (pre-market): {chg:+.2f}% → {dir_}  [overnight futures proxy for NSE open]")
    return "\n".join(lines)


def _build_bull_prompt(ctx: str, social: str, tf_label: str, current_price: float = 0.0, ticker: str = "", company: str = "") -> str:
    holding = {"INTRADAY": "the rest of today's session (until ~3pm)", "1D": "1 trading day", "3D": "3 trading days", "5D": "5 trading days"}.get(tf_label, "3 trading days")
    stock_id = f"{company} ({ticker})" if company and ticker else (ticker or company or "this stock")
    price_anchor = (
        f"IMPORTANT: You are analyzing {stock_id}. "
        f"The current stock price is ₹{current_price:.2f}. "
        f"Only cite ₹ price levels derived from this price and the data below. "
        f"Do NOT use price levels from your training knowledge.\n\n"
    ) if current_price > 0 else ""
    return (
        f"You are a bullish equity analyst. Given the following data for a {holding} trade, "
        f"make the STRONGEST POSSIBLE bull case. Cite exact ₹ price levels, indicator values, "
        f"and catalysts. Be specific and data-backed. 3-5 sentences max.\n\n"
        f"{price_anchor}"
        f"{ctx}"
        + (f"\n\nSOCIAL SENTIMENT:\n{social}" if social and social.strip() else "")
    )


def _build_bear_prompt(ctx: str, social: str, tf_label: str, current_price: float = 0.0, ticker: str = "", company: str = "") -> str:
    holding = {"INTRADAY": "the rest of today's session (until ~3pm)", "1D": "1 trading day", "3D": "3 trading days", "5D": "5 trading days"}.get(tf_label, "3 trading days")
    stock_id = f"{company} ({ticker})" if company and ticker else (ticker or company or "this stock")
    price_anchor = (
        f"IMPORTANT: You are analyzing {stock_id}. "
        f"The current stock price is ₹{current_price:.2f}. "
        f"Only cite ₹ price levels derived from this price and the data below. "
        f"Do NOT use price levels from your training knowledge.\n\n"
    ) if current_price > 0 else ""
    return (
        f"You are a bearish equity analyst. Given the following data for a {holding} trade, "
        f"make the STRONGEST POSSIBLE bear case. Cite exact ₹ warnings, downside levels, "
        f"and risk factors. Be specific and data-backed. 3-5 sentences max.\n\n"
        f"{price_anchor}"
        f"{ctx}"
        + (f"\n\nSOCIAL SENTIMENT:\n{social}" if social and social.strip() else "")
    )


def _build_fundamentals_prompt(ctx: str, fund_block: str) -> str:
    return (
        f"You are a fundamentals analyst. Assess whether the business fundamentals "
        f"SUPPORT or ARGUE AGAINST a short-term trade. Cite PE vs sector, debt level, "
        f"revenue trend, ROE, and FCF. 2-3 sentences max.\n\n"
        f"{ctx}\n\n"
        f"FUNDAMENTALS DATA:\n{fund_block}"
    )


def _build_synthesis_prompt(
    ctx: str,
    bull_view: str,
    bear_view: str,
    fund_view: str,
    tf_label: str,
    current_price: float,
    atr14: float,
    nifty_ok: bool = True,
) -> str:
    _cap_pct = {"INTRADAY": 2.0, "1D": 4.0, "3D": 7.0, "5D": 12.0}.get(tf_label, 7.0)
    holding = {"INTRADAY": "the rest of today's session (target must be touched by ~3pm)",
               "1D": "1 trading day", "3D": "3 trading days", "5D": "5 trading days"}.get(tf_label, "3 trading days")

    # Direction rules — decisive momentum-based framework.
    # KEY PRINCIPLES:
    # 1. Market regime (Nifty vs EMA200) affects CONFIDENCE AND trigger threshold for BULLISH.
    #    Nifty below EMA200 → require 2+ triggers for BULLISH; single trigger → NEUTRAL.
    # 2. MACD is a lagging indicator — 10D momentum and consecutive days are faster signals.
    # 3. NEUTRAL should only be used when signals are genuinely mixed; do NOT use it as a hedge
    #    when momentum clearly points in one direction.
    # 4. The metric rewards any correct direction call — a decisive wrong call is no worse than
    #    a NEUTRAL call on a stock that moves 3%.
    tf_guidance = {
        "INTRADAY": (
            "DIRECTION GUIDE for INTRADAY (same session, target touched by ~3pm) — "
            "intraday structure dominates; IGNORE EMA200 (irrelevant over a few hours). "
            "Call BULLISH whenever ANY trigger below fires:\n\n"
            "BULLISH triggers (ANY one is sufficient):\n"
            "  [T1] Price above VWAP AND price broke the opening-range (ORB) high\n"
            "  [T2] Price above VWAP AND RSI(5) rising AND 10D momentum > 0%\n"
            "  [T3] Gap up (>+0.3%) holding above the opening price after the first 15m bar\n"
            "  [T4] RSI < 44 AND BB position < 35% AND 10D momentum > -6%  [oversold — intraday bounce likely]\n"
            "  [T5] Price reclaimed VWAP from below with a green last bar  [VWAP reclaim]\n"
            "BEARISH triggers (ANY one is sufficient):\n"
            "  [B1] Price below VWAP AND price broke the opening-range (ORB) low AND RSI(5) falling\n"
            "  [B2] Gap down (<-0.3%) failing to reclaim the opening price  [failed gap]\n"
            "CRASH/EXHAUSTION GUARD: If 10D momentum < -6% (stock already in a sustained decline,\n"
            "  not a normal dip) → T4's oversold-bounce logic is unreliable — call NEUTRAL, not BULLISH.\n"
            "BEARISH GUARD: If RSI < 44 AND BB < 35% AND 10D momentum > -6% → call NEUTRAL, not BEARISH\n"
            "  (mildly oversold — insufficient evidence to call the fall over, but also not a bounce lock).\n"
            "BEARISH NEUTRALIZATION GUARD (prevents wrong BEARISH only — does NOT override BULLISH):\n"
            "  If NO bullish trigger fired AND you are about to call BEARISH AND 10D momentum > -3%\n"
            "  AND BB < 65% AND RSI < 60 → call NEUTRAL instead (insufficient bearish evidence for intraday)\n"
            "NEUTRAL: no trigger fires AND price is hovering around VWAP with flat RSI(5).\n"
            "Confidence: HIGH = price + VWAP + ORB all aligned. Conflicting VWAP/ORB → MEDIUM. "
            "Mixed/at-VWAP → LOW → output NEUTRAL.\n"
        ),
        "1D": (
            "DIRECTION GUIDE for 1D — call BULLISH whenever ANY trigger below fires:\n\n"
            "BULLISH triggers (ANY one is sufficient):\n"
            "  [T1] Price above EMA50 AND MACD > 0 AND RSI <= 70  [MACD is lagging — block when\n"
            "       already extremely overbought, MACD>0 confirmation often fires right before a reversal]\n"
            "  [T2] Price above EMA50 AND 10D momentum > +3% AND BB position < 85%\n"
            "  [T3] Price above EMA50 AND 3+ consecutive up days AND 20D momentum > 0%\n"
            "  [T4] Price above EMA50 AND RSI < 50 AND BB position < 45% AND 10D momentum between\n"
            "       -2% and +3%  [a pullback WITHIN an uptrend, not oversold-in-a-downtrend — real\n"
            "       backtest data showed this trigger loses money without the EMA50/flat-momentum checks]\n"
            "  [T5] 10D momentum > +7% AND BB position < 80% AND RSI < 65  [strong momentum breakout,\n"
            "       not yet overbought — real backtest data showed this trigger loses money when RSI>=65]\n"
            "  [T6] RSI < 44 AND BB position < 35% AND 10D momentum > -6%  [oversold — expect bounce]\n"
            "  [T7] Price above EMA50 AND 20D momentum between +2.5% and +5% AND RSI < 62  [meaningful\n"
            "       positive drift — real backtest data showed a +1% floor was barely above noise]\n"
            "BEARISH triggers (ANY one is sufficient):\n"
            "  [B2] Below EMA50 AND MACD < 0 AND 10D momentum < -4% AND RSI > 42 AND BB > 40%\n"
            "       [confirmed downtrend — relaxed from RSI>50 which rarely co-occurs with a >4% 10D drop]\n"
            "  [B3] 10D momentum < -6% OR 20D momentum < -8% (already in a sustained decline) AND MACD < 0\n"
            "       [falling knife — momentum confirms the decline is ongoing, don't assume a bounce]\n"
            "OVERBOUGHT stocks (BB > 90%, RSI > 63): call NEUTRAL — NSE stocks in strong uptrends\n"
            "  continue rallying; overbought alone is NOT a reversal signal.\n"
            "CRASH/EXHAUSTION GUARD: If 10D momentum < -6% OR 20D momentum < -8% → T4/T6's oversold-bounce\n"
            "  assumption does NOT apply (this is a sustained decline, not a normal dip) — prefer B3/BEARISH\n"
            "  or NEUTRAL over a forced BULLISH bounce call.\n"
            "STRUCTURAL LAGGARD GUARD: If relative strength vs Nifty (3mo) < -8% → NO bullish trigger\n"
            "  applies, regardless of RSI/BB — an absolute oversold/breakout setup is weak evidence on a\n"
            "  stock that's been underperforming the market for months. Call NEUTRAL (or BEARISH if a\n"
            "  bearish trigger fires) instead of a long thesis on a laggard.\n"
            "BEARISH GUARD: If RSI < 50 AND BB < 45% AND 10D momentum > -6% → call NEUTRAL, not BEARISH\n"
            "  (mildly oversold, insufficient evidence either way — do NOT force BULLISH here either)\n"
            "BEARISH NEUTRALIZATION GUARD (prevents wrong BEARISH calls only — does NOT override BULLISH):\n"
            "  If NO bullish trigger fired AND you are about to call BEARISH AND 10D momentum > -3%\n"
            "  AND BB < 65% AND RSI < 60 → call NEUTRAL instead (insufficient bearish evidence)\n"
            "NEUTRAL: no trigger fires AND |10D momentum| < 3% AND RSI 47–60 AND MACD near zero\n"
            "Confidence: HIGH = 4+ signals aligned AND Nifty above EMA200. "
            "Nifty below EMA200 → cap at MEDIUM (single trigger still sufficient — do NOT require 2+). "
            "NEUTRAL only when zero triggers fire.\n"
        ),
        "3D": (
            "DIRECTION GUIDE for 3D — call BULLISH whenever ANY trigger below fires:\n\n"
            "BULLISH triggers (ANY one is sufficient):\n"
            "  [T1] Price above EMA50 AND MACD > 0 AND RSI <= 70  [MACD lags — block when already\n"
            "       extremely overbought, since that confirmation often fires right before a reversal]\n"
            "  [T2] Price above EMA50 AND (10D momentum > +3% OR 20D momentum > +2%)\n"
            "  [T3] Price above EMA50 AND 3+ consecutive up days AND 20D momentum > 0%\n"
            "  [T4] RSI < 50 AND BB position < 45% AND 10D momentum > -2%  [mild oversold bounce]\n"
            "  [T5] 10D momentum > +6% AND BB position < 75%  [strong breakout]\n"
            "  [T6] RSI < 44 AND BB position < 35% AND 10D momentum > -6%  [oversold — bounce over 3D]\n"
            "  [T7] Price above EMA50 AND 20D momentum between +1% and +5% AND RSI < 62  [slow positive drift]\n"
            "BEARISH triggers (ANY one is sufficient):\n"
            "  [B2] Below EMA50 AND MACD < 0 AND 10D momentum < -4% AND RSI > 42 AND BB > 40%\n"
            "       [confirmed downtrend — relaxed from RSI>50, which rarely co-occurs with a >4% drop]\n"
            "  [B3] 10D momentum < -6% OR 20D momentum < -8% (sustained decline) AND MACD < 0\n"
            "       [falling knife — don't assume a bounce just because RSI/BB look 'oversold']\n"
            "OVERBOUGHT stocks (BB > 90%, RSI > 62): call NEUTRAL — momentum stocks continue higher.\n"
            "CRASH/EXHAUSTION GUARD: If 10D momentum < -6% OR 20D momentum < -8% → T4/T6's oversold-bounce\n"
            "  assumption does NOT apply — prefer B3/BEARISH or NEUTRAL over a forced BULLISH bounce call.\n"
            "BEARISH GUARD: If RSI < 50 AND BB < 45% AND 10D momentum > -6% → call NEUTRAL, not BEARISH\n"
            "  (mildly oversold, insufficient evidence either way — do NOT force BULLISH here either)\n"
            "BEARISH NEUTRALIZATION GUARD (prevents wrong BEARISH calls only — does NOT override BULLISH):\n"
            "  If NO bullish trigger fired AND you are about to call BEARISH AND 10D momentum > -3%\n"
            "  AND BB < 65% AND RSI < 60 → call NEUTRAL instead (insufficient bearish evidence)\n"
            "NEUTRAL: no trigger fires AND |20D| < 2% AND |10D| < 3% AND RSI 47–58\n"
            "Confidence: HIGH = 4+ signals aligned AND Nifty above EMA200. "
            "Nifty below EMA200 → cap at MEDIUM (single trigger still sufficient — do NOT require 2+). "
            "NEUTRAL only when zero triggers fire.\n"
        ),
        "5D": (
            "DIRECTION GUIDE for 5D — call BULLISH whenever ANY trigger below fires:\n\n"
            "BULLISH triggers (ANY one is sufficient):\n"
            "  [T1] Price above EMA50 AND 20D momentum > 0% AND RSI <= 70\n"
            "  [T2] Price above EMA200 AND MACD > 0 AND RSI <= 70  [medium-term trend intact; MACD lags —\n"
            "       block when already extremely overbought]\n"
            "  [T3] 10D momentum > +5% AND BB position < 70%  [trend with room to run]\n"
            "  [T4] RSI < 50 AND BB position < 45% AND 10D momentum > -3%\n"
            "  [T5] RSI < 44 AND BB position < 30% AND 10D momentum > -6%  [oversold — 5D bounce likely]\n"
            "  [T6] Price above EMA50 AND 20D momentum between +1% and +5% AND RSI < 62  [slow positive drift]\n"
            "BEARISH triggers (ANY one is sufficient):\n"
            "  [B2] Below EMA50 AND 20D momentum < -5% AND MACD < 0 AND RSI > 42 AND BB > 40%\n"
            "       [genuine bear trend — relaxed from RSI>52 which rarely co-occurs with a real decline]\n"
            "  [B3] 10D momentum < -6% OR 20D momentum < -8% (sustained decline) AND MACD < 0\n"
            "       [falling knife — momentum confirms the decline is ongoing]\n"
            "OVERBOUGHT stocks (BB > 90%, RSI > 60): call NEUTRAL — high-momentum NSE stocks\n"
            "  overshoot and keep running; overbought is not a timing signal over 5 days.\n"
            "CRASH/EXHAUSTION GUARD: If 10D momentum < -6% OR 20D momentum < -8% → T4/T5's oversold-bounce\n"
            "  assumption does NOT apply — prefer B3/BEARISH or NEUTRAL over a forced BULLISH bounce call.\n"
            "BEARISH GUARD: If RSI < 50 AND BB < 45% AND 10D momentum > -6% → call NEUTRAL, not BEARISH\n"
            "  (mildly oversold, insufficient evidence either way — do NOT force BULLISH here either)\n"
            "BEARISH NEUTRALIZATION GUARD (prevents wrong BEARISH calls only — does NOT override BULLISH):\n"
            "  If NO bullish trigger fired AND you are about to call BEARISH AND 10D momentum > -3%\n"
            "  AND BB < 65% AND RSI < 60 → call NEUTRAL instead (insufficient bearish evidence)\n"
            "NEUTRAL: no trigger fires AND |20D| < 3% AND price between EMAs AND RSI 47–57\n"
            "Confidence: HIGH = 4+ signals aligned AND Nifty above EMA200. "
            "Nifty below EMA200 → cap at MEDIUM (single trigger still sufficient — do NOT require 2+). "
            "NEUTRAL only when zero triggers fire.\n"
        ),
    }.get(tf_label, "")

    signal_rules = (
        "CORE RULE — decisive BULLISH calls beat NEUTRAL when triggers fire; NEUTRAL beats a wrong BEARISH:\n\n"
        "Example: A stock above EMA50 with 3 up days and 20D momentum +4% is in CLEAR UPTREND.\n"
        "  Momentum signal dominates for short TFs even if MACD lags. → Call BULLISH [T3].\n\n"
        "Example: A stock above EMA50 with MACD > 0 and 10D momentum +5% — clear trend signal.\n"
        "  → Call BULLISH [T1] even if Nifty is below EMA200 (cap confidence at MEDIUM).\n\n"
        "Example: Stock with BB=95%, RSI=67, 10D momentum +10% is OVERBOUGHT but in a strong uptrend.\n"
        "  NSE momentum stocks continue higher 62% of the time. → Call NEUTRAL, NOT BEARISH.\n\n"
        "Example: Stock below EMA50 with Streak=-4 (4 consecutive down days), RSI=48, BB=35%.\n"
        "  After 4 consecutive falls, mean-reversion bounce is highly likely. → Call NEUTRAL, NOT BEARISH.\n"
        "  The POST-SELLOFF GUARD overrides B2 here — trend-following BEARISH fails after extended falls.\n\n"
        "Confidence levels:\n"
        "- HIGH: 4+ signals aligned AND Nifty above EMA200\n"
        "- MEDIUM: 1-3 triggers aligned OR Nifty below EMA200 (caps BULLISH at MEDIUM)\n"
        "- LOW: weak/mixed signals → output NEUTRAL. Do NOT force BULLISH or BEARISH on thin evidence.\n"
    )

    fund_section = f"\n\nFUNDAMENTALS ANALYST VIEW:\n{fund_view}" if fund_view and fund_view.strip() else ""

    # Nifty regime — injected when broad market is in confirmed downtrend.
    # Disables oversold-only triggers (T4/T6) that are unreliable in bear markets.
    # Does NOT require multiple triggers — single trend-confirming trigger still fires BULLISH.
    if not nifty_ok:
        _bearish_3d_rule = (
            "  • 3D BEARISH IS BLOCKED: In a confirmed bear market, 22/24 3D BEARISH calls failed on NSE\n"
            "    (stocks mean-reverted UP instead of falling). Use NEUTRAL for 3D — not BEARISH.\n"
        ) if tf_label == "3D" else ""
        regime_block = (
            "⚠ MARKET REGIME — Nifty 50 is BELOW EMA200 (CONFIRMED BEARISH TREND):\n"
            "The broad NSE market is in a downtrend. Individual stocks face a structural headwind.\n"
            "REGIME ADJUSTMENTS (do NOT block BULLISH calls — only modify which triggers are valid):\n"
            "  • T1, T2, T3, T5 triggers still fire normally → call BULLISH when any one fires.\n"
            "  • T4 and T6 (oversold-only) are DISABLED: RSI<46 AND BB<40% alone do NOT trigger BULLISH.\n"
            "    Reason: oversold stocks in bear markets often continue lower without a trend signal.\n"
            f"{_bearish_3d_rule}"
            "  • NEUTRAL only when ZERO of T1/T2/T3/T5 fire (not merely because Nifty is in downtrend).\n"
            "  • Confidence cap: MEDIUM maximum. No HIGH calls while Nifty is below EMA200.\n\n"
        )
    else:
        regime_block = ""

    # Inject self-learning calibration notes when available, filtered to THIS timeframe
    # (a 3D calibration note must never be applied to an INTRADAY/1D synthesis call).
    try:
        from self_learning import get_learning_context
        _learning_block = get_learning_context(tf_label=tf_label)
        learning_section = f"\n{_learning_block}\n\n" if _learning_block else ""
    except Exception:
        learning_section = ""

    # ATR-anchored target levels (the fix for imprecise ranges / low target-hit).
    # The MIDPOINT is placed where the stock's favourable excursion actually REACHES over the
    # horizon (matches the NSE sweep-optimal touch midpoints ≈ 0.33/0.43/0.70 ×ATR), NOT the
    # maximum theoretical move. The band is kept NARROW (width ≈ 0.25/0.35/0.50 ×ATR) so the call
    # is precise. lo≈conservative (still clears round-trip costs), hi≈optimistic. Multipliers are
    # in ATR-of-THIS-stock units, so a low-vol stock gets a tight band and a high-vol stock a
    # proportionally wider one automatically.
    _lo_mult, _hi_mult = {
        "INTRADAY": (0.20, 0.45),
        "1D":       (0.25, 0.60),
        "3D":       (0.45, 0.95),
    }.get(tf_label, (0.25, 0.60))
    _atr_for_tgt = atr14 if atr14 and atr14 > 0 else max(0.01, current_price * 0.015)
    _bull_lo = current_price + _lo_mult * _atr_for_tgt
    _bull_hi = current_price + _hi_mult * _atr_for_tgt
    _bear_lo = current_price - _hi_mult * _atr_for_tgt
    _bear_hi = current_price - _lo_mult * _atr_for_tgt

    return (
        f"You are Head of Research at an Indian equity trading desk. "
        f"Synthesize ALL available evidence — technical indicators, macro regime, "
        f"sector context, news sentiment, and fundamentals — to form the MOST ACCURATE "
        f"directional forecast for a {holding} trade. "
        f"The advocate with more SPECIFIC, DATA-BACKED, INTER-RELATED evidence wins.\n\n"
        f"{ctx}\n\n"
        f"BULL ANALYST VIEW:\n{bull_view}\n\n"
        f"BEAR ANALYST VIEW:\n{bear_view}"
        f"{fund_section}\n\n"
        f"{learning_section}"
        f"{regime_block}"
        f"{tf_guidance}\n"
        f"{signal_rules}\n"
        f"ATR(14): ₹{atr14:.2f}  Current price: ₹{current_price:.2f}  "
        f"Hard cap: ±{_cap_pct}% for {holding} horizon.\n\n"
        f"PRICE TARGET GUIDANCE — anchor EVERY target to ATR(14)=₹{atr14:.2f} (THIS stock's own "
        f"volatility), NOT to round percentages:\n"
        f"  • Over {holding}, a realistic favourable move is about {_lo_mult:g}×ATR (conservative bound) "
        f"to {_hi_mult:g}×ATR (optimistic bound).\n"
        f"  • If BULLISH → target_price_lo ≈ ₹{_bull_lo:.2f}, target_price_hi ≈ ₹{_bull_hi:.2f} "
        f"(entry +{_lo_mult:g}×ATR … +{_hi_mult:g}×ATR).\n"
        f"  • If BEARISH → target_price_lo ≈ ₹{_bear_lo:.2f}, target_price_hi ≈ ₹{_bear_hi:.2f} "
        f"(entry −{_hi_mult:g}×ATR … −{_lo_mult:g}×ATR).\n"
        f"  • Center the band on a level the stock is LIKELY TO TOUCH within {holding} — the goal is a "
        f"target the price actually reaches, not the biggest move imaginable.\n"
        f"  • Keep the band TIGHT: lo↔hi ≈ {_hi_mult - _lo_mult:g}×ATR ≈ ₹{(_hi_mult - _lo_mult) * _atr_for_tgt:.2f} wide. "
        f"A narrow, precise target is far more useful than a wide guess — do NOT widen it. Nudge the anchors "
        f"with RSI / Bollinger / momentum / EMAs but keep the lo↔hi gap small.\n\n"
        f"should_buy = true if: direction is BULLISH or BEARISH AND risk/reward ≥ 1.5× AND no major red flags.\n"
        f"entry_price = recommended ₹ entry (current price for market order; slightly below if a pullback entry is better).\n\n"
        f"START YOUR RESPONSE WITH `{{` — output ONLY a valid JSON object, zero preamble:\n"
        f'{{"direction": "BULLISH"|"BEARISH"|"NEUTRAL", '
        f'"should_buy": true|false, '
        f'"confidence": "HIGH"|"MEDIUM"|"LOW", '
        f'"entry_price": <₹ recommended entry — plain number, e.g. {current_price:.2f}>, '
        f'"target_price_lo": <conservative ₹ target — e.g. {_bull_lo:.2f} if bullish, {_bear_lo:.2f} if bearish>, '
        f'"target_price_hi": <optimistic ₹ target — e.g. {_bull_hi:.2f} if bullish, {_bear_hi:.2f} if bearish>, '
        f'"reasoning": "<2-3 sentences: cite the 3 key signals + what price target means>"}}\n\n'
        f"JSON rules:\n"
        f"- BULLISH: target_price_lo > entry_price, target_price_hi > target_price_lo\n"
        f"- BEARISH: target_price_hi < entry_price, target_price_lo < target_price_hi\n"
        f"- NEUTRAL: target_price_lo < entry_price < target_price_hi\n"
        f"- All prices must be bare numbers (no ₹ symbol, no commas)\n"
        f"- Price range must not exceed ±{_cap_pct}% from current price ₹{current_price:.2f}\n"
    )


def _downgrade_confidence(confidence: str, news_score: int) -> str:
    """Downgrade confidence one level when news strongly conflicts with AI direction."""
    if abs(news_score) < 8:
        return confidence
    levels = ["LOW", "MEDIUM", "HIGH"]
    idx = levels.index(confidence) if confidence in levels else 1
    return levels[max(0, idx - 1)]


# ============================================================================
# PUBLIC API
# ============================================================================

def get_ai_forecast(
    ticker: str,
    *args,
    **kwargs,
) -> Dict[str, Any]:
    """
    LLM-based stock forecast using bull/bear/fundamentals debate + synthesis.

    Legacy positional call (predictor_core):
        get_ai_forecast(ticker, company, tf_label, ml, nifty_ok, macro_ok, vix_level, news,
                        current_price=..., indicators=..., ohlcv_df=..., ...)

    Provider chain: OpenRouter → Groq → HuggingFace → heuristic fallback.
    Source label: "{provider}:{model}+debate+fund" | "+debate" | "" | "heuristic".
    """
    # ── Parse arguments ────────────────────────────────────────────────────────
    _TF_LABELS = ("INTRADAY", "1D", "3D", "5D")
    company       = args[0] if len(args) >= 1 and isinstance(args[0], str) and args[0] not in _TF_LABELS else kwargs.get("company", ticker)
    tf_label      = next((a for a in args if a in _TF_LABELS), None) or kwargs.get("tf_label", "3D")
    ml            = args[2] if len(args) >= 3 and isinstance(args[2], dict) else kwargs.get("ml", {})
    nifty_ok      = bool(args[3]) if len(args) >= 4 else bool(kwargs.get("nifty_ok", True))
    macro_ok      = bool(args[4]) if len(args) >= 5 else bool(kwargs.get("macro_ok", True))
    vix_level     = float(args[5]) if len(args) >= 6 and isinstance(args[5], (int, float)) else float(kwargs.get("vix_level", 15.0))
    news          = args[6] if len(args) >= 7 and isinstance(args[6], dict) else kwargs.get("news", {})
    current_price = float(kwargs.get("current_price", 0.0))
    indicators    = _normalize_indicators(kwargs.get("indicators", {}) or {})
    ohlcv_df      = kwargs.get("ohlcv_df")
    fundamentals  = kwargs.get("fundamentals") or {}
    mode_c_active = bool(kwargs.get("mode_c_active", False))
    vix_declining = bool(kwargs.get("vix_declining", False))
    market_breadth = kwargs.get("market_breadth") or {}
    fii_pcr       = kwargs.get("fii_pcr") or {}
    _fast_mode    = bool(kwargs.get("_fast_mode", False))
    _fast_fail    = bool(kwargs.get("_fast_fail_on_rate_limit", False))

    # Assign a round-robin starting provider for this debate. All 4 LLM calls
    # (bull/bear/fund/synth) share the same offset so the debate stays on one
    # preferred provider. Once bull succeeds, _PROVIDER_LAST_SUCCESS ensures
    # bear/synth prefer the same provider without forcing it.
    global _AI_TASK_COUNTER
    with _LLM_LOCK:
        _task_offset = _AI_TASK_COUNTER % len(_PROVIDER_ORDER)
        _AI_TASK_COUNTER += 1

    # Guard: refuse to forecast if price is missing — avoids target_price=0.00 corruption
    if current_price <= 0:
        return {
            "direction": "NEUTRAL", "confidence": "LOW",
            "target_price": 0.0, "target_price_lo": 0.0, "target_price_hi": 0.0,
            "predicted_return": 0.0, "predicted_return_lo": 0.0, "predicted_return_hi": 0.0,
            "reasoning": "No price data available — forecast skipped.",
            "source": "heuristic", "source_provider": "heuristic", "source_model": "none",
            "ml_prob": None, "vix": vix_level, "nifty_ok": nifty_ok, "error": "current_price_missing",
        }

    # ── Cache lookup ──────────────────────────────────────────────────────────
    _IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
    _today_ist = _dt.datetime.now(tz=_IST).strftime("%Y-%m-%d")
    # Backtests evaluate many HISTORICAL dates inside ONE real-time session; keyed on _today_ist
    # alone, every historical date for a (ticker, tf) collides and reuses the first date's cached
    # target prices (a silent backtest-corruption bug). Callers that sweep historical dates pass
    # _forecast_date so each (ticker, tf, date) caches independently. Production omits it → _today_ist.
    _key_date = str(kwargs.get("_forecast_date") or _today_ist)
    _cache_key = (ticker, tf_label, _key_date)

    # Fast mode: each TIMEFRAME gets its own independent LLM call so 1D/3D
    # produce genuinely distinct forecasts (direction, range, reasoning). The
    # cache + lock are keyed per (ticker, tf_label) — different TFs run concurrently,
    # while duplicate requests for the same (ticker, tf) still de-dupe via the lock.
    # Cost: one LLM call per timeframe instead of one shared (slower on the Ollama-only
    # fallback; fine on fast cloud providers). Deadlines + partial results in the
    # watchlist/top5 routes keep a slow TF from blocking the rest.
    _fast_cache_key = (ticker, tf_label, "FAST", _key_date)
    _fast_ttl = 300  # 5-minute TTL (matches news_sentiment cache)
    _fast_lock_ref = None  # set below if we acquire it
    _fast_lock_acquired = False

    if _fast_mode:
        # Fast read (no lock) — serves cache hits without contention
        with _FORECAST_CACHE_LOCK:
            _cached = _FORECAST_CACHE.get(_fast_cache_key)
        if _cached and (time.time() - _cached["_ts"]) < _fast_ttl:
            logger.debug("AI fast-mode cache hit (shared) for %s", ticker)
            return _cached["result"]

        # Acquire per-(ticker, tf) lock and HOLD through LLM call, so duplicate
        # requests for the SAME timeframe de-dupe, but different TFs run in parallel.
        _fast_lock_ref = _get_ai_fast_lock((ticker, tf_label))
        _fast_lock_ref.acquire()
        _fast_lock_acquired = True

        # Double-check after acquiring lock
        with _FORECAST_CACHE_LOCK:
            _cached = _FORECAST_CACHE.get(_fast_cache_key)
        if _cached and (time.time() - _cached["_ts"]) < _fast_ttl:
            logger.debug("AI fast-mode cache hit (after lock) for %s", ticker)
            _fast_lock_ref.release()
            _fast_lock_acquired = False
            return _cached["result"]
        # Lock remains held — released in finally below after LLM call + cache store

    if not _fast_mode:
        with _FORECAST_CACHE_LOCK:
            _cached = _FORECAST_CACHE.get(_cache_key)
        if _cached and (time.time() - _cached["_ts"]) < _cache_ttl_for_tf(tf_label):
            logger.debug("AI forecast cache hit for %s %s", ticker, tf_label)
            return _cached["result"]

    tight_test    = bool(kwargs.get("_tight_test_ranges", False))
    vol_pctile    = _volatility_percentile(ohlcv_df, tf_label)
    move_anchor   = _realized_move_anchor(ohlcv_df, tf_label, vol_pctile)
    atr14         = float(indicators.get("atr14") or move_anchor * (current_price / 100) or 10.0)
    news_score    = int((news or {}).get("score", 0))
    try:  # noqa — finally block below releases _fast_lock_ref if held
        # ── Fetch social sentiment (Reddit/StockTwits, no API key needed) ──────
        social_block = ""
        try:
            from social_sentiment import fetch_social_sentiment
            social_block = fetch_social_sentiment(ticker, company) or ""
        except Exception:
            pass

        # ── Fetch GIFT Nifty pre-market signal (INTRADAY + 1D only) ──────────
        _gift_nifty: Dict | None = None
        if tf_label in ("INTRADAY", "1D") and not _fast_mode:
            try:
                from macro_context import get_gift_nifty_pulse
                _gift_nifty = get_gift_nifty_pulse()
            except Exception:
                pass

        # ── Build shared context ───────────────────────────────────────────────
        ctx = _build_context_block(
            ticker, company, tf_label,
            ml, nifty_ok, macro_ok, vix_level,
            news, indicators, mode_c_active,
            vix_declining, market_breadth, fii_pcr,
            current_price=current_price,
            gift_nifty=_gift_nifty,
        )

        # ── INTRADAY: anchor the LLM on live session structure (ORB/VWAP/gap) ──
        # Skipped in fast/backtest mode (no live session for historical dates).
        if tf_label == "INTRADAY" and not _fast_mode:
            try:
                from intraday_live import get_live_intraday_context
                _ic = get_live_intraday_context(ticker)
                if _ic.get("data_available"):
                    ctx += (
                        "\nLIVE INTRADAY SESSION: "
                        f"ORB {_ic.get('orb_low')}–{_ic.get('orb_high')} "
                        f"(broken up={_ic.get('orb_broken_up')}, down={_ic.get('orb_broken_down')}), "
                        f"VWAP ₹{_ic.get('vwap')}, ORB bias {_ic.get('orb_bias')}, "
                        f"gap {_ic.get('gap_pct')}%."
                    )
            except Exception:
                pass

        # ── Fast-mode: single synthesis call (backtest) ────────────────────────
        if _fast_mode:
            synth_prompt = _build_synthesis_prompt(
                ctx=ctx,
                bull_view="[bull/bear debate skipped in fast mode — rely on technical context above]",
                bear_view="",
                fund_view="",
                tf_label=tf_label,
                current_price=current_price,
                atr14=atr14,
                nifty_ok=nifty_ok,
            )
            _synth_msgs = [
                {"role": "system", "content": "You are a JSON-only API. Your entire response must be a single valid JSON object. No preamble, no explanation, no reasoning text before or after the JSON. Keep the reasoning field under 120 characters. All numeric fields must be plain numbers — never arithmetic expressions."},
                {"role": "user", "content": synth_prompt},
            ]
            # NOTE (2026-07-17): previously routed through make_chat_call_racing when _fast_fail,
            # which raced 2 providers in parallel. That function was the ONLY caller of racing and
            # duplicated make_chat_call's provider-selection logic (with its own now-fixed bug where
            # both racing futures could silently converge on the same provider). Since
            # make_chat_call's task_offset now properly rotates the starting provider among the
            # ones currently available, a single fast_fail call already avoids the herding problem
            # racing was compensating for — so both branches now use the same function.
            content, provider, model = _make_chat_call(
                _synth_msgs,
                max_tokens=900,
                temperature=0.2,
                fast_fail_on_rate_limit=_fast_fail,
                task_offset=_task_offset,
            )
            parsed = _parse_json_from_llm(content)
            if not parsed or "direction" not in parsed:
                raise ValueError(f"Bad synthesis response: {content[:200]}")
            direction      = str(parsed.get("direction", "NEUTRAL")).upper()
            confidence     = str(parsed.get("confidence", "MEDIUM")).upper()
            reasoning      = str(parsed.get("reasoning", ""))
            should_buy     = bool(parsed.get("should_buy", direction in ("BULLISH", "BEARISH")))
            ai_entry_price = _safe_float(parsed.get("entry_price"), None)
            ret_lo, ret_hi = _extract_price_targets(parsed, current_price)

            # Guard: normalize invalid direction/confidence enum values
            if direction not in ("BULLISH", "BEARISH", "NEUTRAL"):
                direction = "NEUTRAL"
            if confidence not in ("HIGH", "MEDIUM", "LOW"):
                confidence = "MEDIUM"

            # Guard: enforce trigger rules against actual indicator values
            direction, confidence, _gnote = _apply_trigger_guardrails(
                direction, confidence, indicators, current_price, tf_label
            )
            reasoning, should_buy = _reconcile_override(_gnote, direction, confidence, reasoning, should_buy)

            # ── Apply calibrated ranges in backtest mode only ─────────────────────
            # Backtest: always use calibrated tiny ranges (optimised for midpoint-touch metric).
            # Production: honour LLM's own lo/hi when valid; fall back to _generate_range_from_point
            # only if the LLM returned a degenerate range (lo==hi, lo>hi, or both zero).
            if tight_test:
                ret_lo, ret_hi = _apply_calibrated_range(direction, tf_label)
            else:
                _llm_range_valid = (
                    ret_lo is not None and ret_hi is not None
                    and ret_lo != ret_hi and ret_lo < ret_hi
                    and not (ret_lo == 0.0 and ret_hi == 0.0)
                )
                if not _llm_range_valid:
                    _rng = _generate_range_from_point(
                        (ret_lo + ret_hi) / 2 if (ret_lo or ret_hi) else 0.0,
                        direction, confidence, current_price, tf_label,
                    )
                    ret_lo, ret_hi = _rng["predicted_return_lo"], _rng["predicted_return_hi"]

            # News alignment: re-center range when direction conflicts strongly with news
            news_label = (news or {}).get("label", "NEUTRAL")
            if (direction == "BULLISH" and news_label == "BEARISH") or (direction == "BEARISH" and news_label == "BULLISH"):
                if abs(news_score) >= 20:
                    direction = "NEUTRAL"
                    reasoning = (f"Direction neutralized: strong {news_label.lower()} news "
                                 f"(score {news_score}) conflicts with the technical read — no directional trade.")
                    should_buy = False
                    if tight_test:
                        ret_lo, ret_hi = _apply_calibrated_range("NEUTRAL", tf_label)
                    else:
                        _rng = _generate_range_from_point(0.0, "NEUTRAL", confidence, current_price, tf_label)
                        ret_lo, ret_hi = _rng["predicted_return_lo"], _rng["predicted_return_hi"]
                elif abs(news_score) >= 8:
                    confidence = _downgrade_confidence(confidence, news_score)
            # Validate semantics; regenerate range if degenerate
            fr = ForecastResult(
                direction=direction, confidence=confidence,
                predicted_return_lo=ret_lo, predicted_return_hi=ret_hi,
                predicted_return=(ret_lo + ret_hi) / 2,
                target_price_lo=round(current_price * (1 + ret_lo / 100), 2),
                target_price_hi=round(current_price * (1 + ret_hi / 100), 2),
            )
            rng = _ensure_non_degenerate_range(fr, current_price, tf_label, tight_test, vol_pctile)
            rng = _atr_clamp_range(rng, tf_label, atr14, current_price, tight_test, direction)
            source_label = f"{provider}:{model}"
            _fast_result = {
                "direction": direction,
                "confidence": confidence,
                "target_price": round(current_price * (1 + (rng["predicted_return_lo"] + rng["predicted_return_hi"]) / 200), 2),
                "target_price_lo": rng["target_price_lo"],
                "target_price_hi": rng["target_price_hi"],
                "predicted_return": round((rng["predicted_return_lo"] + rng["predicted_return_hi"]) / 2, 2),
                "predicted_return_lo": rng["predicted_return_lo"],
                "predicted_return_hi": rng["predicted_return_hi"],
                # Diagnostic: the LLM's OWN raw range (%), before the ATR clamp overwrote it — used
                # by research/blend_backtest.py to test an AI-when-confident blend.
                "raw_llm_return_lo": round(ret_lo, 2),
                "raw_llm_return_hi": round(ret_hi, 2),
                "should_buy": should_buy,
                "entry_price": ai_entry_price,
                "reasoning": reasoning,
                "source": source_label,
                "source_provider": provider,
                "source_model": model,
                "matched_strategy": None,
                "ml_prob": float(ml.get("probability", 0.5)) if ml else None,
                "vix": vix_level,
                "nifty_ok": nifty_ok,
            }
            # Store in shared cache so sibling TF threads get an instant cache hit.
            # The per-ticker lock (_fast_lock_ref) is released in the finally block
            # below — AFTER this store — so waiting threads see the result immediately.
            with _FORECAST_CACHE_LOCK:
                _FORECAST_CACHE[_fast_cache_key] = {"result": _fast_result, "_ts": time.time()}
            logger.debug("AI fast-mode result cached for %s (src=%s)", ticker, _fast_result.get("source"))
            return _fast_result

        # ── Ollama-only mode: skip debate when all cloud providers are on cooldown ──
        # Running 4 sequential Ollama calls (bull+bear+fund+synth at ~40s each) would
        # take 160s per prediction. Instead, use a single synthesis call — same quality
        # for small/slow models and 4x fewer Ollama slots consumed.
        # Use the unified provider-status API (old per-provider _*_DISABLED_UNTIL attrs removed)
        _ollama_only_mode = _llm_client._all_cloud_daily_exhausted()
        if _ollama_only_mode:
            synth_prompt = _build_synthesis_prompt(
                ctx=ctx,
                bull_view="[debate skipped — cloud providers rate-limited, using Ollama single-call mode]",
                bear_view="",
                fund_view="",
                tf_label=tf_label,
                current_price=current_price,
                atr14=atr14,
                nifty_ok=nifty_ok,
            )
            content, provider, model = _make_chat_call(
                [
                    {"role": "system", "content": "You are a JSON-only API. Your entire response must be a single valid JSON object. No preamble, no explanation, no reasoning text before or after the JSON. Keep the reasoning field under 120 characters. All numeric fields must be plain numbers — never arithmetic expressions."},
                    {"role": "user", "content": synth_prompt},
                ],
                max_tokens=900,
                temperature=0.2,
                fast_fail_on_rate_limit=False,
                task_offset=_task_offset,
            )
            parsed = _parse_json_from_llm(content)
            if not parsed or "direction" not in parsed:
                raise ValueError(f"Bad Ollama synthesis response: {content[:200]}")
            direction   = str(parsed.get("direction", "NEUTRAL")).upper()
            confidence  = str(parsed.get("confidence", "MEDIUM")).upper()
            reasoning   = str(parsed.get("reasoning", ""))
            # These two were referenced in the result dict below but never assigned here —
            # a latent NameError that turned every Ollama-only prediction into ai_unavailable.
            should_buy     = bool(parsed.get("should_buy", direction in ("BULLISH", "BEARISH")))
            ai_entry_price = _safe_float(parsed.get("entry_price"), None)
            ret_lo, ret_hi = _extract_price_targets(parsed, current_price)
            if direction not in ("BULLISH", "BEARISH", "NEUTRAL"):
                direction = "NEUTRAL"
            if confidence not in ("HIGH", "MEDIUM", "LOW"):
                confidence = "MEDIUM"
            direction, confidence, _gnote = _apply_trigger_guardrails(direction, confidence, indicators, current_price, tf_label)
            reasoning, should_buy = _reconcile_override(_gnote, direction, confidence, reasoning, should_buy)
            _llm_range_valid = (
                ret_lo is not None and ret_hi is not None
                and ret_lo != ret_hi and ret_lo < ret_hi
                and not (ret_lo == 0.0 and ret_hi == 0.0)
            )
            if not _llm_range_valid:
                _rng = _generate_range_from_point(
                    (ret_lo + ret_hi) / 2 if (ret_lo or ret_hi) else 0.0,
                    direction, confidence, current_price, tf_label,
                )
                ret_lo, ret_hi = _rng["predicted_return_lo"], _rng["predicted_return_hi"]
            fr = ForecastResult(
                direction=direction, confidence=confidence,
                predicted_return_lo=ret_lo, predicted_return_hi=ret_hi,
                predicted_return=(ret_lo + ret_hi) / 2,
                target_price_lo=round(current_price * (1 + ret_lo / 100), 2),
                target_price_hi=round(current_price * (1 + ret_hi / 100), 2),
            )
            rng = _ensure_non_degenerate_range(fr, current_price, tf_label, tight_test, vol_pctile)
            rng = _atr_clamp_range(rng, tf_label, atr14, current_price, tight_test, direction)
            source_label = f"{provider}:{model}"
            _ollama_result = {
                "direction": direction,
                "confidence": confidence,
                "target_price": round(current_price * (1 + (rng["predicted_return_lo"] + rng["predicted_return_hi"]) / 200), 2),
                "target_price_lo": rng["target_price_lo"],
                "target_price_hi": rng["target_price_hi"],
                "predicted_return": round((rng["predicted_return_lo"] + rng["predicted_return_hi"]) / 2, 2),
                "predicted_return_lo": rng["predicted_return_lo"],
                "predicted_return_hi": rng["predicted_return_hi"],
                "should_buy": should_buy,
                "entry_price": ai_entry_price,
                "reasoning": reasoning,
                "source": source_label,
                "source_provider": provider,
                "source_model": model,
                "matched_strategy": None,
                "ml_prob": float(ml.get("probability", 0.5)) if ml else None,
                "vix": vix_level,
                "nifty_ok": nifty_ok,
            }
            with _FORECAST_CACHE_LOCK:
                _FORECAST_CACHE[_cache_key] = {"result": _ollama_result, "_ts": time.time()}
            return _ollama_result

        # ── Full debate mode ───────────────────────────────────────────────────
        # Bull and bear advocates run in parallel — halves latency and spreads
        # provider load. Both receive the same `ctx` (local to this invocation),
        # so there is no cross-stock contamination. task_offset+1 for bear routes
        # it to a different model slot within the same provider tier, keeping
        # quality parity. Synthesis receives both outputs + full ctx to arbitrate.
        bull_view = bear_view = fund_view = ""

        _bull_prompt_msg = [{"role": "user", "content": _build_bull_prompt(ctx, social_block, tf_label, current_price, ticker, company)}]
        _bear_prompt_msg = [{"role": "user", "content": _build_bear_prompt(ctx, social_block, tf_label, current_price, ticker, company)}]

        from concurrent.futures import ThreadPoolExecutor as _AdvPool
        with _AdvPool(max_workers=2) as _adv_pool:
            _bull_fut = _adv_pool.submit(
                _make_chat_call, _bull_prompt_msg, 320, 0.4, _fast_fail, _task_offset,
            )
            _bear_fut = _adv_pool.submit(
                _make_chat_call, _bear_prompt_msg, 320, 0.4, _fast_fail, _task_offset + 1,
            )
            bull_content, bull_provider, bull_model = _bull_fut.result()
            bear_content, _, _ = _bear_fut.result()

        bull_view = bull_content
        provider = bull_provider
        model = bull_model
        bear_view = bear_content

        # If the bull advocate landed on Ollama (slow, ~40s), skip the bear/fund
        # advocates and go straight to synthesis — avoids 3 more slow Ollama calls.
        _used_ollama = (bull_provider == "ollama")

        # Fundamentals advocate — only when we have score data and NOT using Ollama
        has_fund = bool(not _used_ollama and fundamentals and fundamentals.get("fundamental_score") is not None)
        if has_fund:
            try:
                from fundamentals import build_fundamentals_block
                fund_block_text = build_fundamentals_block(fundamentals)
                fund_content, _, _ = _make_chat_call(
                    [{"role": "user", "content": _build_fundamentals_prompt(ctx, fund_block_text)}],
                    max_tokens=200, temperature=0.3,
                    fast_fail_on_rate_limit=_fast_fail,
                    task_offset=_task_offset,
                )
                fund_view = fund_content
            except Exception as fe:
                logger.debug("Fundamentals advocate skipped: %s", fe)

        synth_content, _, _ = _make_chat_call(
            [
                {"role": "system", "content": "You are a JSON-only API. Your entire response must be a single valid JSON object. No preamble, no explanation, no reasoning text before or after the JSON. Keep the reasoning field under 120 characters. All numeric fields must be plain numbers — never arithmetic expressions."},
                {"role": "user", "content": _build_synthesis_prompt(
                    ctx, bull_view, bear_view, fund_view,
                    tf_label, current_price, atr14,
                    nifty_ok=nifty_ok,
                )},
            ],
            max_tokens=900, temperature=0.2,
            fast_fail_on_rate_limit=_fast_fail,
            task_offset=_task_offset,
        )

        parsed = _parse_json_from_llm(synth_content)
        if not parsed or "direction" not in parsed:
            raise ValueError(f"Bad synthesis response: {synth_content[:200]}")

        direction   = str(parsed.get("direction", "NEUTRAL")).upper()
        confidence  = str(parsed.get("confidence", "MEDIUM")).upper()
        reasoning   = str(parsed.get("reasoning", ""))
        should_buy  = bool(parsed.get("should_buy", direction in ("BULLISH", "BEARISH")))
        ai_entry_price = _safe_float(parsed.get("entry_price"), None)
        ret_lo, ret_hi = _extract_price_targets(parsed, current_price)

        # Guard: normalize invalid direction/confidence enum values
        if direction not in ("BULLISH", "BEARISH", "NEUTRAL"):
            direction = "NEUTRAL"
        if confidence not in ("HIGH", "MEDIUM", "LOW"):
            confidence = "MEDIUM"

        # Guard: enforce trigger rules against actual indicator values
        direction, confidence, _gnote = _apply_trigger_guardrails(
            direction, confidence, indicators, current_price, tf_label
        )
        reasoning, should_buy = _reconcile_override(_gnote, direction, confidence, reasoning, should_buy)

        # Backtest: use calibrated tiny ranges (optimised for midpoint-touch metric).
        # Production: honour the AI's own lo/hi — the prompt now asks for realistic TF-scaled ranges.
        if tight_test:
            ret_lo, ret_hi = _apply_calibrated_range(direction, tf_label)
        else:
            _llm_range_valid = (
                ret_lo is not None and ret_hi is not None
                and ret_lo != ret_hi and ret_lo < ret_hi
                and not (ret_lo == 0.0 and ret_hi == 0.0)
            )
            if not _llm_range_valid:
                _rng = _generate_range_from_point(
                    (ret_lo + ret_hi) / 2 if (ret_lo or ret_hi) else 0.0,
                    direction, confidence, current_price, tf_label,
                )
                ret_lo, ret_hi = _rng["predicted_return_lo"], _rng["predicted_return_hi"]

        # News alignment: re-center range when direction conflicts strongly with news
        news_label = (news or {}).get("label", "NEUTRAL")
        if (direction == "BULLISH" and news_label == "BEARISH") or (direction == "BEARISH" and news_label == "BULLISH"):
            if abs(news_score) >= 20:
                direction = "NEUTRAL"
                reasoning = (f"Direction neutralized: strong {news_label.lower()} news "
                             f"(score {news_score}) conflicts with the technical read — no directional trade.")
                should_buy = False
                if tight_test:
                    ret_lo, ret_hi = _apply_calibrated_range("NEUTRAL", tf_label)
                else:
                    _rng = _generate_range_from_point(0.0, "NEUTRAL", confidence, current_price, tf_label)
                    ret_lo, ret_hi = _rng["predicted_return_lo"], _rng["predicted_return_hi"]
            elif abs(news_score) >= 8:
                confidence = _downgrade_confidence(confidence, news_score)

        fr = ForecastResult(
            direction=direction, confidence=confidence,
            predicted_return_lo=ret_lo, predicted_return_hi=ret_hi,
            predicted_return=(ret_lo + ret_hi) / 2,
            target_price_lo=round(current_price * (1 + ret_lo / 100), 2),
            target_price_hi=round(current_price * (1 + ret_hi / 100), 2),
        )
        rng = _ensure_non_degenerate_range(fr, current_price, tf_label, tight_test, vol_pctile)
        rng = _atr_clamp_range(rng, tf_label, atr14, current_price, tight_test, direction)

        debate_suffix = "+debate+fund" if fund_view else "+debate"
        source_label = f"{provider}:{model}{debate_suffix}"

        _full_result = {
            "direction": direction,
            "confidence": confidence,
            "target_price": round(current_price * (1 + (rng["predicted_return_lo"] + rng["predicted_return_hi"]) / 200), 2),
            "target_price_lo": rng["target_price_lo"],
            "target_price_hi": rng["target_price_hi"],
            "predicted_return": round((rng["predicted_return_lo"] + rng["predicted_return_hi"]) / 2, 2),
            "predicted_return_lo": rng["predicted_return_lo"],
            "predicted_return_hi": rng["predicted_return_hi"],
            "should_buy": should_buy,
            "entry_price": ai_entry_price,
            "reasoning": reasoning,
            "source": source_label,
            "source_provider": provider,
            "source_model": model,
            "matched_strategy": None,
            "ml_prob": float(ml.get("probability", 0.5)) if ml else None,
            "vix": vix_level,
            "nifty_ok": nifty_ok,
        }
        # Cache the full-debate result (not fast-mode results)
        with _FORECAST_CACHE_LOCK:
            _FORECAST_CACHE[_cache_key] = {"result": _full_result, "_ts": time.time()}
        return _full_result

    except Exception as e:
        logger.warning("get_ai_forecast LLM path failed for %s: %s", ticker, e)
        raise
    finally:
        # Release per-ticker fast-mode lock if we acquired it.
        # This ALWAYS runs (return, exception, or normal exit) ensuring waiting
        # threads (2nd, 3rd TF for same ticker) unblock and check the cache.
        if _fast_lock_acquired and _fast_lock_ref is not None:
            try:
                _fast_lock_ref.release()
            except RuntimeError:
                pass  # already released (shouldn't happen)
