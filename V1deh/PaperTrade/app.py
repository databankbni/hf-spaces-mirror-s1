#!/usr/bin/env python3
"""
app.py — Flask web UI for the Indian equity paper trading platform.
Run: python3 app.py
Open: http://localhost:5000
"""

import sys, os, warnings, json, urllib.parse, urllib.request, time, logging, csv, re, statistics, threading
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, as_completed
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv optional — env vars already set

from flask import Flask, render_template, request, jsonify
from datetime import date, datetime, timedelta, timezone
from werkzeug.exceptions import HTTPException
from predictor_core import (
    predict_stock_v2, rank_stocks_v2, TICKER_NAMES,
    timeframe_to_dates, clear_runtime_caches,
)
from ai_forecast import _cache_ttl_for_tf
from universe import get_universe, refresh_universe  # get_universe used by search fallback
from data_sources import fetch_ohlcv, fetch_live_price, warm_ohlcv_cache
import database as db
import risk_engine

from top5_picker import get_top5_picks
from market_calendar import (
    market_status as nse_market_status,
    is_trading_day as nse_is_trading_day,
    next_trading_day as nse_next_trading_day,
)

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

# Paper-trading account capital (matches the ₹15,00,000 shown in the UI header). Used only
# as the base for the advisory Kelly position-size hint below.
_ACCOUNT_CAPITAL = 1_500_000
# Floor for the Kelly-based position-size hint (% of capital). A negative recent edge floors
# Kelly to 0; this floor keeps the SUGGESTED size sensible. It is advisory only — this is a
# paper-trading app, so the guardrail never blocks a trade (see /api/trades).
_MIN_KELLY_LIMIT_PCT = 5.0


class _SafeJSONProvider(app.json_provider_class):
    """Replace NaN/Infinity with null so browsers can parse the response."""
    def dumps(self, obj, **kwargs):
        import math

        def _clean(o):
            if isinstance(o, float):
                return None if not math.isfinite(o) else o
            if isinstance(o, dict):
                return {k: _clean(v) for k, v in o.items()}
            if isinstance(o, (list, tuple)):
                return [_clean(v) for v in o]
            return o

        return super().dumps(_clean(obj), **kwargs)


app.json_provider_class = _SafeJSONProvider
app.json = _SafeJSONProvider(app)

# yfinance can emit noisy crumb-related errors; the app has multi-source fallbacks.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

# Restore DB from HF Hub (no-op locally; required on HF Spaces free tier)
db.setup_hf_persistence()
# Initialise DB on startup
db.init_db()

# Top-5 dashboard cache (daily reset at midnight IST to ensure fresh daily picks)
_TOP5_CACHE: dict = {}
_TOP5_CACHE_TTL = 86400  # 24 hours — daily reset ensures new rankings based on fresh market data
_TOP5_COMPUTING = False   # True while a background computation is in progress
_TOP5_COMPUTING_LOCK = __import__("threading").Lock()  # guards the check-and-set on _TOP5_COMPUTING
# Live progress snapshot published by the background compute so /api/top5 can stream
# partial (per-card) results while the scan/AI phases are still running.
_TOP5_PROGRESS: dict = {}
_TOP5_PROGRESS_LOCK = __import__("threading").Lock()

# Watchlist prediction cache — keyed by (ticker, tf_label).
# TTL: 1D/3D/5D cached until IST midnight (re-run not needed same trading day).
# INTRADAY: 15-min TTL, auto-refreshed by _start_intraday_refresh_scheduler().
_WATCHLIST_PICK_CACHE: dict = {}
_WATCHLIST_PICK_AI_UNAVAILABLE_TTL = 125  # short TTL when AI was unavailable (>120s Ollama backoff so retry fires after cooldown clears)

# Give-up threshold for PENDING validations whose price data repeatedly fails to fetch
# (e.g. delisted/illiquid ticker, persistent data-source outage). Without this, such a
# row stays PENDING forever, showing an ever-more-overdue "Validation Due" date on every
# run even though every validation attempt (scheduler + manual) already retries it. Once
# a row's target date is this many days in the past AND the fetch still fails, it is
# marked EXPIRED (excluded from PENDING) rather than left to accumulate indefinitely.
_STALE_PENDING_GIVEUP_DAYS = 3

# ── Final INTRADAY call of the session ────────────────────────────────────────
# Once NSE closes (or we pass the 14:15 cutoff) INTRADAY can't be predicted live, so we
# normally show a "market closed" stub. Instead, remember the last REAL intraday call
# (direction + target price) made during the session and surface it after close, so the
# user can still see "what was the final call for the day". Keyed by ticker; kept for the
# most recent trading day. In-memory (mirrors _WATCHLIST_PICK_CACHE); resets on restart.
_INTRADAY_FINAL_CALL: dict = {}
_INTRADAY_FINAL_CALL_LOCK = __import__("threading").Lock()

# ── ML INTRADAY target memory ─────────────────────────────────────────────────
# Last INTRADAY target served per ticker by /api/ml-predict, so a fresh forecast can badge
# itself as a re-evaluation once the live price has run past that prior target (mirrors the
# AI "target hit → re-evaluate" flow). In-memory; resets on restart.
_ML_INTRADAY_TARGET: dict = {}
_ML_INTRADAY_TARGET_LOCK = __import__("threading").Lock()


def _intraday_pred_has_target(pred) -> bool:
    """True if `pred` is a real, actionable INTRADAY call carrying a target price band."""
    if not isinstance(pred, dict):
        return False
    if (pred.get("direction") or "").upper() in ("N/A", "NO TRADE", "NEUTRAL", ""):
        return False
    if pred.get("no_trade_reason"):
        return False
    lo = pred.get("target_price_lo") or 0
    hi = pred.get("target_price_hi") or 0
    return bool(lo and hi and lo > 0 and hi > 0)


def _last_trading_day(today):
    """Most recent NSE trading day on/before `today` (walks back up to 10 days)."""
    d = today
    for _ in range(10):
        if nse_is_trading_day(d):
            return d
        d = d - timedelta(days=1)
    return today


def _remember_intraday_call(ticker: str, pred: dict) -> None:
    """Cache the latest valid INTRADAY call (has a target price) for `ticker`, tagged with
    today's IST date, so it can be surfaced after the session closes."""
    if not isinstance(pred, dict) or pred.get("intraday_final_call"):
        return  # don't re-stamp an already-served final call (would corrupt its session date)
    if not _intraday_pred_has_target(pred):
        return
    ist = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(timezone.utc).astimezone(ist)
    with _INTRADAY_FINAL_CALL_LOCK:
        _INTRADAY_FINAL_CALL[ticker] = {
            "pred": pred,
            "date": now_ist.strftime("%Y-%m-%d"),
            "time": now_ist.strftime("%H:%M"),
        }


def _get_intraday_final_call(ticker: str):
    """Return a copy of the cached final INTRADAY call for `ticker` if it was made on the
    most recent NSE trading day, annotated (`intraday_final_call`, `final_call_time`) so the
    UI renders it as the session's final call rather than a live prediction. Else None."""
    with _INTRADAY_FINAL_CALL_LOCK:
        entry = _INTRADAY_FINAL_CALL.get(ticker)
    if not entry:
        return None
    ist = timezone(timedelta(hours=5, minutes=30))
    today = datetime.now(timezone.utc).astimezone(ist).date()
    if entry.get("date") != _last_trading_day(today).isoformat():
        return None
    pred = dict(entry["pred"])
    pred.pop("no_trade_reason", None)
    pred["intraday_final_call"] = True
    pred["final_call_time"] = entry.get("time")
    pred["final_call_date"] = entry.get("date")
    return pred


def _intraday_closed_value(ticker: str, stub: dict):
    """When INTRADAY can't be predicted live (market closed / past 14:15 cutoff), return the
    cached final call for the last session if we have one, otherwise the given stub."""
    return _get_intraday_final_call(ticker) or stub


def _intraday_target_reached(pred, live, today_high=None) -> bool:
    """True if the live price / today's intraday high has reached a live INTRADAY call's
    directional target. This is the trigger to re-evaluate the call for a fresh target off the
    new price level, instead of serving a target the price has already run past."""
    if not isinstance(pred, dict) or not live or live <= 0:
        return False
    d = (pred.get("direction") or "").upper()
    if "BULL" in d:
        tgt = pred.get("target_price_hi") or 0
        if tgt <= 0:
            return False
        ref = max(live, today_high) if (today_high and today_high > 0) else live
        return ref >= tgt
    if "BEAR" in d:
        tgt = pred.get("target_price_lo") or 0
        return tgt > 0 and live <= tgt
    return False

# ── Watchlist AI concurrency cap (process-wide) ───────────────────────────────
# Without this, the frontend fires N per-ticker requests in parallel × up to 3 TFs each =
# up to 3N simultaneous LLM calls, which 429s every free-tier provider at once → the
# "⚠ AI unavailable" storm. A small shared semaphore paces the whole scan so the calls
# spread across the ~6 providers (via task_offset rotation) instead of tripping all their
# per-minute limits together. A TF that can't get a slot before the deadline returns a
# retryable 'timeout' (the frontend refetches it), so predictions are paced, not lost.
# Env-tunable; small by design.
_WATCHLIST_AI_CONCURRENCY = max(1, int(os.getenv("WATCHLIST_AI_CONCURRENCY", "4")))
_WATCHLIST_AI_SEMAPHORE = threading.Semaphore(_WATCHLIST_AI_CONCURRENCY)
_WATCHLIST_AI_ACQUIRE_TIMEOUT = int(os.getenv("WATCHLIST_AI_ACQUIRE_TIMEOUT", "80"))

_WATCHLIST_TIMEOUT_STUB = {
    "no_trade_reason": "timeout", "direction": "N/A", "confidence": "N/A",
    "signal_count": 0, "ret_lo": 0, "ret_hi": 0, "midpoint": 0,
}


def _gated_predict(*args, **kwargs):
    """Run predict_stock_v2 under the watchlist AI concurrency cap.

    Blocks until a slot frees up (or WATCHLIST_AI_ACQUIRE_TIMEOUT seconds). If no slot is
    available in time, returns a retryable 'timeout' stub instead of blocking indefinitely or
    bursting — the frontend refetches that cell, so the prediction is deferred, not dropped."""
    got = _WATCHLIST_AI_SEMAPHORE.acquire(timeout=_WATCHLIST_AI_ACQUIRE_TIMEOUT)
    if not got:
        return dict(_WATCHLIST_TIMEOUT_STUB)
    try:
        return predict_stock_v2(*args, **kwargs)
    finally:
        _WATCHLIST_AI_SEMAPHORE.release()


# Portfolio insight cache — same LLM debate cost as watchlist, lazy-loaded on card expand
_PORTFOLIO_INSIGHT_CACHE: dict = {}
_PORTFOLIO_INSIGHT_TTL = 600  # 10 minutes


@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return jsonify({"error": str(e)}), e.code
    return jsonify({"error": str(e)}), 500


# ── HELPERS ───────────────────────────────────────────────────────────────────

def direction_to_snap(trade_direction: str) -> str:
    """Map LONG/SHORT trade direction to BULLISH/BEARISH for prediction snapshot."""
    return "BULLISH" if (trade_direction or "").upper() == "LONG" else "BEARISH"


def _bare(ticker: str) -> str:
    """Strip exchange suffix (.NS or .BO) for display / name lookup."""
    return ticker.replace(".NS", "").replace(".BO", "")


def _normalise(ticker: str) -> str:
    """Ensure ticker has an exchange suffix; default to NSE (.NS)."""
    t = ticker.upper().strip()
    if "." not in t:
        t += ".NS"
    return t


def _classify_watchlist_warning(err: object) -> str:
    """Map raw prediction errors to clearer user-facing warning text."""
    text = str(err or "").strip()
    if not text:
        return "Data unavailable"

    lower = text.lower()
    if text in ("'label'", '"label"') or "keyerror" in lower:
        return "Prediction processing error (missing field in upstream payload)."

    if (
        "all data sources failed" in lower
        or "no price data available" in lower
        or "insufficient history" in lower
    ):
        return f"Market data unavailable: {text}"

    return text


def _resolve_dates(data: dict) -> tuple[str, str]:
    """Return (start, end) from either timeframe or explicit dates.

    Only INTRADAY/1D are accepted as timeframe shortcuts — 3D/5D are retired from the live
    API. A 3D/5D timeframe falls through to explicit start/end dates (usually absent), so the
    caller gets the "timeframe required" error instead of a 3D/5D prediction.
    """
    tf = data.get("timeframe", "").upper()
    if tf in ("INTRADAY", "1D"):
        return timeframe_to_dates(tf)
    start = data.get("start_date", "")
    end   = data.get("end_date", "")
    return start, end


def _trade_price_diagnostics(trade: dict) -> dict:
    """Build price-action diagnostics for a closed trade using OHLCV in the trade window."""
    try:
        ticker = _normalise(trade.get("ticker", ""))
        entry = float(trade.get("entry_price") or 0)
        exit_px = float(trade.get("exit_price") or 0)
        direction = (trade.get("direction") or "LONG").upper()
        if not ticker or entry <= 0 or exit_px <= 0:
            return {}

        opened_raw = (trade.get("opened_at") or "")[:10]
        closed_raw = (trade.get("closed_at") or "")[:10]
        if not opened_raw or not closed_raw:
            return {}

        opened_date = datetime.strptime(opened_raw, "%Y-%m-%d").date()
        closed_date = datetime.strptime(closed_raw, "%Y-%m-%d").date()

        # Include a small buffer around the trade window for context bars.
        start = (opened_date - timedelta(days=4)).strftime("%Y-%m-%d")
        end = (closed_date + timedelta(days=1)).strftime("%Y-%m-%d")
        bars = fetch_ohlcv(ticker, period="2y")
        if bars is None or getattr(bars, "empty", True):
            return {}

        df = bars.copy()
        idx = getattr(df, "index", None)
        if idx is None:
            return {}

        mask = (idx.date >= opened_date) & (idx.date <= closed_date)
        tw = df.loc[mask]
        if getattr(tw, "empty", True):
            tw = df.tail(5)
        if getattr(tw, "empty", True):
            return {}

        high = float(tw["High"].max())
        low = float(tw["Low"].min())
        first_close = float(tw["Close"].iloc[0])
        last_close = float(tw["Close"].iloc[-1])

        if direction == "LONG":
            mfe_pct = ((high - entry) / entry) * 100
            mae_pct = ((low - entry) / entry) * 100
        else:
            mfe_pct = ((entry - low) / entry) * 100
            mae_pct = ((entry - high) / entry) * 100

        return {
            "window_days": int(len(tw)),
            "window_high": round(high, 2),
            "window_low": round(low, 2),
            "swing_pct": round(((high - low) / entry) * 100, 2),
            "trend_pct": round(((last_close - first_close) / first_close) * 100, 2),
            "mfe_pct": round(mfe_pct, 2),
            "mae_pct": round(mae_pct, 2),
            "entry_to_exit_pct": round(((exit_px - entry) / entry) * 100, 2),
        }
    except Exception:
        return {}


def _autofill_trade_context(ticker: str) -> dict:
    """Best-effort context fill for manual trade opens (strategy/timeframe/prediction_data).
    Runs without LLM calls so trade submission is fast — context is analytics-only.
    _skip_news=True is required for that: news_sentiment.fetch_and_analyze() calls the same
    LLM provider chain as the AI forecast on any cache miss (5-min TTL), which previously made
    "Open Trade" block for as long as a full AI forecast (up to ~90s w/ Ollama fallback)."""
    try:
        start, end = timeframe_to_dates("1D")
        pred = predict_stock_v2(
            ticker,
            start,
            end,
            _run_ai_forecast=False,
            _skip_news=True,
        )
        if not pred or pred.get("error"):
            return {}

        ai = pred.get("ai_forecast") or {}
        return {
            "strategy": ((pred.get("active_strategies") or ["AUTO_SCAN"])[0]),
            "timeframe": pred.get("timeframe") or "1D",
            "prediction_data": {
                "ml": pred.get("ml") or {},
                "news": pred.get("news") or {},
                "ai": {
                    "direction": ai.get("direction"),
                    "confidence": ai.get("confidence"),
                    "target_price_lo": ai.get("target_price_lo"),
                    "target_price_hi": ai.get("target_price_hi"),
                },
                "market": pred.get("market") or {},
            },
        }
    except Exception as exc:
        app.logger.warning("autofill_trade_context failed for %s: %s", ticker, exc)
        return {}


def _postmortem(trade: dict) -> str:
    """Generate a structured trade post-mortem using the full LLM provider chain."""

    pred_data = {}
    if trade.get("prediction_data"):
        try:
            pred_data = json.loads(trade["prediction_data"])
        except Exception:
            pass

    pnl_pct = trade.get("pnl_pct") or 0.0
    outcome = "WIN" if pnl_pct >= 0 else "LOSS"
    ml_score = pred_data.get("ml", {}).get("score", "N/A")
    news_label = pred_data.get("news", {}).get("label", "N/A")
    news_score = pred_data.get("news", {}).get("score", "N/A")
    news_summary = pred_data.get("news", {}).get("summary", "")
    ai_direction = pred_data.get("ai", {}).get("direction", "N/A")
    ai_confidence = pred_data.get("ai", {}).get("confidence", "N/A")
    vix_label = pred_data.get("market", {}).get("vix_label", "N/A")
    nifty_label = pred_data.get("market", {}).get("nifty_label", "N/A")

    is_manual = not pred_data and not trade.get("strategy")

    if is_manual:
        diag = _trade_price_diagnostics(trade)
        diag_block = ""
        if diag:
            diag_block = (
                "PRICE ACTION DIAGNOSTICS:\n"
                f"  Bars in window: {diag.get('window_days')}\n"
                f"  Window high/low: ₹{diag.get('window_high')} / ₹{diag.get('window_low')}\n"
                f"  Swing in window: {diag.get('swing_pct')}%\n"
                f"  Window trend (first close -> last close): {diag.get('trend_pct')}%\n"
                f"  MFE (best excursion from entry): {diag.get('mfe_pct')}%\n"
                f"  MAE (worst excursion from entry): {diag.get('mae_pct')}%\n"
            )
        prompt = f"""You are a senior NSE equity trader reviewing a paper trade that was opened manually — no prior AI prediction scan was run.

TRADE DETAILS:
  Ticker:    {trade['ticker']} ({trade.get('name', '')})
  Direction: {trade['direction']}
  Entry:     ₹{trade['entry_price']:,.2f}
  Exit:      ₹{trade['exit_price']:,.2f}
  P&L:       {pnl_pct:+.2f}%  → {outcome}

{diag_block}

No strategy signals, ML score, news sentiment, or AI prediction were recorded at entry.
Analyse strictly from the recorded trade levels and diagnostics above.
Do NOT mention missing AI data repeatedly. Be concrete and numeric.

Return ONLY a valid JSON object with these exact keys — no markdown, no explanation:
{{
  "why_outcome": "<2-3 sentences: primary reason this trade {outcome.lower()} based on price action and entry/exit levels alone.>",
  "what_went_right": "<what price behaviour or timing was favourable, even if trade {outcome.lower()}. Reference specific ₹ levels.>",
  "what_went_wrong": "<what price behaviour or risk management was poor. Be specific to the entry/exit prices and % move.>",
    "ai_prediction_assessment": "No AI prediction was run before entry, so there was no pre-trade directional confidence to validate against outcome.",
  "improvement_rule": "<one concrete, actionable rule. Start with a verb: e.g. 'Always run a watchlist prediction for ... before entering a LONG position.' >"
}}"""
    else:
        prompt = f"""You are a senior NSE equity trader reviewing a paper trade. Produce a structured post-mortem.

TRADE DETAILS:
  Ticker:        {trade['ticker']} ({trade.get('name', '')})
  Direction:     {trade['direction']}
  Entry price:   ₹{trade['entry_price']:,.2f}
  Exit price:    ₹{trade['exit_price']:,.2f}
  P&L:           {pnl_pct:+.2f}%  → {outcome}
  Strategy:      {trade.get('strategy', 'unknown')}
  Timeframe:     {trade.get('timeframe', 'unknown')}

AI PREDICTION AT ENTRY:
  Direction predicted: {ai_direction}  Confidence: {ai_confidence}
  ML score: {ml_score}/100
  News sentiment: {news_label} (score: {news_score})
  News summary: {news_summary}
  VIX at entry: {vix_label}
  Nifty gate:   {nifty_label}

Return ONLY a valid JSON object with these exact keys — no markdown, no explanation:
{{
  "why_outcome": "<2-3 sentences: primary reason this trade {outcome.lower()}. Name specific indicators or market conditions.>",
  "what_went_right": "<what signals or conditions were correct, even if trade {outcome.lower()}. Be specific.>",
  "what_went_wrong": "<what signals failed or what should have been a red flag. Cite exact data points.>",
  "ai_prediction_assessment": "<was the AI direction {ai_direction} correct? Did confidence {ai_confidence} match outcome? One sentence.>",
  "improvement_rule": "<one concrete, actionable rule to apply next time. Start with a verb: e.g. 'Skip LONG entries when...' >"
}}"""

    raw = None
    try:
        from ai_forecast import _make_chat_call
        content, _prov, _mdl = _make_chat_call(
            [{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.3,
            fast_fail_on_rate_limit=True,
        )
        raw = content
    except Exception:
        pass

    if raw:
        try:
            import re as _re
            cleaned = _re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=_re.MULTILINE).strip()
            parsed = json.loads(cleaned)
            # Validate expected keys present
            if "why_outcome" in parsed:
                return json.dumps(parsed)
        except Exception:
            pass
        # LLM returned unparseable output — fall through to unavailable stub
        _pm_reason = "LLM returned malformed JSON"
    else:
        _pm_reason = "All LLM providers unavailable or rate-limited — try again in a minute"

    # LLM unavailable stub — clearly labeled, no fake analysis
    if outcome == "LOSS":
        return json.dumps({
            "why_outcome": f"Trade closed at {pnl_pct:+.2f}%. Post-mortem unavailable. Reason: {_pm_reason}",
            "what_went_right": f"ML score was {ml_score}/100 at entry.",
            "what_went_wrong": "Unable to determine without LLM analysis.",
            "ai_prediction_assessment": f"AI predicted {ai_direction} with {ai_confidence} confidence.",
            "improvement_rule": "Retry post-mortem when LLM providers recover (usually within 1–2 minutes).",
        })
    return json.dumps({
        "why_outcome": f"Trade closed at {pnl_pct:+.2f}%. Post-mortem unavailable. Reason: {_pm_reason}",
        "what_went_right": f"Direction {trade['direction']} was profitable. ML score: {ml_score}/100.",
        "what_went_wrong": "No issues identified — trade was a winner.",
        "ai_prediction_assessment": f"AI predicted {ai_direction} with {ai_confidence} confidence.",
        "improvement_rule": "Retry post-mortem when LLM providers recover (usually within 1–2 minutes).",
    })


def _current_price(ticker: str, strict: bool = False) -> float | None:
    """Fetch latest price; strict mode avoids delayed fallback providers."""
    return fetch_live_price(ticker, allow_delayed=not strict)


def _reanchor_targets_to_live(tf_dict: dict, live: float | None) -> None:
    """Re-anchor a timeframe's price targets to the live price, IN PLACE.

    Cached predictions anchor their target prices to the prior close (the anchor at compute
    time). When the live price has since moved — most visibly a pre-market gap — the shown
    target range can already be surpassed by the current price, so the card looks nonsensical
    ("BULLISH, target ₹11,447" while the stock trades ₹11,549). The predicted MOVE (ret_lo /
    ret_hi / midpoint, in %) is anchor-independent, so we simply re-apply those percentages to
    the live price. This keeps the displayed target range consistent with — and ahead of — the
    current price the user sees, and preserves the INTRADAY ≥1% floor (baked into ret_hi). No-op
    without a valid live price or return %s (e.g. backtest, data errors)."""
    if not isinstance(tf_dict, dict) or not live or live <= 0:
        return
    ret_lo = tf_dict.get("ret_lo")
    ret_hi = tf_dict.get("ret_hi")
    if ret_lo is None or ret_hi is None:
        return
    tf_dict["target_price_lo"] = round(live * (1 + ret_lo / 100.0), 2)
    tf_dict["target_price_hi"] = round(live * (1 + ret_hi / 100.0), 2)
    # Expected target = the MIDPOINT of the shown range. Recompute it from ret_lo/ret_hi rather
    # than trusting a stored `midpoint`, which can be stale/inconsistent on cached predictions
    # (that produced "Target ₹1,611" sitting BELOW a ₹1,621–₹1,627 range). Guarantees the Target
    # always lands inside the displayed range.
    _lo, _hi = min(ret_lo, ret_hi), max(ret_lo, ret_hi)
    mid = tf_dict.get("midpoint")
    if mid is None or not (_lo <= mid <= _hi):
        mid = round((ret_lo + ret_hi) / 2.0, 2)
        tf_dict["midpoint"] = mid
    tf_dict["expected_target_price"] = round(live * (1 + mid / 100.0), 2)
    # Keep the embedded AI sub-line anchored to the SAME band as the headline range, so the AI
    # ₹ range can never diverge from the Target. Use the headline ret_lo/ret_hi (authoritative)
    # rather than the AI's own possibly-stale predicted_return_lo/hi.
    af = tf_dict.get("ai_forecast")
    if isinstance(af, dict) and af.get("direction") in ("BULLISH", "BEARISH", "SLIGHTLY BULLISH", "SELL"):
        af = dict(af)
        af["predicted_return_lo"] = ret_lo
        af["predicted_return_hi"] = ret_hi
        af["target_price_lo"] = round(live * (1 + ret_lo / 100.0), 2)
        af["target_price_hi"] = round(live * (1 + ret_hi / 100.0), 2)
        af["expected_target_price"] = tf_dict["expected_target_price"]
        tf_dict["ai_forecast"] = af
        tf_dict["ai_target_lo"] = af["target_price_lo"]
        tf_dict["ai_target_hi"] = af["target_price_hi"]


def _is_price_fresh(ticker: str) -> bool:
    """Check whether a current-session price is available for critical ops (stop-loss).

    The NSE/BSE realtime quote APIs and jugaad NSELive all hit the bot-blocked
    www.nseindia.com API (HTTP 403), so they were removed. The working same-day source
    is yfinance intraday, which reflects a live tick only while the market is OPEN.
    A price is therefore treated as actionable only during live market hours — outside
    the session there is no new tick to trigger stops against.
    """
    try:
        mkt = nse_market_status()
        if not mkt.get("is_trading_day") or mkt.get("status") != "OPEN":
            return False
        return _current_price(ticker) is not None
    except Exception:
        return False


def _json_no_store(payload: dict, status: int = 200):
    """Return JSON response with no-store headers for freshness-critical endpoints."""
    resp = jsonify(payload)
    resp.status_code = status
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


def _with_live_prices(payload: dict) -> dict:
    """Fetch live prices for all picks in parallel with a hard 10 s budget.

    Tickers whose price can't be resolved within the budget keep the cached
    price already stored in the pick dict — good enough for display and
    prevents the response from blocking for up to 60 s (4 sources × 15 s)
    when NSE/BSE/Yahoo are slow, which would trigger the frontend's AbortController.
    """
    picks = payload.get("picks") if isinstance(payload, dict) else None
    if not isinstance(picks, list):
        return payload

    out = dict(payload)
    tickers = [p["ticker"] for p in picks if isinstance(p, dict) and p.get("ticker")]

    price_map: dict = {}
    if tickers:
        def _fetch(t):
            return t, _current_price(t, strict=False)

        # NOTE: do NOT use `with ThreadPoolExecutor(...) as ex:` here. The context
        # manager's __exit__ calls shutdown(wait=True), which blocks until every
        # already-running fetch finishes — and f.cancel() only cancels futures that
        # have not started yet, not running ones. A single slow live-price source
        # (NSE/Yahoo can take up to ~60s) would therefore make this function block
        # far past the intended 10s budget and hang /api/top5. Create the executor
        # explicitly and shutdown(wait=False) so the 10s wait() timeout is a true
        # hard cap; unresolved tickers keep their cached price.
        ex = ThreadPoolExecutor(max_workers=len(tickers))
        try:
            fs = {ex.submit(_fetch, t): t for t in tickers}
            done, pending = concurrent.futures.wait(fs, timeout=10)
            for f in done:
                try:
                    t, price = f.result()
                    if price is not None:
                        price_map[t] = price
                except Exception:
                    pass
            for f in pending:
                f.cancel()
        finally:
            ex.shutdown(wait=False)

    out_picks = []
    for p in picks:
        if not isinstance(p, dict):
            out_picks.append(p)
            continue
        cloned = dict(p)
        ticker = p.get("ticker")
        if ticker and ticker in price_map:
            _live = price_map[ticker]
            cloned["price"] = _live
            cloned["current_price"] = _live
            # Re-anchor each timeframe's targets to the fresh live price so the shown target
            # range stays ahead of the current price (pre-market/gap moves otherwise leave the
            # cached target already surpassed). Clone the timeframes dict to avoid mutating the
            # shared cached pick.
            _tfs = cloned.get("timeframes")
            if isinstance(_tfs, dict):
                _tfs = {k: (dict(v) if isinstance(v, dict) else v) for k, v in _tfs.items()}
                for _tf_v in _tfs.values():
                    _reanchor_targets_to_live(_tf_v, _live)
                cloned["timeframes"] = _tfs
        out_picks.append(cloned)
    out["picks"] = out_picks
    return out


def _safe_float(v) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except Exception:
        return None


def _iter_num_from_path(path: str) -> int | None:
    m = re.search(r"ai_prompt_accuracy_iter(\d+)\.csv$", os.path.basename(path))
    if not m:
        return None
    return int(m.group(1))


def _read_iteration_metrics(path: str) -> dict | None:
    """Parse one loop-backtest CSV into per-timeframe target-hit metrics."""
    if not os.path.exists(path):
        return None

    excluded_sources = {"heuristic", "ai_unavailable", "failed"}
    per_tf: dict[str, dict] = {
        "1D": {"hits": 0, "n": 0, "widths": []},
        "3D": {"hits": 0, "n": 0, "widths": []},
        "5D": {"hits": 0, "n": 0, "widths": []},
    }

    try:
        with open(path, "r", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or "timeframe" not in reader.fieldnames:
                return None

            for row in reader:
                tf = (row.get("timeframe") or "").strip()
                if tf not in per_tf:
                    continue

                direction = (row.get("direction") or "").strip().upper()
                if direction not in {"BULLISH", "BEARISH"}:
                    continue

                source = (row.get("source") or "").strip().lower()
                if source in excluded_sources:
                    continue

                hit_val = row.get("target_hit_for_tf")
                hit = str(hit_val).strip().lower() in {"1", "true", "t", "yes"}
                per_tf[tf]["n"] += 1
                if hit:
                    per_tf[tf]["hits"] += 1

                entry = _safe_float(row.get("entry_price"))
                lo = _safe_float(row.get("target_price_lo"))
                hi = _safe_float(row.get("target_price_hi"))
                if entry and entry > 0 and lo is not None and hi is not None:
                    width_pct = abs(hi - lo) / entry * 100
                    per_tf[tf]["widths"].append(width_pct)
    except Exception:
        return None

    any_rows = sum(per_tf[tf]["n"] for tf in per_tf)
    if any_rows == 0:
        return None

    out = {}
    for tf in ("1D", "3D", "5D"):
        n = per_tf[tf]["n"]
        hits = per_tf[tf]["hits"]
        widths = per_tf[tf]["widths"]
        out[tf] = {
            "n": n,
            "hits": hits,
            "target_acc": round((hits / n) * 100, 1) if n else None,
            "median_width_pct": round(statistics.median(widths), 3) if widths else None,
        }

    out["rows"] = any_rows
    return out


def _archive_top5_predictions(result: dict, source: str = "top5") -> None:
    """Persist predictions for validation tracking."""
    for pick in result.get("picks", []):
        ticker = pick.get("ticker")
        if not ticker:
            continue
        price = pick.get("price", 0)
        timeframes = pick.get("timeframes", {})
        for tf in ["INTRADAY", "1D"]:
            tf_data = timeframes.get(tf, {})
            direction = tf_data.get("direction", "NEUTRAL")
            # Skip NO TRADE / data-error entries — they have no meaningful range to validate
            if (direction or "").upper() in ("NO TRADE", "N/A", ""):
                continue
            lo = tf_data.get("target_price_lo") or 0
            hi = tf_data.get("target_price_hi") or 0
            # Skip zero-width or degenerate target ranges (lo == hi == entry price)
            if lo and hi and lo == hi:
                continue
            try:
                db.save_prediction_snapshot(
                    ticker=ticker,
                    timeframe=tf,
                    direction=direction,
                    confidence=tf_data.get("confidence", "LOW"),
                    target_price_lo=lo,
                    target_price_hi=hi,
                    predicted_return_lo=tf_data.get("predicted_return_lo") or tf_data.get("ret_lo", 0),
                    predicted_return_hi=tf_data.get("predicted_return_hi") or tf_data.get("ret_hi", 0),
                    current_price=price,
                    snapshot_source=source,
                    snapshot_data=None,
                )
            except Exception as e:
                logging.warning(f"Failed to archive prediction for {ticker}/{tf}: {e}")


def _archive_ml_predictions(result: dict) -> None:
    """Persist standalone ML-model predictions for validation tracking (snapshot_source='ml').

    Mirrors _archive_top5_predictions but reads the ml_predictor.predict_all_tf schema so
    the validation tab can grade ML vs AI separately against the same realized NSE price.
    """
    if not result or not result.get("available"):
        return
    ticker = result.get("ticker")
    if not ticker:
        return
    top_price = result.get("current_price") or 0
    tfs = result.get("tfs", {}) or {}
    for tf in ["INTRADAY", "1D"]:
        d = tfs.get(tf, {}) or {}
        direction = (d.get("direction") or "NEUTRAL")
        if (direction or "").upper() in ("NO TRADE", "N/A", "", "SKIPPED"):
            continue
        lo = d.get("target_price_lo") or 0
        hi = d.get("target_price_hi") or 0
        if lo and hi and lo == hi:
            continue
        try:
            db.save_prediction_snapshot(
                ticker=ticker,
                timeframe=tf,
                direction=direction,
                confidence=d.get("confidence", "LOW"),
                target_price_lo=lo,
                target_price_hi=hi,
                predicted_return_lo=d.get("predicted_return_lo") or 0,
                predicted_return_hi=d.get("predicted_return_hi") or 0,
                current_price=d.get("current_price") or top_price,
                snapshot_source="ml",
                snapshot_data=None,
            )
        except Exception as e:
            logging.warning(f"Failed to archive ML prediction for {ticker}/{tf}: {e}")


# ── STATIC PAGES ──────────────────────────────────────────────────────────────

@app.route("/api/db-diag")
def db_diag():
    import sqlite3, shutil
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
    token_set = bool(token)
    db_exists = os.path.exists(db.DB_PATH)
    db_size = os.path.getsize(db.DB_PATH) if db_exists else 0
    counts = {}
    download_result = None
    if db_exists:
        try:
            with sqlite3.connect(db.DB_PATH) as c:
                for tbl in ("trades", "watchlist", "prediction_snapshots", "signal_accuracy"):
                    try:
                        counts[tbl] = c.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                    except Exception:
                        counts[tbl] = "missing"
        except Exception as e:
            counts["error"] = str(e)
    # Live test: attempt HF download right now and report what happens
    if token:
        try:
            from huggingface_hub import hf_hub_download
            local = hf_hub_download(
                repo_id=db._HF_REPO_ID,
                filename="paper_trading.db",
                repo_type="dataset",
                token=token,
                force_download=True,
            )
            size = os.path.getsize(local)
            # Inspect the DOWNLOADED copy READ-ONLY — never overwrite the live DB here. The old
            # shutil.copy2 over the live file clobbered local writes and could corrupt it mid-write.
            hub_counts = {}
            try:
                with sqlite3.connect(f"file:{local}?mode=ro", uri=True) as c:
                    for tbl in ("trades", "watchlist", "prediction_snapshots", "signal_accuracy"):
                        try:
                            hub_counts[tbl] = c.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                        except Exception:
                            hub_counts[tbl] = "missing"
            except Exception as e:
                hub_counts["error"] = str(e)
            counts["hub_copy"] = hub_counts
            download_result = f"OK — downloaded {size} bytes (inspected read-only; live DB untouched)"
        except Exception as e:
            download_result = f"FAILED: {e}"
    providers = {
        "openrouter_api_key":  bool(os.environ.get("OPENROUTER_API_KEY", "").strip()),
        "groq_api_key":        bool(os.environ.get("GROQ_API_KEY", "").strip()),
        "hf_token":            bool(os.environ.get("HF_TOKEN", "").strip()),
        "hf_inference_model":  os.environ.get("HF_INFERENCE_MODEL", "(default)"),
        "openrouter_best_model": os.environ.get("OPENROUTER_BEST_FREE_MODEL", "(default)"),
    }
    return jsonify({"token_set": token_set, "db_path": db.DB_PATH, "db_size_bytes": db_size, "download_result": download_result, "counts": counts, "providers": providers})


@app.route("/")
def index():
    return render_template("index.html")


# ── UNIVERSE ──────────────────────────────────────────────────────────────────

@app.route("/api/universe")
def universe():
    full = get_universe()
    tickers = [{"ticker": t, "name": name} for t, name in full.items()]
    return jsonify({"universe": tickers})


@app.route("/api/universe/refresh", methods=["POST"])
def universe_refresh():
    """Force-refresh the YF screener universe cache."""
    try:
        fresh = refresh_universe()
        return jsonify({"status": "refreshed", "count": len(fresh)})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/cache/warm", methods=["POST"])
def cache_warm():
    """
    Pre-warm OHLCV SQLite cache for a list of tickers.
    POST body: {"tickers": ["RELIANCE.NS", ...], "period": "1y"}
    Runs parallel yfinance fetches (60s timeout each) and returns per-ticker status.
    """
    body = request.get_json(silent=True) or {}
    tickers = body.get("tickers") or [item["ticker"] for item in db.get_watchlist()]
    period = body.get("period", "1y")

    if not tickers:
        return jsonify({"status": "ok", "results": {}}), 200

    results: dict = {}
    with ThreadPoolExecutor(max_workers=min(len(tickers), 8)) as ex:
        futs = {ex.submit(warm_ohlcv_cache, t, period): t for t in tickers}
        for f in as_completed(futs):
            t = futs[f]
            try:
                results[t] = "warm" if f.result(timeout=70) else "failed"
            except Exception as e:
                results[t] = f"error: {e}"

    return jsonify({"status": "ok", "period": period, "results": results})


# ── TICKER SEARCH (Yahoo Finance) ────────────────────────────────────────────

@app.route("/api/provider-status")
def provider_status():
    """Debug: show LLM provider config + availability. Add ?probe=1 to live-test each.

    Open this directly on the deployed Space (…/api/provider-status?probe=1) to see the
    REAL provider state there — which Secrets are configured and which actually answer —
    since that environment differs from local .env and can't be reproduced on the terminal.
    """
    import time as _time
    try:
        from llm_client import (
            _PROVIDER_STATUS, _maybe_daily_reset, _get_cloud_order,
            provider_key_status, probe_provider, _CLOUD_PROVIDERS,
        )
        _maybe_daily_reset()
        now = _time.time()
        configured = provider_key_status()
        status = {}
        for name, s in _PROVIDER_STATUS.items():
            avail_in = max(0, s["avail_at"] - now)
            status[name] = {
                "configured": configured.get(name, False),
                "daily_exhausted": s["daily_exhausted"],
                "avail_in_secs": round(avail_in, 1),
                "available_now": avail_in <= 0 and not s["daily_exhausted"],
                "fail_streak": s.get("fail_streak", 0),
            }
        out = {
            "providers": status,
            "configured": configured,
            "configured_count": sum(1 for v in configured.values() if v),
            "cloud_order": _get_cloud_order(),
        }
        # ?probe=1 → make a real 1-token call to each configured provider in parallel.
        if request.args.get("probe") == "1":
            names = list(_CLOUD_PROVIDERS) + ["ollama"]
            probes: dict = {}
            ex = ThreadPoolExecutor(max_workers=len(names))
            try:
                futs = {ex.submit(probe_provider, n): n for n in names}
                done, pending = concurrent.futures.wait(futs, timeout=40)
                for f in done:
                    n = futs[f]
                    try:
                        probes[n] = f.result()
                    except Exception as pe:
                        probes[n] = {"ok": False, "error": str(pe)[:200]}
                for f in pending:
                    probes[futs[f]] = {"ok": False, "error": "probe timed out (>40s)"}
                    f.cancel()
            finally:
                ex.shutdown(wait=False)
            out["probe"] = probes
            out["probe_working"] = [n for n, r in probes.items() if r.get("ok")]
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/search")
def search_ticker():
    """Ticker search: tries Yahoo Finance live, falls back to cached local universe."""
    q = request.args.get("q", "").strip().upper()
    if len(q) < 1:
        return jsonify({"results": []})

    results = []

    # 1. Try Yahoo Finance live search
    try:
        url = (
            f"https://query2.finance.yahoo.com/v1/finance/search"
            f"?q={urllib.parse.quote(q)}&lang=en-US&region=IN&quotesCount=10&newsCount=0"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        quotes = data.get("quotes") or []
        results = [
            {"ticker": item["symbol"],
             "name": item.get("longname") or item.get("shortname") or item["symbol"]}
            for item in quotes
            if item.get("symbol", "").endswith((".NS", ".BO"))
        ]
    except Exception:
        pass  # fall through to local search

    # 2. Local fallback — search cached universe by ticker/name substring (<1 ms if cached)
    if not results:
        try:
            universe = get_universe()
            q_lower = q.lower()
            for ticker, name in universe.items():
                bare = ticker.replace(".NS", "").replace(".BO", "")
                if q in bare or q_lower in name.lower():
                    results.append({"ticker": ticker, "name": name})
                if len(results) >= 10:
                    break
        except Exception:
            pass

    return jsonify({"results": results})


# ── MARKET STATUS ─────────────────────────────────────────────────────────────

@app.route("/api/market-status")
def market_status_endpoint():
    """Return current NSE market status (OPEN/CLOSED/HOLIDAY/WEEKEND/PRE_MARKET/POST_MARKET)."""
    return _json_no_store(nse_market_status())


# ── PREDICT ───────────────────────────────────────────────────────────────────

@app.route("/api/predict", methods=["POST"])
def predict():
    data       = request.get_json(force=True)
    stocks     = data.get("stocks", [])
    start, end = _resolve_dates(data)

    if not stocks:
        return jsonify({"error": "Provide at least one ticker"}), 400
    if not start or not end:
        return jsonify({"error": "timeframe (INTRADAY/1D) or start_date + end_date required"}), 400
    if len(stocks) > 20:
        return jsonify({"error": "Max 20 stocks per request"}), 400

    with ThreadPoolExecutor(max_workers=min(len(stocks), 10)) as pool:
        futures = {pool.submit(predict_stock_v2, _normalise(t), start, end): t for t in stocks}
        results = [fut.result() for fut in as_completed(futures)]

    # Add loophole checking to each prediction
    for pred in results:
        if not pred.get("error") and pred.get("direction") not in ("N/A", "NEUTRAL", "NO TRADE"):
            loopholes = _audit_prediction(pred)
            if loopholes.get("loophole_count", 0) > 0:
                pred["loopholes"] = loopholes

    mkt = nse_market_status()
    resp: dict = {"predictions": results}
    if not mkt["is_trading_day"]:
        resp["market_closed"] = {"status": mkt["status"], "message": mkt["message"], "next_open": mkt["next_open"]}
    elif mkt["status"] in ("PRE_MARKET", "POST_MARKET"):
        resp["market_closed"] = {"status": mkt["status"], "message": mkt["message"], "next_open": mkt.get("next_open")}
    return _json_no_store(resp)


# ── RANK ──────────────────────────────────────────────────────────────────────

@app.route("/api/rank", methods=["POST"])
def rank():
    data       = request.get_json(force=True)
    start, end = _resolve_dates(data)
    capital    = data.get("capital")
    universe   = data.get("universe")

    if not start or not end:
        return jsonify({"error": "timeframe (INTRADAY/1D) or start_date + end_date required"}), 400

    if capital:
        try:
            capital = float(capital)
        except (ValueError, TypeError):
            capital = None

    if universe:
        universe = [_normalise(t) for t in universe]

    result = rank_stocks_v2(start, end, universe=universe, capital=capital)

    # Add loophole checking to ranked predictions
    if result.get("predictions"):
        for pred in result["predictions"]:
            if not pred.get("error") and pred.get("direction") not in ("N/A", "NEUTRAL", "NO TRADE"):
                loopholes = _audit_prediction(pred)
                if loopholes.get("loophole_count", 0) > 0:
                    pred["loopholes"] = loopholes

    return _json_no_store(result)


# ── CHART DATA ────────────────────────────────────────────────────────────────

@app.route("/api/chart/<ticker>")
def chart_data(ticker):
    t = _normalise(ticker)

    interval = request.args.get("interval", "1d")   # "1d" | "5m" | "15m"
    if interval == "5m":
        period, yf_interval = "2d",  "5m"   # 2d ensures we get the last trading day even over weekends
    elif interval == "15m":
        period, yf_interval = "60d", "15m"
    else:
        period, yf_interval = "90d", "1d"

    try:
        # Daily candles can use the resilient multi-source OHLCV chain.
        if yf_interval == "1d":
            sc, sh, sl, _ = fetch_ohlcv(t, period="3mo")
            hist = (
                sc.rename(columns={t: "Close"})
                .join(sh.rename(columns={t: "High"}), how="inner")
                .join(sl.rename(columns={t: "Low"}), how="inner")
            )
            # Open is approximated from previous close for daily display only.
            hist["Open"] = hist["Close"].shift(1).fillna(hist["Close"])
        else:
            import yfinance as yf
            hist = yf.download(
                t,
                period=period,
                interval=yf_interval,
                auto_adjust=True,
                progress=False,
                threads=False,
            )
            if hist is not None and not hist.empty and hasattr(hist.columns, "nlevels") and hist.columns.nlevels > 1:
                hist.columns = hist.columns.get_level_values(0)
            # Intraday feed empty (ticker not on Yahoo intraday) — fall back to daily multi-source
            if hist is None or hist.empty:
                try:
                    sc, sh, sl, _ = fetch_ohlcv(t, period="3mo")
                    hist = (
                        sc.rename(columns={t: "Close"})
                        .join(sh.rename(columns={t: "High"}), how="inner")
                        .join(sl.rename(columns={t: "Low"}), how="inner")
                    )
                    hist["Open"] = hist["Close"].shift(1).fillna(hist["Close"])
                    yf_interval = "1d"
                    interval = "1d"
                except Exception:
                    pass

        if hist is None or hist.empty:
            return jsonify({"ticker": t, "candles": [], "interval": interval})

        candles = []
        for idx, r in hist.iterrows():
            # Lightweight Charts needs Unix timestamps for intraday
            if yf_interval in ("5m", "15m"):
                ts = int(idx.timestamp())
            else:
                ts = str(idx.date())
            candles.append({
                "time":  ts,
                "open":  round(float(r.Open),  2),
                "high":  round(float(r.High),  2),
                "low":   round(float(r.Low),   2),
                "close": round(float(r.Close), 2),
            })
        return jsonify({"ticker": t, "candles": candles, "interval": interval})
    except Exception as e:
        return jsonify({"error": str(e), "candles": []}), 500


# ── LIVE PRICE ────────────────────────────────────────────────────────────────

@app.route("/api/live-price/<ticker>")
def live_price(ticker):
    t = _normalise(ticker)
    price = fetch_live_price(t)
    if price is None:
        return jsonify({"error": "Price unavailable"}), 404
    resp = jsonify({"ticker": t, "price": price, "source": "multi-source fallback"})
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/api/ml-predict/<ticker>")
def ml_predict(ticker):
    """Standalone ML price model (ml_predictor) — INTRADAY/1D/3D quantile forecast.

    Independent of the LLM debate pipeline. Returns per-timeframe direction, confidence,
    return band, target prices, buy-price suggestion, stop-loss, and — for INTRADAY —
    the estimated high plus an 'already gone' flag against the live price.
    Query params: ?news=<int> optional news score, ?live=0 to skip the live-price fetch.
    """
    t = _normalise(ticker)
    try:
        from ml_predictor.infer import get_ml_predictor
        predictor = get_ml_predictor()
        if not predictor.available:
            return jsonify({"ticker": t, "available": False,
                            "error": "ML model not trained/loaded — run ml_predictor/train.py"}), 503
        # Market status is a cheap local (calendar) check — resolve it up front so we can skip
        # the expensive intraday-bars download when the session is closed (INTRADAY gets stubbed
        # to market_closed below regardless, so fetching today_high then is pure wasted latency).
        try:
            _mkt = nse_market_status()
        except Exception:
            _mkt = {}
        _mkt_open = _mkt.get("status") == "OPEN"
        live_price = None
        if request.args.get("live", "1") != "0":
            try:
                live_price = fetch_live_price(t)
            except Exception:
                live_price = None
        # Fetch today's intraday HIGH so the ML "already_gone"/headroom guard works — this is
        # what stops INTRADAY from emitting a target the stock has ALREADY passed earlier in the
        # session. Without today_high the guard is blind and can print a target below the live price.
        # Only needed while the market is OPEN — the 15m-bar download serializes every caller on a
        # single global lock (intraday_live._YF_DOWNLOAD_LOCK), so skipping it off-hours removes the
        # main reason ML rows lag behind the (concurrent) AI calls on watchlist/top-pick loads.
        today_high = None
        if live_price and _mkt_open and request.args.get("live", "1") != "0":
            try:
                from intraday_live import get_intraday_bars
                _bars = get_intraday_bars(t, interval="15m", period="1d")
                if _bars is not None and not _bars.empty and "High" in _bars.columns:
                    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
                    _ist = _tz(_td(hours=5, minutes=30))
                    _idx = _bars.index
                    _loc = _idx.tz_convert(_ist) if _idx.tz is not None else _idx.tz_localize("UTC").tz_convert(_ist)
                    _today = _dt.now(_ist).strftime("%Y-%m-%d")
                    _mask = [ts.strftime("%Y-%m-%d") == _today for ts in _loc]
                    _sub = _bars[_mask]
                    if not _sub.empty:
                        today_high = round(float(_sub["High"].max()), 2)
            except Exception:
                today_high = None
        news_score = 0
        try:
            news_score = int(request.args.get("news", "0"))
        except (TypeError, ValueError):
            news_score = 0
        result = predictor.predict_all_tf(t, live_price=live_price, today_high=today_high, news_score=news_score)
        # 3D/5D are retired from the live API — the ML model still computes 3D internally
        # (committed artifacts), but the endpoint only exposes INTRADAY/1D.
        if isinstance(result.get("tfs"), dict):
            result["tfs"] = {k: v for k, v in result["tfs"].items() if k in ("INTRADAY", "1D")}
        # Block INTRADAY once NSE has closed for the day (post 15:30 IST) — there is no
        # live session left to predict, so the same-day ML forecast is meaningless. Mirrors
        # the AI path, which already stubs INTRADAY as market_closed when the market isn't OPEN.
        try:
            if not _mkt_open and result.get("available") and result.get("tfs"):
                result["tfs"]["INTRADAY"] = {
                    "market_closed": True,
                    "direction": "N/A",
                    "confidence": "N/A",
                    "market_status": _mkt.get("status"),
                }
                result["intraday_market_closed"] = True
        except Exception:
            pass
        # INTRADAY "target hit → re-evaluate": if the live price has run past the target we last
        # served for this ticker, tag this fresh forecast so the UI badges the new (higher/lower)
        # target as a re-evaluation. Mirrors the AI path. Then remember the new target.
        try:
            _itf = (result.get("tfs") or {}).get("INTRADAY") if result.get("available") else None
            if (isinstance(_itf, dict) and not _itf.get("market_closed")
                    and _mkt_open and live_price and live_price > 0):
                _dir = (_itf.get("direction") or "").upper()
                _new_tgt = _itf.get("expected_target_price")
                with _ML_INTRADAY_TARGET_LOCK:
                    _prev = _ML_INTRADAY_TARGET.get(t)
                if (_prev and _prev.get("target")
                        and ((_prev.get("dir") == "BULLISH" and live_price >= _prev["target"])
                             or (_prev.get("dir") == "BEARISH" and live_price <= _prev["target"]))):
                    _ist_ml = timezone(timedelta(hours=5, minutes=30))
                    _itf["reevaluated"] = True
                    _itf["reeval_time"] = datetime.now(timezone.utc).astimezone(_ist_ml).strftime("%H:%M")
                    _itf["prev_target"] = _prev["target"]
                if _dir in ("BULLISH", "BEARISH") and _new_tgt:
                    with _ML_INTRADAY_TARGET_LOCK:
                        _ML_INTRADAY_TARGET[t] = {"dir": _dir, "target": _new_tgt}
        except Exception:
            pass
        # Optional: persist ML predictions for the validation tab (ML vs AI vs Actual).
        # The frontend passes ?archive=1 when rendering watchlist/top-pick cards so ML
        # snapshots accrue exactly where AI snapshots do. INTRADAY market_closed stubs carry
        # direction 'N/A' and are skipped by _archive_ml_predictions.
        if request.args.get("archive") == "1":
            try:
                _archive_ml_predictions(result)
            except Exception:
                logging.warning("ML archive failed for %s", t, exc_info=True)
        resp = jsonify(result)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return resp
    except Exception as e:
        logging.exception("ml_predict failed for %s", t)
        return jsonify({"ticker": t, "available": False, "error": str(e)}), 500


@app.route("/api/open-trades")
def open_trades_with_prices():
    """Return all open trades enriched with current live prices."""
    try:
        trades = db.get_open_trades_with_live_prices()
        resp = jsonify({"trades": trades})
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        return resp
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── LOOPHOLE CHECKING & SPECIALIST ANALYSIS ──────────────────────────────────

def _audit_prediction(pred: dict) -> dict:
    """
    Validate a prediction for loopholes: conflicting signals, news mismatch,
    weak conviction, fundamentals contradictions.
    """
    loopholes = []

    # 1. CONFLICTING TECHNICAL SIGNALS
    if pred.get("direction") == "BULLISH":
        ml_features = (pred.get("ml") or {}).get("features") or {}
        rsi = ml_features.get("rsi", 50)
        ema50 = ml_features.get("ema50")
        price = pred.get("price")

        if rsi and rsi > 60:
            loopholes.append({
                "category": "conflicting_signals",
                "flag": "RSI_OVERBOUGHT",
                "severity": "WARNING",
                "detail": f"Bullish call but RSI {rsi:.0f} > 60 (overbought, lacks pullback)"
            })
        if ema50 and price and price < ema50:
            loopholes.append({
                "category": "conflicting_signals",
                "flag": "BELOW_EMA50",
                "severity": "CRITICAL",
                "detail": f"Bullish call but price below EMA50 (downtrend)"
            })

    if pred.get("direction") == "BEARISH":
        ml_features = (pred.get("ml") or {}).get("features") or {}
        rsi = ml_features.get("rsi", 50)
        if rsi and rsi < 40:
            loopholes.append({
                "category": "conflicting_signals",
                "flag": "RSI_OVERSOLD",
                "severity": "WARNING",
                "detail": f"Bearish call but RSI {rsi:.0f} < 40 (oversold bounce risk)"
            })

    if pred.get("signal_count", 0) == 0 and pred.get("confidence") in ("HIGH", "MEDIUM"):
        loopholes.append({
            "category": "conflicting_signals",
            "flag": "NO_STRATEGY_SIGNALS",
            "severity": "CRITICAL",
            "detail": f"{pred.get('confidence')} confidence but no active strategy signals (AI-only)"
        })

    # 2. NEWS SENTIMENT MISMATCH
    news = pred.get("news") or {}
    if news:
        news_score = news.get("score", 0)
        direction = pred.get("direction")

        if direction == "BULLISH" and news_score <= -8:
            loopholes.append({
                "category": "news_mismatch",
                "flag": "BEARISH_NEWS",
                "severity": "WARNING",
                "detail": f"Bullish call but news score {news_score} (bearish sentiment)"
            })
        elif direction == "BEARISH" and news_score >= 8:
            loopholes.append({
                "category": "news_mismatch",
                "flag": "BULLISH_NEWS",
                "severity": "WARNING",
                "detail": f"Bearish call but news score {news_score} (bullish sentiment)"
            })
        elif direction == "NEUTRAL" and abs(news_score) >= 15:
            loopholes.append({
                "category": "news_mismatch",
                "flag": "STRONG_NEWS_CONFLICT",
                "severity": "WARNING",
                "detail": f"NEUTRAL call but strong directional news (score {news_score})"
            })

    # 3. WEAK CONVICTION INDICATORS
    if pred.get("confidence") == "HIGH" and pred.get("signal_count", 0) <= 1:
        loopholes.append({
            "category": "weak_conviction",
            "flag": "HIGH_CONF_LOW_SIGNALS",
            "severity": "CRITICAL",
            "detail": f"HIGH confidence but only {pred.get('signal_count', 0)} active signal(s)"
        })

    if pred.get("confidence") == "MEDIUM" and pred.get("signal_count", 0) == 0:
        loopholes.append({
            "category": "weak_conviction",
            "flag": "MEDIUM_CONF_NO_SIGNALS",
            "severity": "WARNING",
            "detail": "MEDIUM confidence but no strategy signals (AI-only, unvalidated)"
        })

    ml_prob = (pred.get("ml") or {}).get("probability", 0.5)
    if ml_prob and 0.45 <= ml_prob <= 0.55:
        loopholes.append({
            "category": "weak_conviction",
            "flag": "UNCERTAIN_ML_LEAN",
            "severity": "WARNING",
            "detail": f"ML probability {ml_prob:.2f} near 50% (uncertain directional lean)"
        })

    # 4. FUNDAMENTALS MISMATCH
    fund = pred.get("fundamentals") or {}
    if fund and pred.get("direction") == "BULLISH":
        pe_rel = fund.get("pe_relative")
        debt = fund.get("debt_level")
        rev_trend = fund.get("revenue_trend")
        fcf = fund.get("fcf_positive")

        if pe_rel == "EXPENSIVE" and debt in ("HIGH", "VERY_HIGH"):
            loopholes.append({
                "category": "fundamentals_mismatch",
                "flag": "EXPENSIVE_LEVERAGED",
                "severity": "WARNING",
                "detail": "Bullish on expensive, highly leveraged stock (execution risk)"
            })
        if rev_trend == "DOWN" and fcf is False:
            loopholes.append({
                "category": "fundamentals_mismatch",
                "flag": "POOR_FUNDAMENTALS",
                "severity": "WARNING",
                "detail": "Bullish but revenue declining and FCF negative"
            })

    # Calculate conviction score
    critical_count = len([l for l in loopholes if l["severity"] == "CRITICAL"])
    warning_count = len([l for l in loopholes if l["severity"] == "WARNING"])
    conviction_score = 100 - (critical_count * 30 + warning_count * 10)
    conviction_score = max(0, conviction_score)

    recommendation = "SKIP" if critical_count > 0 else ("CAUTION" if warning_count > 0 else "PROCEED")

    return {
        "loopholes": loopholes,
        "loophole_count": len(loopholes),
        "critical_count": critical_count,
        "warning_count": warning_count,
        "conviction_score": conviction_score,
        "recommendation": recommendation,
        "summary": f"{critical_count} critical, {warning_count} warnings — {recommendation.lower()}"
    }


def _analyze_specialist_performance(min_samples: int = 15) -> dict:
    """
    Analyze prediction_snapshots to identify which stocks are specialists
    for Intraday vs 1D trading. Compares win rates.
    """
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        query = """
        SELECT
          ticker,
          timeframe,
          COUNT(*) as total,
          SUM(CASE WHEN validation_result = 'HIT' THEN 1 ELSE 0 END) as hits,
          ROUND(CAST(SUM(CASE WHEN validation_result = 'HIT' THEN 1 ELSE 0 END) AS REAL) / COUNT(*), 3) as win_rate
        FROM prediction_snapshots
        WHERE validation_status = 'VALIDATED'
          AND validation_result IN ('HIT', 'MISS')
          AND timeframe IN ('INTRADAY', '1D')
        GROUP BY ticker, timeframe
        HAVING COUNT(*) >= ?
        ORDER BY win_rate DESC
        """

        cursor.execute(query, (min_samples,))
        rows = cursor.fetchall()
        conn.close()

        # Reorganize into per-stock, per-timeframe buckets
        stock_data = {}
        for ticker, timeframe, total, hits, wr in rows:
            if ticker not in stock_data:
                stock_data[ticker] = {}
            stock_data[ticker][timeframe] = {
                "win_rate": wr,
                "hits": hits,
                "total": total
            }

        # Classify specialists — 5% win rate difference threshold
        intraday_specialists = []
        one_d_specialists = []
        recommendation_map = {}

        for ticker, tf_data in stock_data.items():
            intraday_wr = tf_data.get("INTRADAY", {}).get("win_rate", 0)
            one_d_wr = tf_data.get("1D", {}).get("win_rate", 0)

            # Need both TFs to recommend specialization
            if "INTRADAY" in tf_data and "1D" in tf_data:
                diff = abs(intraday_wr - one_d_wr)

                if diff >= 0.05:  # 5% difference threshold
                    if intraday_wr > one_d_wr:
                        best_tf = "INTRADAY"
                        specialists_list = intraday_specialists
                        other_tf = "1D"
                    else:
                        best_tf = "1D"
                        specialists_list = one_d_specialists
                        other_tf = "INTRADAY"

                    company = TICKER_NAMES.get(ticker, ticker.replace(".NS", ""))

                    specialists_list.append({
                        "ticker": ticker,
                        "company": company,
                        "win_rate": tf_data[best_tf]["win_rate"],
                        "accuracy": f"{int(tf_data[best_tf]['win_rate']*100)}% ({tf_data[best_tf]['hits']}/{tf_data[best_tf]['total']})",
                        "sample_size": tf_data[best_tf]["total"],
                        "vs_other": f"{best_tf} {int(tf_data[best_tf]['win_rate']*100)}% vs {other_tf} {int(tf_data[other_tf]['win_rate']*100)}%",
                        "recommended_tf": best_tf
                    })

                    recommendation_map[ticker] = {
                        "best_tf": best_tf,
                        "best_tf_accuracy": tf_data[best_tf]["win_rate"],
                        "reason": f"{best_tf} {int(tf_data[best_tf]['win_rate']*100)}% vs {other_tf} {int(tf_data[other_tf]['win_rate']*100)}% — {int(diff*100)}% better"
                    }

        # Sort by win_rate descending
        intraday_specialists.sort(key=lambda x: x["win_rate"], reverse=True)
        one_d_specialists.sort(key=lambda x: x["win_rate"], reverse=True)

        return {
            "specialists": {
                "INTRADAY": intraday_specialists[:10],
                "1D": one_d_specialists[:10]
            },
            "recommendation_map": recommendation_map,
            "generated_at": datetime.now().isoformat(),
            "sample_size_total": len(stock_data),
            "min_samples_threshold": min_samples
        }
    except Exception as e:
        return {
            "error": str(e),
            "specialists": {"INTRADAY": [], "1D": []},
            "recommendation_map": {},
            "sample_size_total": 0
        }


# ── TOP 5 ─────────────────────────────────────────────────────────────────────

def _start_top5_background(force_universe_refresh: bool = False) -> None:
    """Start a background thread to compute top5 picks and populate the cache."""
    global _TOP5_COMPUTING
    import threading

    def _publish_progress(payload: dict) -> None:
        """Store the latest progress snapshot from get_top5_picks for /api/top5 to serve."""
        try:
            snap = dict(payload)
            snap["generated_at"] = snap.get("generated_at")
            with _TOP5_PROGRESS_LOCK:
                _TOP5_PROGRESS.clear()
                _TOP5_PROGRESS.update(snap)
        except Exception as _pe:
            app.logger.debug("top5 progress publish failed: %s", _pe)

    def _run():
        global _TOP5_COMPUTING
        _t5_started = time.time()
        app.logger.info("[TOP5] background compute started (force_universe_refresh=%s)", force_universe_refresh)
        try:
            result = get_top5_picks(
                force_universe_refresh=force_universe_refresh,
                progress_cb=_publish_progress,
            )
            if not result.get("market"):
                result["market"] = _watchlist_market_ctx()
            _archive_top5_predictions(result)
            mkt = nse_market_status()
            if not mkt["is_trading_day"] or mkt["status"] in ("PRE_MARKET", "POST_MARKET"):
                result["market_closed"] = {"status": mkt["status"], "message": mkt["message"], "next_open": mkt.get("next_open")}
            picks = result.get("picks", [])
            has_ai_unavailable = any(
                tf_data.get("no_trade_reason") == "ai_unavailable"
                for p in picks
                for tf_data in p.get("timeframes", {}).values()
                if isinstance(tf_data, dict)
            )
            result["has_ai_unavailable"] = has_ai_unavailable
            # IST-midnight reset: same picks shouldn't persist across market sessions.
            # AI-unavailable case uses 120s so the next request triggers a recompute
            # after providers recover, rather than serving stale no-AI results all day.
            effective_ttl = 120 if has_ai_unavailable else _cache_ttl_for_tf("1D")
            _TOP5_CACHE["top5"] = {
                "ts": time.time(),
                "reset_at": time.time() + effective_ttl,
                "result": result,
                "archived": True,
            }
            app.logger.info(
                "[TOP5] background compute done: %d picks in %.1fs (ai_unavailable=%s, ttl=%ds)",
                len(picks), time.time() - _t5_started, has_ai_unavailable, effective_ttl,
            )
        except Exception as exc:
            app.logger.warning("Background top5 compute failed: %s", exc)
            # Cache a genuine error result (short TTL) instead of leaving the cache cold.
            # A cold cache makes every poll re-report "computing", so the UI spins forever.
            # Surfacing the real reason lets the frontend show an actionable error and
            # retry after the short TTL expires.
            _TOP5_CACHE["top5"] = {
                "ts": time.time(),
                "reset_at": time.time() + 120,
                "result": {
                    "picks": [],
                    "market": _watchlist_market_ctx(),
                    "generated_at": None,
                    "error": f"Top-picks scan failed: {exc}",
                    "no_picks_reason": f"Scan failed — {exc}. Retrying automatically.",
                },
                "archived": True,
            }
        finally:
            with _TOP5_COMPUTING_LOCK:
                _TOP5_COMPUTING = False
            # Compute finished — clear the streaming snapshot so /api/top5 serves the
            # final cached result rather than a stale partial one.
            with _TOP5_PROGRESS_LOCK:
                _TOP5_PROGRESS.clear()

    # Caller already holds _TOP5_COMPUTING_LOCK — set flag directly (no re-acquire)
    _TOP5_COMPUTING = True
    # Reset any progress snapshot from a previous run before starting fresh.
    with _TOP5_PROGRESS_LOCK:
        _TOP5_PROGRESS.clear()
    threading.Thread(target=_run, daemon=True, name="top5-compute").start()


@app.route("/api/top5")
def top5():
    global _TOP5_COMPUTING
    force_refresh = request.args.get("refresh") == "1"
    cache_key = "top5"
    now = time.time()
    entry = _TOP5_CACHE.get(cache_key)
    cache_fresh = entry and now < entry.get("reset_at", entry["ts"] + _TOP5_CACHE_TTL)

    # On force refresh, clear API + predictor caches so the next compute is truly fresh.
    if force_refresh:
        _TOP5_CACHE.pop(cache_key, None)
        clear_runtime_caches()
        entry = None
        cache_fresh = False

    if not force_refresh and cache_fresh:
        if not entry.get("archived"):
            _archive_top5_predictions(entry["result"])
            entry["archived"] = True
        result = _with_live_prices(entry["result"])
        # Add loophole checking to top5 picks
        if result.get("picks"):
            for pick in result["picks"]:
                if pick.get("direction") and pick["direction"] not in ("N/A", "NEUTRAL"):
                    # Get best TF prediction for loophole checking
                    best_tf = pick.get("best_tf", "1D")
                    tf_data = pick.get("timeframes", {}).get(best_tf, {})
                    if tf_data and isinstance(tf_data, dict) and not tf_data.get("error"):
                        # Build a minimal pred dict for audit
                        pred_dict = {
                            "ticker": pick.get("ticker"),
                            "direction": tf_data.get("direction"),
                            "confidence": tf_data.get("confidence"),
                            "signal_count": tf_data.get("signal_count", 0),
                            "price": pick.get("price"),
                            "ml": pick.get("ml", {}),
                            "news": pick.get("news", {}),
                        }
                        loopholes = _audit_prediction(pred_dict)
                        if loopholes.get("loophole_count", 0) > 0:
                            pick["loopholes"] = loopholes
        return _json_no_store(result)

    # Cache is cold — kick off background compute and return immediately so the UI
    # doesn't hang. The frontend should poll (with ?poll=1) until "computing" is gone.
    if not cache_fresh:
        with _TOP5_COMPUTING_LOCK:
            if not _TOP5_COMPUTING:
                _start_top5_background(force_universe_refresh=force_refresh)
        # Serve stale result immediately while background recomputes (better UX than spinner)
        if entry and not force_refresh:
            stale_result = dict(entry["result"])
            stale_result["_stale"] = True
            result = _with_live_prices(stale_result)
            # Add loophole checking to stale picks too
            if result.get("picks"):
                for pick in result["picks"]:
                    if pick.get("direction") and pick["direction"] not in ("N/A", "NEUTRAL"):
                        best_tf = pick.get("best_tf", "1D")
                        tf_data = pick.get("timeframes", {}).get(best_tf, {})
                        if tf_data and isinstance(tf_data, dict) and not tf_data.get("error"):
                            pred_dict = {
                                "ticker": pick.get("ticker"),
                                "direction": tf_data.get("direction"),
                                "confidence": tf_data.get("confidence"),
                                "signal_count": tf_data.get("signal_count", 0),
                                "price": pick.get("price"),
                                "ml": pick.get("ml", {}),
                                "news": pick.get("news", {}),
                            }
                            loopholes = _audit_prediction(pred_dict)
                            if loopholes.get("loophole_count", 0) > 0:
                                pick["loopholes"] = loopholes
            return _json_no_store(result)
        # No stale result to serve — stream the live progress snapshot so ready cards
        # render immediately (per-card) instead of waiting for the whole scan to finish.
        with _TOP5_PROGRESS_LOCK:
            progress = dict(_TOP5_PROGRESS) if _TOP5_PROGRESS else None
        if progress:
            progress["computing"] = True
            if progress.get("picks"):
                progress = _with_live_prices(progress)
            return _json_no_store(progress)
        return _json_no_store({
            "computing": True,
            "phase": "starting",
            "picks": [],
            "market": {},
            "generated_at": None,
            "message": "Top picks are being computed — check back in ~2 minutes.",
        })



# ── WATCHLIST ─────────────────────────────────────────────────────────────────

@app.route("/api/watchlist", methods=["GET"])
def watchlist_get():
    return _json_no_store({"watchlist": db.get_watchlist()})


@app.route("/api/watchlist", methods=["POST"])
def watchlist_add():
    data   = request.get_json(force=True)
    ticker = data.get("ticker", "").upper().strip()
    name   = data.get("name", _bare(ticker))
    if not ticker:
        return jsonify({"error": "ticker required"}), 400
    t = _normalise(ticker)
    # Quick existence check via multi-source fallback chain — refuse unknown tickers early
    if fetch_live_price(t) is None:
        suggestion = ""
        bare = _bare(t)
        candidates = [k for k in ["STARHEALTH.NS","STARCEMENT.NS","BLUESTARCO.NS","LTIM.NS","COFORGE.NS"]
                      if bare.upper() in k]
        if candidates:
            suggestion = f" Did you mean: {', '.join(candidates[:2])}?"
        return jsonify({"error": f"Ticker {t} not found on NSE — it may be delisted or renamed.{suggestion}"}), 400
    # Check that ≥200 bars of 1-year history exist (required for predictions)
    try:
        sc, _, _, _ = fetch_ohlcv(t, period="1y")
        bars = sc[t].dropna() if t in sc.columns else []
        if len(bars) < 200:
            return jsonify({"error": f"{t} has only {len(bars)} days of history (need 200+). Predictions require at least 1 year of data."}), 400
    except Exception:
        pass  # transient failure — allow the add; prediction will surface the error
    if not name or name == _bare(ticker):
        name = TICKER_NAMES.get(t, _bare(t))
    item = db.add_to_watchlist(t, name)
    return jsonify(item), 201


@app.route("/api/watchlist/<ticker>", methods=["DELETE"])
def watchlist_remove(ticker: str):
    t = _normalise(ticker)
    removed = db.remove_from_watchlist(t)
    if removed:
        for _tf in ("INTRADAY", "1D", "3D"):
            _WATCHLIST_PICK_CACHE.pop((t, _tf), None)
        return jsonify({"removed": t})
    return jsonify({"error": "Not found"}), 404


def _watchlist_market_ctx() -> dict:
    """Fetch market context once and reuse across watchlist predictions."""
    from predictor_core import _get_vix, _get_nifty_gate, _get_macro_gate
    from concurrent.futures import ThreadPoolExecutor, as_completed as _as_completed

    results: dict = {}
    with ThreadPoolExecutor(max_workers=3) as _ex:
        futs = {
            _ex.submit(_get_vix): "vix",
            _ex.submit(_get_nifty_gate): "nifty",
            _ex.submit(_get_macro_gate): "macro",
        }
        for f in _as_completed(futs):
            key = futs[f]
            try:
                results[key] = f.result()
            except Exception:
                results[key] = None

    vix_level, vix_label = results.get("vix") or (18.0, "UNKNOWN — assume moderate")
    nifty_ok, nifty_label = results.get("nifty") or (True, "")
    macro_ok, macro_label = results.get("macro") or (True, "")
    return {
        "vix_level": vix_level,
        "vix_label": vix_label,
        "nifty_ok": nifty_ok,
        "nifty_label": nifty_label,
        "macro_ok": macro_ok,
        "macro_label": macro_label,
    }


def _build_watchlist_pick(item: dict, preds: dict) -> tuple[dict, dict]:
    """Build one watchlist pick payload from timeframe predictions."""
    TIMEFRAMES = ["INTRADAY", "1D"]  # 3D + 5D removed — INTRADAY/1D are the shown horizons

    anchor_tf = next(
        (tf for tf in ["1D", "INTRADAY"] if preds.get(tf) and not preds[tf].get("error")),
        None,
    )
    anchor = (
        preds.get(anchor_tf)
        if anchor_tf
        else (preds.get("1D") or preds.get("INTRADAY") or {})
    )

    if not anchor or anchor.get("error"):
        live = _current_price(item["ticker"], strict=True)
        fallback_tf = {
            tf: {
                "direction": "N/A",
                "confidence": "N/A",
                "expected_return_range": "N/A",
                "no_trade_reason": "data_error",
                "signal_count": 0,
                "ret_lo": 0,
                "ret_hi": 0,
                "midpoint": 0,
                "expected_entry_price": None,
                "expected_target_price": None,
                "target_price_lo": None,
                "target_price_hi": None,
                "predicted_direction": None,
                "predicted_return_lo": None,
                "predicted_return_hi": None,
                "ai_forecast": None,
                "stop_loss": None,
                "stop_loss_pct": None,
                "min_target": None,
                "actual_rr": None,
            }
            for tf in TIMEFRAMES
        }
        err_text = "Data unavailable"
        for tf in TIMEFRAMES:
            p = preds.get(tf) or {}
            if p.get("error"):
                err_text = _classify_watchlist_warning(p.get("error"))
                break
        return ({
            "ticker": item["ticker"],
            "company": item.get("name") or item["ticker"],
            "price": live or 0,
            "direction": "NEUTRAL",
            "confidence": "LOW",
            "warning": err_text,
            "timeframes": fallback_tf,
            "news": {},
            "risk": {},
            "signals": {},
        }, {})

    timeframes: dict = {}
    for tf in TIMEFRAMES:
        p = preds.get(tf, {})
        if not p or p.get("error"):
            timeframes[tf] = {
                "direction": "N/A",
                "confidence": "N/A",
                "expected_return_range": "N/A",
                "no_trade_reason": "data_error",
                "signal_count": 0,
                "ret_lo": 0,
                "ret_hi": 0,
                "midpoint": 0,
            }
        else:
            r = p.get("risk") or {}
            tp = p.get("trade_plan") or {}
            timeframes[tf] = {
                "expected_return_range": p.get("expected_return_range"),
                "midpoint": p.get("midpoint", 0),
                "ret_lo": p.get("ret_lo", 0),
                "ret_hi": p.get("ret_hi", 0),
                "expected_entry_price": tp.get("expected_entry_price", p.get("expected_entry_price", p.get("price"))),
                "entry_basis": tp.get("entry_basis", p.get("entry_basis")),
                "entry_buffer_pct": tp.get("entry_buffer_pct", p.get("entry_buffer_pct", 0.0)),
                "max_chase_pct": tp.get("max_chase_pct", p.get("max_chase_pct", 0.0)),
                "gapped_past_target": tp.get("gapped_past_target", p.get("gapped_past_target", False)),
                "expected_target_price": tp.get("expected_target_price", p.get("expected_target_price", r.get("min_target"))),
                "target_price_lo": tp.get("target_price_lo", p.get("target_price_lo")),
                "target_price_hi": tp.get("target_price_hi", p.get("target_price_hi")),
                "direction": p.get("direction"),
                "confidence": p.get("confidence"),
                "no_trade_reason": p.get("no_trade_reason"),
                "range_bound": p.get("range_bound", False),
                "ai_disclaimer": p.get("ai_disclaimer"),
                "signal_count": p.get("signal_count", 0),
                "intraday_final_call": p.get("intraday_final_call"),
                "final_call_time": p.get("final_call_time"),
                "intraday_premarket": p.get("intraday_premarket"),
                "intraday_reevaluated": p.get("intraday_reevaluated"),
                "reeval_time": p.get("reeval_time"),
                "prev_target": p.get("prev_target"),
                "predicted_direction": p.get("predicted_direction"),
                "predicted_return_lo": p.get("predicted_return_lo"),
                "predicted_return_hi": p.get("predicted_return_hi"),
                "ai_forecast": p.get("ai_forecast"),
                "ai_target_lo": (p.get("ai_forecast") or {}).get("target_price_lo"),
                "ai_target_hi": (p.get("ai_forecast") or {}).get("target_price_hi"),
                "ai_matched_strategy": (p.get("ai_forecast") or {}).get("matched_strategy"),
                "stop_loss": r.get("stop_loss"),
                "stop_loss_pct": r.get("stop_loss_pct"),
                "min_target": r.get("min_target"),
                "actual_rr": r.get("actual_rr"),
            }

    tf_primary = timeframes.get("1D", {})
    tf_primary_ai = (tf_primary.get("ai_forecast") or {})
    primary_direction = (
        tf_primary_ai.get("direction")
        or tf_primary.get("predicted_direction")
        or tf_primary.get("direction")
        or anchor.get("direction", "NEUTRAL")
    )
    primary_confidence = (
        tf_primary_ai.get("confidence")
        or tf_primary.get("confidence")
        or anchor.get("confidence", "LOW")
    )

    live = _current_price(item["ticker"], strict=True) or _current_price(item["ticker"], strict=False)
    display_price = live if live is not None else anchor.get("price", 0)

    # Refresh entry prices from the current live price so cached predictions don't show
    # stale ₹ anchors. Buffers match ENTRY_BUFFER_BY_TIMEFRAME in predictor_core.
    _entry_buffers = {"INTRADAY": 0.001, "1D": 0.002}
    if live:
        for _tf, _buf in _entry_buffers.items():
            _tf_d = timeframes.get(_tf, {})
            if isinstance(_tf_d, dict) and _tf_d.get("expected_entry_price") is not None:
                timeframes[_tf]["expected_entry_price"] = round(live * (1 + _buf), 2)
        # Re-anchor target ranges to the live price too — otherwise a cached prediction shows
        # a target computed off the prior close that the live (e.g. pre-market gap) price has
        # already blown past ("BULLISH, target below current price"). Keeps the shown range
        # ahead of the current price and preserves the INTRADAY ≥1% move floor.
        for _tf in timeframes:
            _reanchor_targets_to_live(timeframes[_tf], live)

    # Pick the timeframe with the strongest directional AI call for the Trade button default.
    _conf_rank = {"HIGH": 2, "MEDIUM": 1, "LOW": 0}
    _best_tf = None  # no best bet when nothing is actionable
    _best_score = -1
    # Accept SLIGHTLY BULLISH/BEARISH too — in a bear market (Nifty below EMA200)
    # every call is downgraded to SLIGHTLY, so the strict set left best_tf None and
    # the "Recommended" badge always showed N/A.
    _actionable_dirs = ("BULLISH", "BEARISH", "SLIGHTLY BULLISH", "SLIGHTLY BEARISH")
    for _tf in ["1D", "INTRADAY"]:
        _tfdata = timeframes.get(_tf, {})
        _conf = _conf_rank.get(_tfdata.get("confidence", ""), -1)
        _dir = (_tfdata.get("direction", "") or "").upper()
        if _dir in _actionable_dirs and _conf >= _best_score:
            _best_score = _conf
            _best_tf = _tf

    # Suggested allocation for BULLISH picks (1% risk per ₹50k default capital)
    suggested_allocation = None
    suggested_shares = None
    if primary_direction == "BULLISH" and display_price and display_price > 0:
        _risk_capital = 50_000
        _sl_pct = (anchor.get("risk") or {}).get("stop_loss_pct") or 2.0
        try:
            _sl_pct = float(_sl_pct)
        except (TypeError, ValueError):
            _sl_pct = 2.0
        if _sl_pct > 0:
            _risk_per_trade = _risk_capital * 0.01  # 1% of ₹50k = ₹500
            _shares = max(1, int(_risk_per_trade / (display_price * _sl_pct / 100)))
            suggested_shares = _shares
            suggested_allocation = round(_shares * display_price, 2)

    return ({
        "ticker": item["ticker"],
        "company": anchor.get("company") or item.get("name") or item["ticker"],
        "price": display_price,
        "best_tf": _best_tf,
        "direction": primary_direction,
        "confidence": primary_confidence,
        "news": anchor.get("news", {}),
        "risk": anchor.get("risk", {}),
        "signals": anchor.get("signals", {}),
        "timeframes": timeframes,
        "suggested_allocation": suggested_allocation,
        "suggested_shares": suggested_shares,
    }, anchor.get("market", {}))


@app.route("/api/watchlist-pick/<ticker>")
def watchlist_pick_single(ticker: str):
    from datetime import datetime

    t = _normalise(ticker)
    force_refresh = request.args.get("refresh") == "1"
    now = time.time()

    wl = db.get_watchlist()
    item = next((w for w in wl if _normalise(w.get("ticker", "")) == t), None)
    if not item:
        return jsonify({"error": f"{t} is not in watchlist"}), 404

    market_ctx = _watchlist_market_ctx()
    mkt_status = nse_market_status()
    market_is_open = mkt_status.get("status") == "OPEN"
    # Pre-market (trading day, before 09:15 IST): run a labeled INTRADAY *preview* so a
    # directional lean is ready before the bell instead of a "market closed" stub.
    _is_premarket = mkt_status.get("status") == "PRE_MARKET"
    _intraday_live = market_is_open or _is_premarket

    _INTRADAY_CLOSED_STUB = {
        "no_trade_reason": "market_closed",
        "direction": "N/A",
        "confidence": "N/A",
        "signal_count": 0,
    }
    _INTRADAY_TOO_LATE_STUB = {
        "no_trade_reason": "too_close_to_close",
        "direction": "N/A",
        "confidence": "N/A",
        "signal_count": 0,
    }

    _ist = timezone(timedelta(hours=5, minutes=30))
    _now_ist = datetime.now(timezone.utc).astimezone(_ist)
    _intraday_too_late = market_is_open and (_now_ist.hour, _now_ist.minute) >= (14, 15)

    all_tfs = ["INTRADAY", "1D"]  # 3D + 5D removed from live predictions
    preds: dict = {}

    if not _intraday_live:
        preds["INTRADAY"] = _intraday_closed_value(t, _INTRADAY_CLOSED_STUB)
    elif _intraday_too_late:
        preds["INTRADAY"] = _intraday_closed_value(t, _INTRADAY_TOO_LATE_STUB)

    # Check per-TF cache; only fetch TFs whose cache is stale
    tfs_to_run = []
    for tf in all_tfs:
        if tf == "INTRADAY" and (not _intraday_live or _intraday_too_late):
            continue
        if not force_refresh:
            entry = _WATCHLIST_PICK_CACHE.get((t, tf))
            if entry and now - entry["ts"] < entry.get("ttl", _cache_ttl_for_tf(tf)):
                preds[tf] = entry["pred"]
                continue
        tfs_to_run.append(tf)

    # All TFs get AI forecasts. Provider chain: OpenRouter → Ollama → Groq → Cerebras → HF.
    # Cards render progressively as each fetch resolves — slow Ollama calls don't block others.
    _AI_TFS = set(tfs_to_run)

    def _predict(tf: str):
        start, end = timeframe_to_dates(tf)
        return tf, _gated_predict(
            t, start, end,
            _market_ctx=market_ctx,
            _run_ai_forecast=(tf in _AI_TFS),
            _ai_fast_mode=True,  # single synthesis call — 4x fewer LLM calls vs full debate
            # BOUNDED: one pass through available cloud providers + a single Ollama last-resort
            # (~70s cap), never the old minutes-long internal wait loop. A TF that can't get AI
            # right now falls through to the `timeout` reason below, which the frontend
            # auto-refetches — so the card renders its ready TFs immediately (partial results)
            # instead of the whole card blocking for up to 320s.
            _ai_fast_fail_on_rate_limit=True,
        )

    if tfs_to_run:
        # Pre-warm OHLCV + news caches concurrently so all TF threads get instant hits.
        # Previously these ran serially (OHLCV first, then news) adding up to 75s of
        # sequential pre-work before the TF pool even started.
        def _warm_news():
            try:
                from news_sentiment import fetch_and_analyze as _fn
                _fn(t, item.get("company", "") if item else "")
            except Exception:
                pass
        # NOTE: do NOT use `with ... as _warm_ex:` here — the context manager's
        # __exit__ calls shutdown(wait=True), which blocks this request until BOTH
        # warm-up fetches actually finish, even though the .result(timeout=...) calls
        # below already degrade gracefully on a slow provider. That silently defeated
        # the soft timeouts and could hang the whole watchlist request as long as
        # news_sentiment's LLM call took (worst case ~90s on Ollama fallback) —
        # surfacing as "news failing" on the first watchlist check for a ticker.
        # Explicit executor + shutdown(wait=False): the straggler keeps warming
        # caches in the background for the next check, without blocking this one.
        _warm_ex = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        try:
            _f_ohlcv = _warm_ex.submit(warm_ohlcv_cache, t, "1y")
            _f_news  = _warm_ex.submit(_warm_news)
            try:
                _f_ohlcv.result(timeout=20)
            except Exception:
                pass
            try:
                _f_news.result(timeout=65)
            except Exception:
                pass
        finally:
            _warm_ex.shutdown(wait=False)

        # All TFs submitted concurrently. exit executor without waiting (wait=False)
        # so Flask returns once the deadline fires, not when threads finish.
        # Threads still blocked on Ollama continue in background — their results
        # are lost (short TTL means the next load retries them).
        # Bounded per-TF calls (fast_fail=True) return fast on cloud (~5-20s) or after a single
        # Ollama last-resort (~35-70s). We no longer wait for the worst-case serial-Ollama path —
        # a TF still unresolved at the deadline is returned as `timeout`, and the frontend
        # auto-refetches it (background fill). This caps the user-visible wait at ~90s per card
        # instead of 320s, while ready TFs render immediately.
        _tf_wait = 90
        ex = ThreadPoolExecutor(max_workers=len(tfs_to_run))
        futures = {ex.submit(_predict, tf): tf for tf in tfs_to_run}
        done, not_done = concurrent.futures.wait(futures, timeout=_tf_wait)
        ex.shutdown(wait=False)  # don't block on in-flight Ollama calls
        for f in done:
            tf = futures[f]
            try:
                _, pred = f.result()
                preds[tf] = pred
                if not pred.get("error"):
                    _reason = pred.get("no_trade_reason")
                    # Never cache a transient 'timeout' (provider will reset shortly) — leaving it
                    # uncached lets the frontend's background refetch genuinely retry and fill in.
                    if _reason != "timeout":
                        ttl = _WATCHLIST_PICK_AI_UNAVAILABLE_TTL if _reason == "ai_unavailable" else _cache_ttl_for_tf(tf)
                        _WATCHLIST_PICK_CACHE[(t, tf)] = {"ts": now, "pred": pred, "ttl": ttl}
            except Exception as e:
                preds[tf] = {"error": str(e)}
        for f in not_done:
            tf = futures[f]
            preds[tf] = {
                "no_trade_reason": "timeout",
                "direction": "N/A",
                "confidence": "N/A",
                "signal_count": 0,
                "ret_lo": 0,
                "ret_hi": 0,
                "midpoint": 0,
            }

    # Tag a pre-market INTRADAY preview so the card can label it as a pre-open lean
    # (built before the session, not a live intraday call).
    if _is_premarket and isinstance(preds.get("INTRADAY"), dict) and not preds["INTRADAY"].get("error"):
        preds["INTRADAY"]["intraday_premarket"] = True

    pick, market = _build_watchlist_pick(item, preds)
    # Remember a fresh valid INTRADAY call so it can be shown as the session's final call
    # after the market closes.
    if "INTRADAY" in preds:
        _remember_intraday_call(t, preds["INTRADAY"])
    if tfs_to_run:
        try:
            _archive_top5_predictions({"picks": [pick]}, source="watchlist")
        except Exception as e:
            logging.warning(f"Failed to archive watchlist snapshot for {t}: {e}")

    # Add loophole checking for the primary prediction
    loopholes_result = None
    if pick.get("direction") and pick["direction"] not in ("N/A", "NEUTRAL"):
        # Get the best available prediction for loophole checking
        primary_pred = preds.get("1D") or preds.get("INTRADAY")
        if primary_pred and not primary_pred.get("error"):
            loopholes_result = _audit_prediction(primary_pred)

    result = {
        "pick": pick,
        "market": market,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    if loopholes_result:
        result["loopholes"] = loopholes_result
    if not market_is_open:
        result["market_closed"] = {
            "status": mkt_status.get("status"),
            "message": mkt_status.get("message"),
            "next_open": mkt_status.get("next_open"),
        }
    # Show "AI unavailable" banner if ANY non-INTRADAY TF has no AI.
    # All timeframes are equally important — missing AI on any one is worth surfacing.
    result["has_ai_unavailable"] = any(
        preds.get(tf, {}).get("no_trade_reason") == "ai_unavailable"
        for tf in all_tfs
        if tf != "INTRADAY"  # INTRADAY shows N/A when market is closed — don't count it
    )
    return _json_no_store(result)


@app.route("/api/watchlist-pick/<ticker>/<tf>")
@app.route("/api/pick-tf/<ticker>/<tf>")
def watchlist_pick_single_tf(ticker: str, tf: str):
    """Predict a single TF for a single ticker.
    Returns instantly from cache when fresh; otherwise runs one predict_stock_v2 call.
    Used by the frontend for progressive per-TF card loading and INTRADAY auto-refresh —
    for BOTH watchlist cards and top-pick cards, so it accepts any ticker (not only watchlist
    members). The /api/pick-tf/ alias is the explicit non-watchlist entry point."""
    from datetime import datetime

    VALID_TFS = {"INTRADAY", "1D"}  # 3D/5D retired from the live API
    tf = tf.upper()
    if tf not in VALID_TFS:
        return jsonify({"error": f"Invalid timeframe: {tf}"}), 400

    t = _normalise(ticker)
    force_refresh = request.args.get("refresh") == "1"
    now = time.time()

    market_ctx = _watchlist_market_ctx()
    mkt_status = nse_market_status()
    market_is_open = mkt_status.get("status") == "OPEN"
    _is_premarket = mkt_status.get("status") == "PRE_MARKET"

    if tf == "INTRADAY" and not market_is_open and not _is_premarket:
        _final = _get_intraday_final_call(t)
        if _final:
            return jsonify({
                "tf": tf, "ticker": t, "data": _final,
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "intraday_final_call": True,
            })
        return jsonify({
            "tf": tf, "ticker": t,
            "data": {"no_trade_reason": "market_closed", "direction": "N/A",
                     "confidence": "N/A", "signal_count": 0},
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "market_closed": True,
        })
    if tf == "INTRADAY":
        _ist = timezone(timedelta(hours=5, minutes=30))
        _now_ist = datetime.now(timezone.utc).astimezone(_ist)
        if market_is_open and (_now_ist.hour, _now_ist.minute) >= (14, 15):
            _final = _get_intraday_final_call(t)
            if _final:
                return jsonify({
                    "tf": tf, "ticker": t, "data": _final,
                    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "intraday_final_call": True,
                })
            return jsonify({
                "tf": tf, "ticker": t,
                "data": {"no_trade_reason": "too_close_to_close", "direction": "N/A",
                         "confidence": "N/A", "signal_count": 0},
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "too_close_to_close": True,
            })

    # Cache check
    _reeval_prev = None  # prior cached INTRADAY call whose target the live price just reached
    if not force_refresh:
        entry = _WATCHLIST_PICK_CACHE.get((t, tf))
        if entry and now - entry["ts"] < entry.get("ttl", _cache_ttl_for_tf(tf)):
            _cached_pred = entry["pred"]
            # INTRADAY: if the live price has already reached the cached call's target, don't
            # serve the passed target — fall through to a fresh recompute so a NEW target off
            # the current level is produced (target hit → re-evaluate). Else serve the cache.
            if (tf == "INTRADAY" and market_is_open
                    and _intraday_pred_has_target(_cached_pred)
                    and _intraday_target_reached(_cached_pred, _current_price(t, strict=False))):
                _reeval_prev = _cached_pred
            else:
                return jsonify({
                    "tf": tf, "ticker": t,
                    "data": _cached_pred,
                    "generated_at": datetime.fromtimestamp(entry["ts"]).strftime("%Y-%m-%d %H:%M"),
                    "cached": True,
                })

    start, end = timeframe_to_dates(tf)
    try:
        pred = _gated_predict(
            t, start, end,
            _market_ctx=market_ctx,
            _run_ai_forecast=True,
            _ai_fast_mode=(tf == "INTRADAY"),
            # BOUNDED (see per-ticker route): this is the frontend's background-fill call for a
            # single pending TF — it must return quickly (ready or retryable), never block minutes.
            _ai_fast_fail_on_rate_limit=True,
        )
    except Exception as e:
        pred = {"error": str(e)}

    if not pred.get("error"):
        _reason = pred.get("no_trade_reason")
        # Tag a pre-market INTRADAY preview so the frontend can label it.
        if tf == "INTRADAY" and _is_premarket:
            pred["intraday_premarket"] = True
        # Tag a re-evaluation triggered because the prior target was hit, so the UI can badge it.
        if _reeval_prev is not None and tf == "INTRADAY" and _intraday_pred_has_target(pred):
            _ist_r = timezone(timedelta(hours=5, minutes=30))
            pred["intraday_reevaluated"] = True
            pred["reeval_time"] = datetime.now(timezone.utc).astimezone(_ist_r).strftime("%H:%M")
            pred["prev_target"] = _reeval_prev.get("target_price_hi") or _reeval_prev.get("target_price_lo")
        # Never cache a transient 'timeout' (provider will reset shortly) so the background
        # refetch retries; keep 'ai_unavailable' on the short TTL for hard outages.
        if _reason != "timeout":
            ttl = _WATCHLIST_PICK_AI_UNAVAILABLE_TTL if _reason == "ai_unavailable" else _cache_ttl_for_tf(tf)
            _WATCHLIST_PICK_CACHE[(t, tf)] = {"ts": now, "pred": pred, "ttl": ttl}
        # Remember a valid INTRADAY call so it survives as the session's final call after close.
        if tf == "INTRADAY" and not _is_premarket:
            _remember_intraday_call(t, pred)

    return jsonify({
        "tf": tf, "ticker": t,
        "data": pred,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "cached": False,
    })


@app.route("/api/watchlist-picks")
def watchlist_picks():
    from datetime import datetime
    wl = db.get_watchlist()
    tickers = [item["ticker"] for item in wl]
    if not tickers:
        return _json_no_store({"picks": [], "market": {},
                       "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M")})

    # Pre-fetch market context ONCE to avoid N×3 simultaneous market data requests
    # (same pattern as rank_stocks_v2 in predictor_core.py)
    shared_ctx = _watchlist_market_ctx()
    mkt_status = nse_market_status()
    market_is_open = mkt_status.get("status") == "OPEN"
    # Pre-market (trading day, before 09:15 IST): run a labeled INTRADAY preview.
    _is_premarket = mkt_status.get("status") == "PRE_MARKET"
    _intraday_live = market_is_open or _is_premarket

    _INTRADAY_CLOSED_STUB = {
        "no_trade_reason": "market_closed",
        "direction": "N/A",
        "confidence": "N/A",
        "signal_count": 0,
    }
    _INTRADAY_TOO_LATE_STUB = {
        "no_trade_reason": "too_close_to_close",
        "direction": "N/A",
        "confidence": "N/A",
        "signal_count": 0,
    }

    _ist = timezone(timedelta(hours=5, minutes=30))
    _now_ist = datetime.now(timezone.utc).astimezone(_ist)
    _intraday_too_late = market_is_open and (_now_ist.hour, _now_ist.minute) >= (14, 15)

    tfs_to_run = (["INTRADAY", "1D"] if (_intraday_live and not _intraday_too_late)
                  else ["1D"])

    def _predict(ticker, tf):
        start, end = timeframe_to_dates(tf)
        # Cache hit → skip the LLM entirely (Option 2: per-(ticker,tf) cache, same store the
        # single-ticker route uses; TTL = 15m INTRADAY / until-IST-midnight for 1D/3D).
        entry = _WATCHLIST_PICK_CACHE.get((ticker, tf))
        if entry and time.time() - entry["ts"] < entry.get("ttl", _cache_ttl_for_tf(tf)):
            return ticker, tf, entry["pred"]
        pred = _gated_predict(ticker, start, end,
                                _market_ctx=shared_ctx,
                                _run_ai_forecast=True,
                                _ai_fast_mode=True,
                                # BOUNDED — never block the batch on one stock (see per-ticker route).
                                _ai_fast_fail_on_rate_limit=True)
        if not pred.get("error"):
            _reason = pred.get("no_trade_reason")
            # Never cache a transient 'timeout' (provider will reset shortly) so the next scan
            # retries; keep 'ai_unavailable' on the short TTL for hard outages.
            if _reason != "timeout":
                ttl = _WATCHLIST_PICK_AI_UNAVAILABLE_TTL if _reason == "ai_unavailable" else _cache_ttl_for_tf(tf)
                _WATCHLIST_PICK_CACHE[(ticker, tf)] = {"ts": time.time(), "pred": pred, "ttl": ttl}
        return ticker, tf, pred

    # ── Phase 0: pre-warm OHLCV caches (parallel, 40s wall-clock cap) ────────
    # OHLCV only — no news LLM calls here. With 9+ tickers, warming news would
    # exhaust provider rate limits before AI forecast even runs.
    # The per-ticker lock in news_sentiment already serializes news LLM calls
    # during Phase 1 predictions, so thundering herd is already prevented.

    def _warm_one(item):
        warm_ohlcv_cache(item["ticker"], "1y")

    warm_ex = ThreadPoolExecutor(max_workers=min(len(tickers), 4))
    warm_futures = {warm_ex.submit(_warm_one, item): item["ticker"] for item in wl}
    warm_done, warm_pending = concurrent.futures.wait(warm_futures, timeout=40)
    for wf in warm_done:
        try:
            wf.result()
        except Exception as e:
            app.logger.warning("Warm error for %s: %s", warm_futures[wf], e)
    warm_ex.shutdown(wait=False)

    # ── Phase 1: run all timeframe × ticker predictions ───────────────────────
    # OHLCV is cached per ticker (5-min TTL) so 4 TF calls for the same ticker
    # share one cached download — no thundering herd.
    # Wall-clock capped at 160s so warm(40s) + predict(160s) ≤ 200s total.
    tf_results: dict = {}
    if not _intraday_live:
        for t in tickers:
            tf_results.setdefault(t, {})["INTRADAY"] = _intraday_closed_value(t, _INTRADAY_CLOSED_STUB)
    elif _intraday_too_late:
        for t in tickers:
            tf_results.setdefault(t, {})["INTRADAY"] = _intraday_closed_value(t, _INTRADAY_TOO_LATE_STUB)
    # Limit to 3 concurrent tickers (×3 TFs = 9 threads) to avoid exhausting
    # provider rate limits. Cloud providers handle 3 tickers in ~15-30s; Ollama
    # handles ~2 tickers in 170s. Incomplete tickers show as timeout.
    ex = ThreadPoolExecutor(max_workers=min(len(tickers), 3) * len(tfs_to_run))
    futures = {ex.submit(_predict, t, tf): (t, tf)
               for t in tickers for tf in tfs_to_run}
    # Bounded calls (fast_fail=True) + cache hits → most resolve fast; unresolved ones drop to the
    # `timeout` stub below (frontend auto-refetches). 90s cap instead of 200s blocking.
    done, not_done = concurrent.futures.wait(futures, timeout=90)
    for f in done:
        t, tf = futures[f]
        try:
            _, _, pred = f.result()
            tf_results.setdefault(t, {})[tf] = pred
        except Exception as e:
            tf_results.setdefault(t, {})[tf] = {"error": str(e)}
    for f in not_done:
        t, tf = futures[f]
        tf_results.setdefault(t, {})[tf] = {"no_trade_reason": "timeout", "direction": "N/A",
                                            "confidence": "N/A", "signal_count": 0}
    ex.shutdown(wait=False)

    picks = []
    market: dict = {}
    for item in wl:
        ticker = item["ticker"]
        preds = tf_results.get(ticker, {})
        # Tag a pre-market INTRADAY preview so the card can label it as a pre-open lean.
        if _is_premarket and isinstance(preds.get("INTRADAY"), dict) and not preds["INTRADAY"].get("error"):
            preds["INTRADAY"]["intraday_premarket"] = True
        # Remember a fresh valid INTRADAY call so it shows as the session's final call after close.
        if "INTRADAY" in preds:
            _remember_intraday_call(ticker, preds["INTRADAY"])
        pick, pick_market = _build_watchlist_pick(item, preds)

        # Add loophole checking for the primary prediction
        loopholes_result = None
        if pick.get("direction") and pick["direction"] not in ("N/A", "NEUTRAL"):
            primary_pred = preds.get("1D") or preds.get("INTRADAY")
            if primary_pred and not primary_pred.get("error"):
                loopholes_result = _audit_prediction(primary_pred)
                if loopholes_result.get("loophole_count", 0) > 0:
                    pick["loopholes"] = loopholes_result

        picks.append(pick)
        if not market and pick_market:
            market = pick_market

    # Persist snapshots for validation tracking
    try:
        _archive_top5_predictions({"picks": picks}, source="watchlist")
    except Exception as e:
        logging.warning(f"Failed to archive watchlist snapshots: {e}")

    # Send WhatsApp alerts for HIGH-confidence predictions (no-op if env vars not set)
    try:
        from whatsapp_alerts import send_bulk_alerts
        all_tf_preds = [tf_pred for pick in picks for tf_pred in pick.get("timeframes", {}).values() if isinstance(tf_pred, dict)]
        send_bulk_alerts(all_tf_preds)
    except Exception:
        pass

    has_ai_unavail = any(
        pred.get("no_trade_reason") == "ai_unavailable"
        for pick in picks
        for pred in pick.get("timeframes", {}).values()
        if isinstance(pred, dict)
    )
    resp: dict = {"picks": picks, "market": market,
                  "has_ai_unavailable": has_ai_unavail,
                  "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    if not market_is_open:
        resp["market_closed"] = {
            "status": mkt_status.get("status"),
            "message": mkt_status.get("message"),
            "next_open": mkt_status.get("next_open"),
        }
    return _json_no_store(resp)


@app.route("/api/portfolio-insight/<path:ticker>")
def portfolio_insight(ticker: str):
    """Return INTRADAY/1D prediction + news bundle for a portfolio ticker."""
    from datetime import datetime

    t = _normalise(ticker)
    force_refresh = request.args.get("refresh") == "1"
    now = time.time()

    if not force_refresh:
        entry = _PORTFOLIO_INSIGHT_CACHE.get(t)
        if entry and now - entry["ts"] < _PORTFOLIO_INSIGHT_TTL:
            return _json_no_store(entry["result"])

    market_ctx = _watchlist_market_ctx()
    preds: dict = {}

    def _predict(tf: str):
        start, end = timeframe_to_dates(tf)
        return tf, predict_stock_v2(
            t, start, end,
            _market_ctx=market_ctx,
            _run_ai_forecast=True,
            _ai_fast_mode=False,
            _ai_fast_fail_on_rate_limit=True,
        )

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(_predict, tf): tf for tf in ["INTRADAY", "1D"]}
        for f in as_completed(futures):
            tf = futures[f]
            try:
                _, pred = f.result()
                preds[tf] = pred
            except Exception as e:
                preds[tf] = {"error": str(e)}

    name = get_universe().get(t, _bare(t))
    pick, market = _build_watchlist_pick({"ticker": t, "name": name}, preds)
    result = {
        "pick": pick,
        "market": market,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    _PORTFOLIO_INSIGHT_CACHE[t] = {"ts": now, "result": result}
    return _json_no_store(result)


# ── TRADES ────────────────────────────────────────────────────────────────────

@app.route("/api/trades/open", methods=["GET"])
def trades_open():
    """Return all open trades with live prices and P&L calculations."""
    trades = db.get_open_trades_with_live_prices()
    if not trades:
        return _json_no_store({"trades": []})

    # Enrich with P&L calculations
    for t in trades:
        if t.get("current_price"):
            price = t["current_price"]
            if t["direction"] == "LONG":
                t["unrealised_pnl"]     = round((price - t["entry_price"]) * t["shares"], 2)
                t["unrealised_pnl_pct"] = round((price - t["entry_price"]) / t["entry_price"] * 100, 2)
            else:
                t["unrealised_pnl"]     = round((t["entry_price"] - price) * t["shares"], 2)
                t["unrealised_pnl_pct"] = round((t["entry_price"] - price) / t["entry_price"] * 100, 2)

    resp = jsonify({"trades": trades})
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/api/trades/history", methods=["GET"])
def trades_history():
    return _json_no_store({"trades": db.get_trade_history()})


@app.route("/api/trades", methods=["POST"])
def trades_open_new():
    data = request.get_json(force=True)
    required = ["ticker", "direction", "entry_price", "shares"]
    for f in required:
        if f not in data:
            return jsonify({"error": f"{f} is required"}), 400

    try:
        _shares_val = int(data["shares"])
    except (TypeError, ValueError):
        return jsonify({"error": "shares must be a positive integer"}), 400
    if _shares_val <= 0:
        return jsonify({"error": "shares must be > 0"}), 400

    # Position sizing: this is a PAPER-TRADING app, so the Kelly-based size guardrail is
    # advisory only — it must NEVER block a trade. Compute an optional soft warning (against
    # the actual account capital) and attach it to the response, but always let the trade
    # through so the user can freely test any position size.
    ticker = _normalise(data["ticker"])
    entry_price = float(data["entry_price"])
    kelly_warning = None
    try:
        risk_metrics = risk_engine.get_portfolio_risk()
        kelly_pct = risk_metrics.get("suggested_position_size_pct", 5.0)
        if not kelly_pct or kelly_pct < _MIN_KELLY_LIMIT_PCT:
            kelly_pct = _MIN_KELLY_LIMIT_PCT
        kelly_amount = _ACCOUNT_CAPITAL * kelly_pct / 100.0
        open_value = db.get_open_position_value(ticker)
        new_value = _shares_val * entry_price
        if open_value + new_value > kelly_amount:
            kelly_warning = (
                f"Note: this ₹{open_value + new_value:,.0f} position is above the suggested "
                f"Kelly size of ₹{kelly_amount:,.0f} ({kelly_pct:.0f}% of capital). "
                f"Allowed for paper trading."
            )
    except Exception:
        kelly_warning = None

    direction = data["direction"].upper()
    max_chase_pct = float(data.get("max_chase_pct") or 0)

    # ── Stop-loss / target sanity guard ──────────────────────────────────────
    # The stop and target are copied from the prediction, which computed them at the ANCHOR price
    # (prior close / est. open / live-at-scan). The user's ACTUAL entry can drift from that anchor
    # (gap, delayed click), which can leave a LONG stop ABOVE entry or a SHORT stop BELOW it —
    # nonsense that would trigger an INSTANT stop-out (e.g. entry ₹1495.9, stop ₹1500 on a LONG).
    # Re-anchor any wrong-side stop/target to the actual entry, preserving the intended distance
    # (floored to a 1% minimum so the stop isn't razor-thin).
    _MIN_DIST_FRAC = 0.01
    _sl_in = _safe_float(data.get("stop_loss"))
    if _sl_in is not None and _sl_in > 0 and entry_price > 0:
        _dist = max(abs(entry_price - _sl_in), entry_price * _MIN_DIST_FRAC)
        if direction == "LONG" and _sl_in >= entry_price:
            data["stop_loss"] = round(entry_price - _dist, 2)
        elif direction == "SHORT" and _sl_in <= entry_price:
            data["stop_loss"] = round(entry_price + _dist, 2)
    _tgt_in = _safe_float(data.get("target"))
    if _tgt_in is not None and _tgt_in > 0 and entry_price > 0:
        _tdist = max(abs(_tgt_in - entry_price), entry_price * _MIN_DIST_FRAC)
        if direction == "LONG" and _tgt_in <= entry_price:
            data["target"] = round(entry_price + _tdist, 2)
        elif direction == "SHORT" and _tgt_in >= entry_price:
            data["target"] = round(entry_price - _tdist, 2)


    merge_into_id = None
    existing_position = db.get_open_trade(ticker, direction)
    if existing_position:
        if not data.get("confirm_merge"):
            return jsonify({
                "error": "Position already open",
                "code": "position_exists",
                "existing": {
                    "id": existing_position["id"],
                    "entry_price": existing_position["entry_price"],
                    "shares": existing_position["shares"],
                    "entry_time": existing_position["opened_at"]
                },
                "new_trade": {
                    "entry_price": entry_price,
                    "shares": int(data["shares"])
                },
                "action_required": "Resubmit with confirm_merge=true to merge positions"
            }), 409
        merge_into_id = existing_position["id"]

    # Determine if this is a limit order (price not yet reached) or market order.
    # Tolerance of 0.1% covers normal bid/ask spread.
    # LONG limit: entry is below current market → order waits until price drops.
    # SHORT limit: entry is above current market → order waits until price rises.
    order_type = "MARKET"
    status = "OPEN"
    live = _current_price(ticker)
    live_price_at_entry = None
    price_deviation_pct = None

    if live is not None:
        # Hard price floor: reject if entry deviates >5% from live market.
        deviation = abs(entry_price - live) / live * 100
        if deviation > 5.0:
            return jsonify({
                "error": f"Entry price ₹{entry_price:.2f} deviates {deviation:.1f}% from live ₹{live:.2f}. Max allowed: 5%."
            }), 400
        live_price_at_entry = live
        price_deviation_pct = deviation

        # No-chase guard: reject if live has already moved too far from
        # the planned entry. Keeps execution aligned with model assumptions.
        if max_chase_pct > 0:
            chase_frac = max_chase_pct / 100.0
            if direction == "LONG" and live > entry_price * (1 + chase_frac):
                return jsonify({
                    "error": (
                        f"No-chase rule: live price ₹{live:.2f} is above allowed entry "
                        f"band (₹{entry_price:.2f} + {max_chase_pct:.2f}%). Skip this trade."
                    )
                }), 400
            if direction == "SHORT" and live < entry_price * (1 - chase_frac):
                return jsonify({
                    "error": (
                        f"No-chase rule: live price ₹{live:.2f} is below allowed entry "
                        f"band (₹{entry_price:.2f} - {max_chase_pct:.2f}%). Skip this trade."
                    )
                }), 400

        tol = 0.001
        if direction == "LONG" and entry_price < live * (1 - tol):
            order_type = "LIMIT"
            status = "PENDING"
        elif direction == "SHORT" and entry_price > live * (1 + tol):
            order_type = "LIMIT"
            status = "PENDING"

    name = data.get("name") or get_universe().get(ticker, _bare(ticker))

    pred_data = data.get("prediction_data")
    if isinstance(pred_data, dict):
        pred_data = json.dumps(pred_data)

    strategy = data.get("strategy")
    timeframe = data.get("timeframe")

    # Auto-fill context for manual entries so post-mortems and analytics remain actionable.
    if (not strategy or not timeframe or not pred_data):
        enriched = _autofill_trade_context(ticker)
        if enriched:
            strategy = strategy or enriched.get("strategy")
            timeframe = timeframe or enriched.get("timeframe")
            if not pred_data and enriched.get("prediction_data"):
                pred_data = json.dumps(enriched["prediction_data"])

    # Link trade to a prediction snapshot so timeframe-expiry auto-close can validate accuracy.
    snap_id = None
    auto_close_date = None
    if timeframe and timeframe not in ("", "N/A") and pred_data:
        try:
            _pd = json.loads(pred_data) if isinstance(pred_data, str) else pred_data
            _ai = (_pd.get("ai") or _pd.get("ai_forecast") or {})
            _snap_dir = (
                _ai.get("direction")
                or _pd.get("direction")
                or direction_to_snap(direction)
            )
            _snap_conf = _ai.get("confidence") or _pd.get("confidence") or "LOW"
            snap_id = db.save_prediction_snapshot(
                ticker=ticker,
                timeframe=timeframe,
                direction=_snap_dir,
                confidence=_snap_conf,
                target_price_lo=float(_ai.get("target_price_lo") or data.get("target") or entry_price),
                target_price_hi=float(_ai.get("target_price_hi") or data.get("target") or entry_price),
                predicted_return_lo=float(_ai.get("predicted_return_lo") or 0),
                predicted_return_hi=float(_ai.get("predicted_return_hi") or 0),
                current_price=entry_price,
                snapshot_source="trade",
                snapshot_data=pred_data if isinstance(pred_data, str) else json.dumps(pred_data),
            )
            auto_close_date = db._trading_deadline(timeframe)
        except Exception as _e:
            app.logger.warning("Snapshot save skipped: %s", _e)

    # If merging into existing position, use merge_into_position; otherwise create new trade
    if merge_into_id:
        merge_confirmed_at = datetime.now().isoformat()
        merged = db.merge_into_position(merge_into_id, int(data["shares"]), entry_price)
        # Create audit trail entry with merge info
        trade = db.open_trade(
            ticker=ticker,
            name=name,
            direction=direction,
            entry_price=entry_price,
            shares=int(data["shares"]),
            stop_loss=data.get("stop_loss"),
            target=data.get("target"),
            strategy=strategy,
            timeframe=timeframe,
            prediction_data=pred_data,
            order_type=order_type,
            status="CLOSED",  # Mark merge records as closed for audit
            snapshot_id=snap_id,
            auto_close_date=auto_close_date,
            live_price_at_entry=live_price_at_entry,
            price_deviation_pct=price_deviation_pct,
            merged_into_trade_id=merge_into_id,
            merge_confirmed_at=merge_confirmed_at,
        )
        merged["_merged"] = True
        merged["_audit_trade_id"] = trade["id"]  # Link to audit record
        trade = merged
    else:
        trade = db.open_trade(
            ticker=ticker,
            name=name,
            direction=direction,
            entry_price=entry_price,
            shares=int(data["shares"]),
            stop_loss=data.get("stop_loss"),
            target=data.get("target"),
            strategy=strategy,
            timeframe=timeframe,
            prediction_data=pred_data,
            order_type=order_type,
            status=status,
            snapshot_id=snap_id,
            auto_close_date=auto_close_date,
            live_price_at_entry=live_price_at_entry,
            price_deviation_pct=price_deviation_pct,
        )
    threading.Thread(target=db.hf_upload_db, daemon=True).start()
    if kelly_warning and isinstance(trade, dict):
        trade["kelly_warning"] = kelly_warning
    return jsonify(trade), 201


@app.route("/api/orders/pending", methods=["GET"])
def orders_pending():
    orders = db.get_pending_orders()
    if not orders:
        return _json_no_store({"orders": []})

    def _enrich_order(order):
        price = _current_price(order["ticker"])
        if price is not None:
            order["current_price"] = price
        return order

    with ThreadPoolExecutor(max_workers=min(len(orders), 5)) as pool:
        orders = list(pool.map(_enrich_order, orders))

    return _json_no_store({"orders": orders})


@app.route("/api/orders/check", methods=["POST"])
def orders_check():
    """Check all pending orders against live prices and fill any that qualify."""
    pending = db.get_pending_orders()
    filled = []
    still_pending = []

    for order in pending:
        live = _current_price(order["ticker"])
        if live is None:
            still_pending.append(order)
            continue

        direction = order["direction"]
        limit = order["entry_price"]
        tol = 0.001

        # Fill when live price reaches the limit — no extra tolerance at fill time.
        # The creation-side tolerance already placed the limit below market for LONG
        # (entry < live * 0.999), so the fill check just needs live <= entry.
        should_fill = (
            (direction == "LONG" and live <= limit) or
            (direction == "SHORT" and live >= limit)
        )

        if should_fill:
            filled_trade = db.fill_order(order["id"], fill_price=live)
            filled_trade["fill_price"] = live
            filled.append(filled_trade)
        else:
            order["current_price"] = live
            still_pending.append(order)

    return jsonify({"filled": filled, "pending": still_pending})


@app.route("/api/trades/check-stops", methods=["POST"])
def trades_check_stops():
    """Auto-close OPEN trades when stop-loss is breached or target price is reached."""
    open_trades = db.get_open_trades()
    triggered = []
    unchanged = []
    skipped = []

    for trade in open_trades:
        stop_loss = trade.get("stop_loss")
        target = trade.get("target")

        if stop_loss is None and target is None:
            unchanged.append(trade)
            continue

        # Check if price data is fresh before using for critical operations
        if not _is_price_fresh(trade["ticker"]):
            app.logger.warning(f"Skipping stop-loss check for {trade['ticker']} — price data is stale")
            skipped.append({
                "trade_id": trade["id"],
                "reason": "stale_price",
                "ticker": trade["ticker"]
            })
            continue

        live = _current_price(trade["ticker"])
        if live is None:
            unchanged.append(trade)
            continue

        direction = (trade.get("direction") or "LONG").upper()

        hit_stop = stop_loss is not None and (
            (direction == "LONG" and live <= float(stop_loss)) or
            (direction == "SHORT" and live >= float(stop_loss))
        )
        hit_target = target is not None and (
            (direction == "LONG" and live >= float(target)) or
            (direction == "SHORT" and live <= float(target))
        )

        if not hit_stop and not hit_target:
            trade["current_price"] = live
            unchanged.append(trade)
            continue

        exit_reason = "TARGET" if hit_target else "STOP_LOSS"
        closed = db.close_trade(trade["id"], float(live))
        if closed and not closed.get("notes"):
            notes = _postmortem(closed)
            db.save_postmortem(trade["id"], notes)
            closed["notes"] = notes
        if closed:
            closed["exit_reason"] = exit_reason
            closed["trigger_price"] = live
            triggered.append(closed)

    return jsonify({"triggered": triggered, "unchanged": unchanged, "skipped": skipped})


@app.route("/api/orders/<int:order_id>/cancel", methods=["POST"])
def orders_cancel(order_id: int):
    order = db.get_trade(order_id)
    if not order:
        return jsonify({"error": "Order not found"}), 404
    if order.get("status") != "PENDING":
        return jsonify({"error": "Only PENDING orders can be cancelled"}), 400
    cancelled = db.cancel_order(order_id)
    return jsonify(cancelled)


@app.route("/api/trades/<int:trade_id>/close", methods=["POST"])
def trades_close(trade_id: int):
    data = request.get_json(force=True)
    exit_price  = data.get("exit_price")
    close_shares = data.get("close_shares")   # None = close all

    if exit_price is None:
        ticker = db.get_trade(trade_id).get("ticker")
        exit_price = _current_price(ticker) if ticker else None

    if exit_price is None:
        return jsonify({"error": "exit_price required"}), 400

    trade = db.close_trade(trade_id, float(exit_price),
                           close_shares=int(close_shares) if close_shares else None)
    if not trade:
        return jsonify({"error": "Trade not found"}), 404
    if trade.get("status") not in ("CLOSED", "OPEN"):
        # close_trade returned the trade unchanged — it was PENDING/CANCELLED, not OPEN
        return jsonify({"error": f"Cannot close trade in status '{trade.get('status')}'"}), 409

    # Only generate postmortem on full close (status=CLOSED).
    if trade.get("status") == "CLOSED" and not trade.get("notes"):
        notes = _postmortem(trade)
        db.save_postmortem(trade_id, notes)
        trade["notes"] = notes

    threading.Thread(target=db.hf_upload_db, daemon=True).start()
    return jsonify(trade)


@app.route("/api/trades/<int:trade_id>/price", methods=["GET"])
def trades_current_price(trade_id: int):
    trade = db.get_trade(trade_id)
    if not trade:
        return jsonify({"error": "Not found"}), 404
    price = _current_price(trade["ticker"])
    return jsonify({"ticker": trade["ticker"], "current_price": price})


# ── SECTOR PULSE ─────────────────────────────────────────────────────────────

@app.route("/api/sector-pulse")
def sector_pulse():
    """NSE sector heatmap — rotation signal, leading/lagging sectors, breadth."""
    try:
        from sector_pulse import get_sector_pulse
    except ImportError:
        return jsonify({"error": "sector_pulse module not available"}), 501

    force = request.args.get("refresh") == "1"
    result = get_sector_pulse(force_refresh=force)
    # Strip internal cache key before returning
    result.pop("_ts", None)
    return jsonify(result)


# ── FUNDAMENTALS ──────────────────────────────────────────────────────────────

@app.route("/api/fundamentals/<path:ticker>")
def fundamentals_ticker(ticker: str):
    """Fundamentals score + PE/debt/ROE breakdown for an NSE ticker."""
    try:
        from fundamentals import get_fundamentals
    except ImportError:
        return jsonify({"error": "fundamentals module not available"}), 501

    t = _normalise(ticker)
    force = request.args.get("refresh") == "1"
    result = get_fundamentals(t, force_refresh=force)
    return jsonify(result)


# ── PORTFOLIO ─────────────────────────────────────────────────────────────────

@app.route("/api/portfolio")
def portfolio():
    summary = db.get_portfolio_summary()
    # Enrich with risk metrics from risk_engine.py
    try:
        from risk_engine import get_portfolio_risk
        risk = get_portfolio_risk()
        summary["risk_metrics"] = risk
    except Exception:
        summary["risk_metrics"] = None
    return _json_no_store(summary)


@app.route("/api/equity-curve")
def equity_curve():
    """Return the equity curve (running portfolio value starting at 100) from closed trades."""
    try:
        from risk_engine import get_portfolio_risk
        data = get_portfolio_risk(include_curve=True)
        curve = data.get("equity_curve") or []
        return _json_no_store({"equity_curve": curve, "trade_count": data.get("trade_count", 0)})
    except Exception as e:
        return _json_no_store({"equity_curve": [], "error": str(e)}), 500


@app.route("/api/portfolio-review")
def portfolio_review():
    """Batch AI review of last N closed trades — surfaces systematic patterns and biases."""
    from datetime import datetime as _dt
    n = request.args.get("n", 20, type=int)
    n = max(5, min(n, 100))

    trades = db.get_trade_history()
    closed = [t for t in trades if t.get("pnl_pct") is not None][-n:]
    if len(closed) < 3:
        return _json_no_store({"error": "Need at least 3 closed trades for a meaningful review", "trade_count": len(closed)})

    lines = []
    for t in closed:
        outcome = "WIN" if (_safe_float(t.get("pnl_pct")) or 0) >= 0 else "LOSS"
        lines.append(
            f"- {t.get('ticker','?')} | {t.get('direction','?')} | "
            f"Entry ₹{(_safe_float(t.get('entry_price')) or 0):.0f} → Exit ₹{(_safe_float(t.get('exit_price') or t.get('current_price')) or 0):.0f} | "
            f"P&L {(_safe_float(t.get('pnl_pct')) or 0):+.2f}% | {outcome}"
        )
    trade_list = "\n".join(lines)

    prompt = (
        f"You are a senior trading coach reviewing {len(closed)} recent paper trades on NSE Indian equities.\n\n"
        f"TRADES:\n{trade_list}\n\n"
        "Analyze these trades holistically and provide:\n"
        "1. SYSTEMATIC BIASES: any patterns in what types of trades consistently win or lose\n"
        "2. SECTOR / TIMING PATTERNS: any sector or time-based tendencies\n"
        "3. SIZING / RISK MISTAKES: any position sizing or stop-loss issues visible\n"
        "4. ONE CONCRETE PROCESS FIX: the single most impactful change to improve outcomes\n\n"
        "Be specific — name tickers and P&L figures. Keep total response under 300 words."
    )

    review_text = None
    try:
        from ai_forecast import _make_chat_call
        content, provider, model = _make_chat_call(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
            temperature=0.4,
        )
        review_text = content.strip()
    except Exception as e:
        review_text = f"AI review unavailable: {e}"

    return _json_no_store({
        "review_text": review_text,
        "trade_count": len(closed),
        "generated_at": _dt.now().strftime("%Y-%m-%d %H:%M"),
    })


# _safe_float defined above (line ~387) — this duplicate removed.




# ── POST-MORTEMS ──────────────────────────────────────────────────────────────

@app.route("/api/prediction-snapshots")
def prediction_snapshots():
    """Retrieve prediction snapshots for audit trail (recent predictions)."""
    ticker = request.args.get("ticker")
    days = request.args.get("days", "30", type=int)
    limit = request.args.get("limit", "100", type=int)
    return _json_no_store({"snapshots": db.get_prediction_snapshots(ticker=ticker, days=days, limit=limit)})


@app.route("/api/prediction-validation")
def prediction_validation():
    """Validate top5 predictions: check if price stayed within predicted range at timeframe expiry.
    
    Returns predictions with actual outcome and whether they hit their targets.
    Expired timeframes are validated (1D next day, 3D in 3 days, 5D in 5 days).
    """
    from datetime import datetime, timedelta, timezone
    
    # Get all predictions from last 7 days
    snapshots = db.get_prediction_snapshots(ticker=None, days=7, limit=500)
    
    if not snapshots:
        return _json_no_store({"validation": [], "summary": {}})
    
    validation_results = []
    
    # Timeframe expiry offsets (days to wait before checking). INTRADAY = same-day.
    tf_offset = {"INTRADAY": 0, "1D": 1, "3D": 3, "5D": 5}
    
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc.astimezone(timezone(timedelta(hours=5, minutes=30)))
    
    for snap in snapshots:
        try:
            ticker = snap.get("ticker")
            timeframe = snap.get("timeframe")
            created_at_str = snap.get("created_at")
            
            # Parse creation timestamp
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            created_at_ist = created_at.astimezone(timezone(timedelta(hours=5, minutes=30)))
            
            # Check if timeframe has expired
            days_elapsed = (now_ist - created_at_ist).days
            tf_days = tf_offset.get(timeframe, 1)
            
            status = "PENDING"
            target_hit = None
            hit_grade = None
            point_reached = None
            hit_note = None
            actual_price = None
            actual_return = None
            window_high = None
            window_low = None
            direction = snap.get("direction", "NEUTRAL")

            # Skip NO TRADE / N/A predictions — not meaningful to validate
            if (direction or "").upper() in ("NO TRADE", "N/A"):
                continue

            # INTRADAY: same-day, 3pm-capped window; only ready after the 15:00 cutoff.
            if (timeframe or "").upper() == "INTRADAY":
                pred_date_str = created_at_ist.strftime("%Y-%m-%d")
                if _intraday_cutoff_passed(pred_date_str):
                    status = "EXPIRED"
                    target_date_str = pred_date_str
                    try:
                        window_high, window_low, actual_price = _fetch_intraday_window_capped(
                            ticker, pred_date_str
                        )
                        entry_price = snap.get("current_price", 0)
                        if entry_price > 0 and actual_price:
                            actual_return = round((actual_price - entry_price) / entry_price * 100, 2)
                        target_price_lo = snap.get("target_price_lo") or 0
                        target_price_hi = snap.get("target_price_hi") or 0
                        ev = _evaluate_price_hit(
                            direction, window_high, window_low, actual_price,
                            target_price_lo, target_price_hi, entry_price,
                        )
                        if ev is not None:
                            target_hit = ev["hit"]
                            hit_grade = ev["grade"]
                            point_reached = ev["point_reached"]
                            hit_note = ev["note"]
                            status = "VALIDATED"
                    except Exception as e:
                        logging.warning(f"Failed intraday validation for {ticker}: {e}")
            elif days_elapsed >= tf_days:
                status = "EXPIRED"
                target_date_str = (created_at_ist + timedelta(days=tf_days)).strftime("%Y-%m-%d")
                # Window starts the day after the prediction was made
                window_start_str = (created_at_ist + timedelta(days=1)).strftime("%Y-%m-%d")
                try:
                    window_high, window_low, actual_price = _fetch_price_window(
                        ticker, window_start_str, target_date_str
                    )
                    entry_price = snap.get("current_price", 0)
                    if entry_price > 0 and actual_price:
                        raw_return = (actual_price - entry_price) / entry_price * 100
                        # For BEARISH predictions sign-flip so positive = stock fell as predicted.
                        actual_return = round(-raw_return if direction == "BEARISH" else raw_return, 2)
                    target_price_lo = snap.get("target_price_lo") or 0
                    target_price_hi = snap.get("target_price_hi") or 0
                    ev = _evaluate_price_hit(
                        direction, window_high, window_low, actual_price,
                        target_price_lo, target_price_hi, entry_price,
                    )
                    if ev is not None:
                        target_hit = ev["hit"]
                        hit_grade = ev["grade"]
                        point_reached = ev["point_reached"]
                        hit_note = ev["note"]
                        status = "VALIDATED"
                except Exception as e:
                    logging.warning(f"Failed to fetch price for {ticker} validation: {e}")

            validation_results.append({
                "ticker": ticker,
                "prediction_date": created_at_ist.strftime("%Y-%m-%d"),
                "timeframe": timeframe,
                "direction": direction,
                "confidence": snap.get("confidence"),
                "predicted_return_lo": snap.get("predicted_return_lo"),
                "predicted_return_hi": snap.get("predicted_return_hi"),
                "target_price_lo": snap.get("target_price_lo"),
                "target_price_hi": snap.get("target_price_hi"),
                "entry_price": snap.get("current_price"),
                "window_high": window_high,
                "window_low": window_low,
                "actual_price": actual_price,
                "actual_return": actual_return,
                "target_hit": target_hit,
                "hit_grade": hit_grade,
                "point_reached": point_reached,
                "note": hit_note,
                "status": status,
                "days_elapsed": days_elapsed,
            })
        except Exception as e:
            logging.warning(f"Error validating snapshot {snap.get('id')}: {e}")
    
    # Compute summary statistics by timeframe
    summary = {}
    for tf in ["INTRADAY", "1D", "3D", "5D"]:
        validated = [v for v in validation_results if v["timeframe"] == tf and v["status"] == "VALIDATED"]
        if validated:
            hits = sum(1 for v in validated if v["target_hit"])
            summary[tf] = {
                "total": len(validated),
                "hits": hits,
                "hit_rate": round(hits / len(validated), 2) if validated else 0,
            }
    
    return _json_no_store({"validation": validation_results, "summary": summary})


@app.route("/api/validation/pending")
def validation_pending():
    """Get all stocks with pending predictions for the Validation tab."""
    pending = db.get_validation_pending(limit=300, due_only=False)
    due_count = db.get_validation_pending_count(due_only=True)
    return _json_no_store({"pending": pending, "due_count": due_count, "total_count": len(pending)})


def _fetch_price_at_date(ticker: str, target_date_str: str):
    """Return EOD close price on or after target_date_str using historical OHLCV.
    Falls back to live price if OHLCV fails or target_date_str is None.
    """
    if not target_date_str:
        return fetch_live_price(ticker, allow_delayed=True)
    try:
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        target = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        days_back = max((today - target).days + 10, 10)
        if days_back <= 30:
            period = "1mo"
        elif days_back <= 90:
            period = "3mo"
        elif days_back <= 180:
            period = "6mo"
        else:
            period = "1y"
        sc, _, _, _ = fetch_ohlcv(ticker, period=period)
        close = sc[ticker]
        idx_dates = [str(ts)[:10] for ts in close.index]
        future = [(d, v) for d, v in zip(idx_dates, close.values) if d >= target_date_str and v == v]
        if future:
            return float(future[0][1])
        valid = [(d, v) for d, v in zip(idx_dates, close.values) if v == v]
        return float(valid[-1][1]) if valid else None
    except Exception as e:
        logging.warning(f"_fetch_price_at_date({ticker}, {target_date_str}): {e}")
        return fetch_live_price(ticker, allow_delayed=True)


def _fetch_price_window(ticker: str, start_date_str: str, end_date_str: str):
    """Return (window_high, window_low, close_on_end) using intraday High/Low over [start, end].

    window_high = max intraday High across all trading days in the window
    window_low  = min intraday Low across all trading days in the window
    close_on_end = closing price on the end date (or last available)
    Returns (None, None, None) on failure.
    """
    if not start_date_str or not end_date_str:
        return None, None, None
    try:
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        end = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        days_back = max((today - end).days + 15, 15)
        if days_back <= 30:
            period = "1mo"
        elif days_back <= 90:
            period = "3mo"
        else:
            period = "6mo"

        sc, sh, sl, _ = fetch_ohlcv(ticker, period=period)
        if ticker not in sc.columns:
            return None, None, None

        idx_dates = [str(ts)[:10] for ts in sc.index]
        rows = [
            (d, float(h), float(l), float(c))
            for d, h, l, c in zip(idx_dates, sh[ticker].values, sl[ticker].values, sc[ticker].values)
            if start_date_str <= d <= end_date_str and h == h and l == l and c == c
        ]

        if not rows:
            # No data in window — fall back to first available date on/after end
            fallback = [
                (d, float(h), float(l), float(c))
                for d, h, l, c in zip(idx_dates, sh[ticker].values, sl[ticker].values, sc[ticker].values)
                if d >= end_date_str and h == h and l == l and c == c
            ]
            if fallback:
                d, h, l, c = fallback[0]
                return h, l, c
            return None, None, None

        window_high = max(r[1] for r in rows)
        window_low  = min(r[2] for r in rows)
        end_closes  = [c for d, _, _, c in rows if d >= end_date_str]
        close_on_end = end_closes[0] if end_closes else rows[-1][3]

        return window_high, window_low, close_on_end

    except Exception as e:
        logging.warning(f"_fetch_price_window({ticker}, {start_date_str}, {end_date_str}): {e}")
        return None, None, None


def _fetch_intraday_window_capped(ticker: str, date_str: str,
                                   cutoff_hour: int = 15, cutoff_minute: int = 0):
    """Return (window_high, window_low, last_close) for the INTRADAY horizon.

    Uses 15m intraday bars (yfinance, ~60-day history) for `date_str`, capped at
    bars whose START time is strictly before the cutoff (15:00 IST) — so a hit only
    counts if the target was touched by ~3pm on the same day (no next-day rollover).
    Returns (None, None, None) if bars are unavailable (leaves the snapshot PENDING).
    """
    try:
        from intraday_live import get_intraday_bars
        bars = get_intraday_bars(ticker, interval="15m", period="5d")
        if bars is None or bars.empty:
            return None, None, None
        ist = timezone(timedelta(hours=5, minutes=30))
        idx = bars.index
        local = idx.tz_convert(ist) if idx.tz is not None else idx.tz_localize("UTC").tz_convert(ist)
        keep = [
            (ts.strftime("%Y-%m-%d") == date_str) and ((ts.hour, ts.minute) < (cutoff_hour, cutoff_minute))
            for ts in local
        ]
        sub = bars[keep]
        if sub.empty:
            return None, None, None
        return (
            round(float(sub["High"].max()), 2),
            round(float(sub["Low"].min()), 2),
            round(float(sub["Close"].iloc[-1]), 2),
        )
    except Exception as e:
        logging.warning(f"_fetch_intraday_window_capped({ticker}, {date_str}): {e}")
        return None, None, None


def _intraday_cutoff_passed(target_date_str: str) -> bool:
    """True if the INTRADAY 3pm cutoff has passed for `target_date_str`.

    Same-day predictions can only be validated after 15:00 IST (window complete);
    for any past date the cutoff is trivially passed.
    """
    ist = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(timezone.utc).astimezone(ist)
    today_str = now_ist.strftime("%Y-%m-%d")
    if target_date_str < today_str:
        return True
    if target_date_str > today_str:
        return False
    return (now_ist.hour, now_ist.minute) >= (15, 0)


def _fetch_intraday_window(ticker: str, date_str: str):
    """INTRADAY validation window with a daily-OHLC fallback for past dates.

    Primary source is 15m intraday bars capped at 15:00 IST.  yfinance only serves
    ~60 days of 15m bars and is flaky for even 1–2 day-old dates, so a backdated
    INTRADAY snapshot would otherwise return no price and stay PENDING forever.
    For any date strictly before today we fall back to that day's daily High/Low/
    Close — the same same-session proxy the backtest uses (_fwd_intraday_moves).
    Returns (window_high, window_low, actual_price); prices may be None.
    """
    wh, wl, ap = _fetch_intraday_window_capped(ticker, date_str)
    if ap is not None:
        return wh, wl, ap
    ist = timezone(timedelta(hours=5, minutes=30))
    today_str = datetime.now(timezone.utc).astimezone(ist).strftime("%Y-%m-%d")
    if date_str and date_str < today_str:
        return _fetch_price_window(ticker, date_str, date_str)
    return wh, wl, ap


def _evaluate_price_hit(direction: str, window_high, window_low, close_price,
                        target_price_lo, target_price_hi, entry_price):
    """Graded price-prediction check against the day's actual price range.

    Price prediction takes priority (per product spec): we first ask whether the
    predicted MIDPOINT was reached during the window; if not, we check whether the
    price entered the predicted RANGE at all, and report the exact point it reached.

    Returns a dict (or None to skip):
      grade:         "MIDPOINT_HIT" | "RANGE_HIT" | "MISS"
      hit:           bool  — True for MIDPOINT_HIT or RANGE_HIT
      midpoint:      float — (lo + hi) / 2
      point_reached: float — the extreme price the stock reached toward the target
                             (window_high for bullish, window_low for bearish, close for neutral)
      progress_pct:  float — how far entry→midpoint the move got (1.0 = midpoint reached)
      note:          human-readable summary of which point was there

    Direction-aware binding extreme:
    - BULLISH: window_high (stock must RISE into the range)
    - BEARISH: window_low  (stock must FALL into the range)
    - NEUTRAL: close_price stayed inside [lo, hi] (flat as predicted)
    """
    direction = (direction or "").upper()
    if direction in ("NO TRADE", "N/A", ""):
        return None
    if not entry_price or entry_price <= 0:
        return None
    if not target_price_lo and not target_price_hi:
        return None
    if target_price_lo == target_price_hi:  # zero-width = NO TRADE under another label
        return None
    if window_high is None or window_low is None:
        return None

    # Consistency guard: a real price window MUST bracket the entry price (the stock
    # moved from entry into the window). If the entry price is grossly outside the
    # window, the window belongs to a different ticker (yfinance thread-safety
    # contamination) — skip grading so it stays PENDING and re-validates cleanly
    # rather than recording a false MISS.
    if not (float(window_low) * 0.75 <= float(entry_price) <= float(window_high) * 1.25):
        return None

    lo, hi = float(target_price_lo), float(target_price_hi)
    midpoint = round((lo + hi) / 2, 2)
    is_bull = direction in ("BULLISH", "SLIGHTLY BULLISH")
    is_bear = direction in ("BEARISH", "SLIGHTLY BEARISH")

    if is_bull:
        reached = float(window_high)                       # best upward point
        midpoint_hit = reached >= midpoint
        range_hit    = reached >= lo
        denom = (midpoint - entry_price) or 1e-9
        progress = (reached - entry_price) / denom
    elif is_bear:
        reached = float(window_low)                        # best downward point
        midpoint_hit = reached <= midpoint
        range_hit    = reached <= hi
        denom = (entry_price - midpoint) or 1e-9
        progress = (entry_price - reached) / denom
    else:  # NEUTRAL — correct if it ended inside the predicted flat band
        reached = float(close_price) if close_price else float(window_high)
        midpoint_hit = lo <= reached <= hi
        range_hit    = (float(window_high) >= lo) and (float(window_low) <= hi)
        progress = 1.0 if midpoint_hit else 0.0

    grade = "MIDPOINT_HIT" if midpoint_hit else ("RANGE_HIT" if range_hit else "MISS")
    if grade == "MIDPOINT_HIT":
        note = f"midpoint ₹{midpoint} reached (touched ₹{round(reached, 2)})"
    elif grade == "RANGE_HIT":
        note = f"entered range ₹{round(lo, 2)}–₹{round(hi, 2)} at ₹{round(reached, 2)} (below midpoint ₹{midpoint})"
    else:
        note = f"missed range ₹{round(lo, 2)}–₹{round(hi, 2)} — best was ₹{round(reached, 2)}"

    return {
        "grade": grade,
        "hit": grade in ("MIDPOINT_HIT", "RANGE_HIT"),
        "midpoint": midpoint,
        "point_reached": round(reached, 2),
        "progress_pct": round(max(-1.0, min(2.0, progress)) * 100, 1),
        "note": note,
    }


def _intraday_target_hit(direction: str, window_high, window_low, close_price,
                          target_price_lo, target_price_hi, entry_price):
    """Backward-compatible boolean wrapper around _evaluate_price_hit.

    Returns True (price reached midpoint or entered range), False (missed), or
    None (skip / not validatable). Callers that need the grade + reached point
    should call _evaluate_price_hit directly.
    """
    res = _evaluate_price_hit(direction, window_high, window_low, close_price,
                              target_price_lo, target_price_hi, entry_price)
    return None if res is None else res["hit"]


@app.route("/api/validation/execute", methods=["POST"])
def validation_execute():
    """Execute validation for pending predictions — parallel OHLCV fetches to avoid timeouts."""
    _IST = timezone(timedelta(hours=5, minutes=30))
    today_ist = datetime.now(timezone.utc).astimezone(_IST).date()
    today_str = today_ist.isoformat()
    is_trading_today = nse_is_trading_day(today_ist)

    pending = db.get_validation_pending(limit=500, due_only=True)

    # On holidays/weekends: only block items targeting today (live price unavailable).
    # Backdated items always proceed — their historical OHLCV is fully available.
    if not is_trading_today:
        backdated = [s for s in pending if (s.get("validation_target_date") or "") < today_str]
        if not backdated:
            next_td = nse_next_trading_day(today_ist).isoformat()
            return _json_no_store({
                "deferred": True,
                "reason": "today_is_holiday",
                "message": f"NSE is closed today. {len(pending)} prediction(s) targeting today will be validated on {next_td}.",
                "next_trading_day": next_td,
                "pending_count": len(pending),
            })
        pending = backdated  # today-targeted items wait; backdated ones proceed

    # Pre-filter: handle NO TRADE / bad entry immediately (no I/O needed)
    actionable = []
    for snap in pending:
        direction = (snap.get("direction") or "").upper()
        entry_price = snap.get("current_price", 0)
        if direction in ("NO TRADE", "N/A"):
            db.mark_prediction_skipped(snap.get("id"))
            continue
        if entry_price <= 0:
            continue
        timeframe = (snap.get("timeframe") or "").upper()
        if timeframe == "INTRADAY" and not _intraday_cutoff_passed(snap.get("validation_target_date")):
            continue
        actionable.append(snap)

    def _fetch_window(snap):
        """Return (snap, window_high, window_low, actual_price) — None prices on failure."""
        timeframe = (snap.get("timeframe") or "").upper()
        target_date_str = snap.get("validation_target_date")
        try:
            if timeframe == "INTRADAY":
                wh, wl, ap = _fetch_intraday_window(snap["ticker"], target_date_str)
            else:
                created_at_str = (snap.get("created_at") or "")[:10]
                try:
                    ws = (datetime.strptime(created_at_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
                except ValueError:
                    ws = target_date_str
                wh, wl, ap = _fetch_price_window(snap["ticker"], ws, target_date_str)
                # Fallback: for today's target date, all 6 daily OHLCV sources may only
                # carry yesterday's close (today's bar is published hours after session
                # end, sometimes not until next morning).  Try intraday 15m bars first
                # (yfinance — only source for sub-daily NSE data), then fall back to
                # fetch_live_price which has its own NSE→BSE→jugaad→Yahoo chain.
                if ap is None and target_date_str == today_str:
                    wh, wl, ap = _fetch_intraday_window_capped(
                        snap["ticker"], target_date_str,
                        cutoff_hour=15, cutoff_minute=30,
                    )
                    if ap is None:
                        from data_sources import fetch_live_price
                        live = fetch_live_price(snap["ticker"], allow_delayed=True)
                        if live and live > 0:
                            ap = live
                            wh = wh if wh is not None else live
                            wl = wl if wl is not None else live
            return snap, wh, wl, ap
        except Exception as e:
            logging.warning(f"_fetch_window({snap.get('ticker')}): {e}")
            return snap, None, None, None

    # Parallel fetch — up to 10 concurrent OHLCV calls (~10× faster than sequential)
    validated_count = 0
    expired_count = 0
    results = []
    max_workers = min(len(actionable), 10) if actionable else 1
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for snap, window_high, window_low, actual_price in pool.map(_fetch_window, actionable):
            try:
                snapshot_id = snap.get("id")
                ticker = snap.get("ticker")
                entry_price = snap.get("current_price", 0)
                direction = (snap.get("direction") or "NEUTRAL").upper()

                if not actual_price:
                    target_date_str = snap.get("validation_target_date") or ""
                    try:
                        days_overdue = (today_ist - date.fromisoformat(target_date_str)).days
                    except ValueError:
                        days_overdue = 0
                    if days_overdue > _STALE_PENDING_GIVEUP_DAYS:
                        db.mark_prediction_expired(snapshot_id)
                        expired_count += 1
                        app.logger.warning(
                            "Expiring stale PENDING validation #%s %s (target %s, %d days "
                            "overdue, price still unfetchable)",
                            snapshot_id, ticker, target_date_str, days_overdue,
                        )
                    continue

                actual_return = round((actual_price - entry_price) / entry_price * 100, 2)
                target_price_lo = snap.get("target_price_lo") or 0
                target_price_hi = snap.get("target_price_hi") or 0

                ev = _evaluate_price_hit(
                    direction, window_high, window_low, actual_price,
                    target_price_lo, target_price_hi, entry_price,
                )
                if ev is None:
                    db.mark_prediction_skipped(snapshot_id)
                    continue

                db.validate_prediction(
                    snapshot_id=snapshot_id,
                    actual_price=actual_price,
                    actual_return=actual_return,
                    target_hit=ev["hit"],
                    window_high=window_high,
                    window_low=window_low,
                    hit_grade=ev["grade"],
                    point_reached=ev["point_reached"],
                )
                results.append({
                    "ticker": ticker,
                    "timeframe": snap.get("timeframe"),
                    "direction": direction,
                    "window_high": window_high,
                    "window_low": window_low,
                    "actual_price": actual_price,
                    "actual_return": actual_return,
                    "target_price_lo": target_price_lo,
                    "target_price_hi": target_price_hi,
                    "target_hit": ev["hit"],
                    "hit_grade": ev["grade"],
                    "midpoint": ev["midpoint"],
                    "point_reached": ev["point_reached"],
                    "note": ev["note"],
                })
                validated_count += 1
            except Exception as e:
                logging.warning(f"Error validating snapshot {snap.get('id')}: {e}")

    # Auto-update self-learning after validations complete, then prune validated rows.
    # Only prune if learnings.json was successfully written with valid data so the
    # history tab can fall back to the records stored there.
    if validated_count > 0:
        try:
            from self_learning import analyze_and_update
            learn_result = analyze_and_update()  # all history
            if learn_result.get("status") != "insufficient_data":
                pruned = db.prune_validated_snapshots()
                if pruned:
                    app.logger.info("Pruned %d validated snapshots after self-learning update", pruned)
        except Exception as _le:
            app.logger.warning("Self-learning update failed: %s", _le)

    hits   = sum(1 for r in results if r.get("target_hit"))
    misses = sum(1 for r in results if not r.get("target_hit"))
    return _json_no_store({
        "validated": validated_count,
        "hits": hits,
        "misses": misses,
        "expired": expired_count,
        "results": results,
    })


@app.route("/api/ai-learn", methods=["POST"])
def ai_learn():
    """Manually trigger self-learning analysis from validation history."""
    try:
        from self_learning import analyze_and_update
        # Default: analyze the ENTIRE validated history (days=None). A positive `days`
        # override still restricts the window when explicitly requested.
        _body = request.get_json(silent=True) or {}
        _days_req = _body.get("days")
        days = int(_days_req) if _days_req and int(_days_req) > 0 else None
        # Manual "Improve AI" click forces an immediate LLM refresh (bypass the throttle).
        force_llm = bool(_body.get("force", True))
        result = analyze_and_update(days=days, force_llm=force_llm)
        pruned = 0
        if result.get("status") != "insufficient_data":
            pruned = db.prune_validated_snapshots()
        result["pruned"] = pruned
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/learnings")
def get_learnings():
    """Serve the current learnings.json for the UI to pre-populate the Validation panel."""
    import self_learning
    data = self_learning._read()
    if data is None:
        return jsonify({"status": "no_data"})
    return jsonify(data)


@app.route("/api/validation/summary")
def validation_summary():
    """Get validation success rates by timeframe."""
    summary = db.get_validation_summary()
    history = db.get_validation_history(limit=200)

    # Always merge DB records with JSON records (pruned records live in learnings.json).
    # DB records are authoritative for rows that still exist; JSON fills the rest.
    try:
        import self_learning
        ldata = self_learning._read() or {}
        json_records = ldata.get("records", [])
        if json_records:
            db_ids = {r["id"] for r in history}
            combined = list(history) + [r for r in json_records if r.get("id") not in db_ids]
            combined.sort(key=lambda x: x.get("validated_at") or "", reverse=True)
            history = combined[:200]

            # Accumulate pruned learnings.json records into summary buckets so
            # stat cards reflect full history, not just the 14-day SQLite window.
            _SKIP_DIRS = {"NO TRADE", "N/A", "", "SKIPPED"}
            for rec in json_records:
                if rec.get("id") in db_ids:
                    continue  # still in DB; already counted by get_validation_summary()
                tf = rec.get("timeframe")
                direction = (rec.get("direction") or "").upper()
                result = rec.get("validation_result")
                if not tf or result not in ("HIT", "MISS") or direction in _SKIP_DIRS:
                    continue
                for bucket in ("all",):
                    bkt = summary.setdefault(bucket, {})
                    s = bkt.setdefault(tf, {"hits": 0, "misses": 0, "total": 0, "hit_rate_pct": 0.0})
                    s["total"] += 1
                    if result == "HIT":
                        s["hits"] += 1
                    else:
                        s["misses"] += 1
                _is_directional = direction in ("BULLISH", "BEARISH", "SLIGHTLY BULLISH", "SLIGHTLY BEARISH")
                if _is_directional:
                    bkt = summary.setdefault("directional", {})
                    s = bkt.setdefault(tf, {"hits": 0, "misses": 0, "total": 0, "hit_rate_pct": 0.0})
                    s["total"] += 1
                    if result == "HIT":
                        s["hits"] += 1
                    else:
                        s["misses"] += 1
                # HIGH-confidence bucket (the 95-97% profit bucket surfaced on the UI)
                if _is_directional and (rec.get("confidence") or "").upper() == "HIGH":
                    bkt = summary.setdefault("high_conf", {})
                    s = bkt.setdefault(tf, {"hits": 0, "misses": 0, "total": 0, "hit_rate_pct": 0.0})
                    s["total"] += 1
                    if result == "HIT":
                        s["hits"] += 1
                    else:
                        s["misses"] += 1

            # Recompute hit_rate_pct for every bucket after merge
            for bucket in ("all", "directional", "high_conf"):
                for s in summary.get(bucket, {}).values():
                    t = s["total"]
                    s["hit_rate_pct"] = round(s["hits"] / t * 100, 1) if t > 0 else 0.0
    except Exception:
        pass

    return _json_no_store({"summary": summary, "history": history})


@app.route("/api/validation/revalidate-all", methods=["POST"])
def validation_revalidate_all():
    """Re-run validation for all previously validated snapshots using correct historical prices.
    Covers both DB rows and JSON-only records (rows pruned from DB but preserved in learnings.json).
    """
    db_history = db.get_validation_history(limit=9999)

    # Pull JSON-only records (ids not in DB) so pruned rows can also be revalidated.
    json_only_records = []
    try:
        import self_learning as _sl
        ldata = _sl._read() or {}
        db_ids = {r["id"] for r in db_history}
        json_only_records = [r for r in ldata.get("records", []) if r.get("id") not in db_ids]
    except Exception:
        pass

    revalidated = 0
    results = []
    updated_json_records = {}  # id -> updated record (for JSON-only rows)

    def _revalidate_snap(snap, is_json_only=False):
        nonlocal revalidated
        snapshot_id = snap.get("id")
        ticker = snap.get("ticker")
        entry_price = snap.get("current_price", 0)
        direction = snap.get("direction", "NEUTRAL")
        target_date_str = snap.get("validation_target_date")

        if (direction or "").upper() in ("NO TRADE", "N/A"):
            if not is_json_only:
                db.mark_prediction_skipped(snapshot_id)
            return
        if not entry_price or entry_price <= 0:
            return

        created_at_str = (snap.get("created_at") or "")[:10]
        try:
            window_start_str = (
                datetime.strptime(created_at_str, "%Y-%m-%d") + timedelta(days=1)
            ).strftime("%Y-%m-%d")
        except ValueError:
            window_start_str = target_date_str

        timeframe = snap.get("timeframe", "")
        if timeframe == "INTRADAY":
            window_high, window_low, actual_price = _fetch_intraday_window_capped(
                ticker, target_date_str
            )
        else:
            window_high, window_low, actual_price = _fetch_price_window(
                ticker, window_start_str, target_date_str
            )
        if not actual_price:
            return

        actual_return = round((actual_price - entry_price) / entry_price * 100, 2)
        target_price_lo = snap.get("target_price_lo") or 0
        target_price_hi = snap.get("target_price_hi") or 0

        hit = _intraday_target_hit(
            direction, window_high, window_low, actual_price,
            target_price_lo, target_price_hi, entry_price,
        )
        if hit is None:
            return

        validation_result = "HIT" if hit else "MISS"
        from datetime import timezone
        validated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        if is_json_only:
            # Can't update DB row (pruned); update the in-memory record for learnings.json.
            updated = dict(snap)
            updated.update({
                "actual_price_at_validation": actual_price,
                "actual_return_at_validation": actual_return,
                "window_high": window_high,
                "window_low": window_low,
                "validation_result": validation_result,
                "validated_at": validated_at,
            })
            updated_json_records[snapshot_id] = updated
        else:
            db.validate_prediction(
                snapshot_id=snapshot_id,
                actual_price=actual_price,
                actual_return=actual_return,
                target_hit=hit,
                window_high=window_high,
                window_low=window_low,
            )

        results.append({
            "ticker": ticker,
            "timeframe": snap.get("timeframe"),
            "direction": direction,
            "window_high": window_high,
            "window_low": window_low,
            "actual_return": actual_return,
            "target_hit": hit,
            "source": "json" if is_json_only else "db",
        })
        revalidated += 1

    for snap in db_history:
        try:
            _revalidate_snap(snap, is_json_only=False)
        except Exception as e:
            logging.warning(f"revalidate-all DB error for snapshot {snap.get('id')}: {e}")

    for snap in json_only_records:
        try:
            _revalidate_snap(snap, is_json_only=True)
        except Exception as e:
            logging.warning(f"revalidate-all JSON error for snapshot {snap.get('id')}: {e}")

    # Write updated JSON records back to learnings.json.
    if updated_json_records:
        try:
            import self_learning as _sl
            ldata = _sl._read() or {}
            existing = ldata.get("records", [])
            merged = [updated_json_records.get(r["id"], r) if r.get("id") in updated_json_records else r
                      for r in existing]
            merged.sort(key=lambda x: x.get("validated_at") or "", reverse=True)
            ldata["records"] = merged[:500]
            _sl._write(ldata)
        except Exception as e:
            logging.warning(f"revalidate-all: failed to write JSON records: {e}")

    return _json_no_store({"revalidated": revalidated, "results": results})


@app.route("/api/validation/recalibrate", methods=["POST"])
def validation_recalibrate():
    """Retroactively apply calibrated target ranges to all snapshots and re-evaluate hit/miss."""
    result = db.recalibrate_all_snapshots()
    return _json_no_store(result)


@app.route("/api/prediction-misses")
def prediction_misses():
    """Retrieve predictions where actual price exceeded predicted targets."""
    days = request.args.get("days", "30", type=int)
    min_confidence = request.args.get("confidence", "MEDIUM")
    return jsonify({"misses": db.get_prediction_misses(days=days, min_confidence=min_confidence)})


@app.route("/api/prediction-loopholes", methods=["POST"])
def check_prediction_loopholes():
    """Audit a prediction dict for loopholes: conflicting signals, news mismatch, weak conviction."""
    try:
        pred = request.get_json(force=True)
        if not pred:
            return jsonify({"error": "Prediction dict required"}), 400
        audit = _audit_prediction(pred)
        return jsonify(audit)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/specialist-stocks")
def specialist_stocks():
    """
    Identify stocks that are specialists for Intraday vs 1D trading.
    Returns: {
      "specialists": {
        "INTRADAY": [{ticker, company, win_rate, accuracy, recommended_tf, ...}],
        "1D": [...]
      },
      "recommendation_map": {ticker: {best_tf, best_tf_accuracy, reason}}
    }
    """
    try:
        min_samples = request.args.get("min_samples", "15", type=int)
        sort_by = request.args.get("sort", "intraday")  # "intraday" or "1d"

        result = _analyze_specialist_performance(min_samples=min_samples)

        # Sort lists by win_rate
        for tf_list in result.get("specialists", {}).values():
            tf_list.sort(key=lambda x: x.get("win_rate", 0), reverse=True)

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/specialist-stocks/<ticker>")
def specialist_stock_detail(ticker: str):
    """Get specialist recommendation for a single stock."""
    try:
        t = _normalise(ticker)
        result = _analyze_specialist_performance(min_samples=1)
        recommendation = result.get("recommendation_map", {}).get(t)

        if not recommendation:
            return jsonify({"ticker": t, "recommendation": None, "note": "Insufficient data for specialist classification"}), 200

        return jsonify({
            "ticker": t,
            "recommendation": recommendation,
            "company": TICKER_NAMES.get(t, t.replace(".NS", ""))
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── MAIN ──────────────────────────────────────────────────────────────────────

def _prewarm_top5():
    """Pre-warm the top5 cache in a background thread at startup.
    Delayed 10 minutes so user-initiated watchlist picks (which need Ollama too)
    get priority when all cloud providers are rate-limited.
    """
    import threading, time as _time
    def _run():
        _time.sleep(600)  # wait 10 min before background top5 compute
        _start_top5_background()
    threading.Thread(target=_run, daemon=True, name="top5-prewarm").start()


def _start_trade_monitor():
    """Background thread: check stop-losses, targets, and pending orders every 5 minutes."""
    import threading, time as _time

    CHECK_INTERVAL = 300  # seconds

    def _run():
        _time.sleep(10)  # let Flask finish binding the port first
        while True:
            try:
                # Reuse the same logic as the API endpoints, directly calling the DB + price layer.
                open_trades = db.get_open_trades()
                for trade in open_trades:
                    stop_loss = trade.get("stop_loss")
                    target = trade.get("target")
                    if stop_loss is None and target is None:
                        continue
                    live = _current_price(trade["ticker"])
                    if live is None:
                        continue
                    direction = (trade.get("direction") or "LONG").upper()
                    hit_stop = stop_loss is not None and (
                        (direction == "LONG" and live <= float(stop_loss)) or
                        (direction == "SHORT" and live >= float(stop_loss))
                    )
                    hit_target = target is not None and (
                        (direction == "LONG" and live >= float(target)) or
                        (direction == "SHORT" and live <= float(target))
                    )
                    if hit_stop or hit_target:
                        exit_reason = "TARGET" if hit_target else "STOP_LOSS"
                        closed = db.close_trade(trade["id"], float(live))
                        if closed and not closed.get("notes"):
                            db.save_postmortem(trade["id"], _postmortem(closed))
                        app.logger.info(
                            "Auto-closed trade #%s %s at ₹%.2f (%s)",
                            trade["id"], trade["ticker"], live, exit_reason,
                        )
                        continue

                    # Timeframe-expiry auto-close: maximum hold time once prediction window ends.
                    auto_close_date = trade.get("auto_close_date")
                    if auto_close_date and trade.get("status") == "OPEN":
                        from datetime import datetime, timedelta, timezone as _tz
                        now_ist = datetime.now(_tz.utc).astimezone(_tz(timedelta(hours=5, minutes=30)))
                        # Close after market close (15:31 IST) on the expiry date.
                        market_closed = now_ist.hour > 15 or (now_ist.hour == 15 and now_ist.minute >= 31)
                        if now_ist.strftime("%Y-%m-%d") >= auto_close_date and market_closed:
                            exp_live = _current_price(trade["ticker"])
                            if not exp_live:
                                app.logger.warning(
                                    "Skipping auto-close for trade #%s %s — live price unavailable; "
                                    "will retry next cycle",
                                    trade["id"], trade["ticker"],
                                )
                                continue
                            closed = db.close_trade(trade["id"], exp_live)
                            if closed and not closed.get("notes"):
                                db.save_postmortem(trade["id"], _postmortem(closed))
                            app.logger.info(
                                "Timeframe-expired trade #%s %s closed at ₹%.2f",
                                trade["id"], trade["ticker"], exp_live,
                            )
            except Exception as exc:
                app.logger.warning("Trade monitor error: %s", exc)

            try:
                # Check pending limit orders.
                pending = db.get_pending_orders()
                for order in pending:
                    live = _current_price(order["ticker"])
                    if live is None:
                        continue
                    direction = order["direction"]
                    limit = order["entry_price"]
                    tol = 0.001
                    if (direction == "LONG" and live <= limit) or \
                       (direction == "SHORT" and live >= limit):
                        db.fill_order(order["id"], fill_price=live)
                        app.logger.info(
                            "Auto-filled order #%s %s at ₹%.2f", order["id"], order["ticker"], live
                        )
            except Exception as exc:
                app.logger.warning("Order monitor error: %s", exc)

            _time.sleep(CHECK_INTERVAL)

    threading.Thread(target=_run, daemon=True, name="trade-monitor").start()


def _start_validation_scheduler():
    """Background thread: auto-run pending validations after NSE market close (3:45pm IST) daily.

    Polls every 5 minutes.  Tracks which calendar date it last ran so it only
    fires once per trading day regardless of how many times the poll fires.
    """
    import threading, time as _time

    _IST = timezone(timedelta(hours=5, minutes=30))
    POLL_SECS = 300  # check every 5 minutes

    def _run():
        last_ran_date = None
        _time.sleep(15)  # let Flask finish binding before starting
        while True:
            try:
                now_ist = datetime.now(timezone.utc).astimezone(_IST)
                today = now_ist.date()

                # Only fire on trading days, after 15:45 IST, and at most once per day.
                if (
                    last_ran_date != today
                    and nse_is_trading_day(today)
                    and (now_ist.hour, now_ist.minute) >= (16, 30)
                ):
                    due_count = db.get_validation_pending_count(due_only=True)
                    if due_count > 0:
                        app.logger.info(
                            "Validation scheduler: %d items due — running auto-execute", due_count
                        )
                        # Import and reuse the same execute logic inline to avoid an HTTP round-trip.
                        from self_learning import analyze_and_update
                        pending = db.get_validation_pending(limit=500, due_only=True)
                        actionable = [
                            s for s in pending
                            if (s.get("direction") or "").upper() not in ("NO TRADE", "N/A")
                            and (s.get("current_price") or 0) > 0
                        ]
                        validated = 0
                        hits = 0
                        misses = 0
                        today_str = today.isoformat()
                        with ThreadPoolExecutor(max_workers=min(len(actionable), 10) or 1) as pool:
                            def _fw(snap):
                                tf = (snap.get("timeframe") or "").upper()
                                tgt = snap.get("validation_target_date")
                                try:
                                    if tf == "INTRADAY":
                                        return snap, *_fetch_intraday_window(snap["ticker"], tgt)
                                    created = (snap.get("created_at") or "")[:10]
                                    try:
                                        ws = (datetime.strptime(created, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
                                    except ValueError:
                                        ws = tgt
                                    wh, wl, ap = _fetch_price_window(snap["ticker"], ws, tgt)
                                    if ap is None and tgt == today_str:
                                        wh2, wl2, ap2 = _fetch_intraday_window_capped(snap["ticker"], tgt, cutoff_hour=15, cutoff_minute=30)
                                        if ap2 is None:
                                            from data_sources import fetch_live_price as _flp
                                            live = _flp(snap["ticker"], allow_delayed=True)
                                            if live and live > 0:
                                                ap2, wh2, wl2 = live, (wh2 or live), (wl2 or live)
                                        wh, wl, ap = (wh2 or wh), (wl2 or wl), ap2
                                    return snap, wh, wl, ap
                                except Exception as exc:
                                    app.logger.warning("scheduler _fw(%s): %s", snap.get("ticker"), exc)
                                    return snap, None, None, None

                            for snap, wh, wl, ap in pool.map(_fw, actionable):
                                try:
                                    if not ap:
                                        tgt = snap.get("validation_target_date") or ""
                                        try:
                                            days_overdue = (today - date.fromisoformat(tgt)).days
                                        except ValueError:
                                            days_overdue = 0
                                        if days_overdue > _STALE_PENDING_GIVEUP_DAYS:
                                            db.mark_prediction_expired(snap.get("id"))
                                            app.logger.warning(
                                                "Scheduler expiring stale PENDING #%s %s "
                                                "(target %s, %d days overdue, price still unfetchable)",
                                                snap.get("id"), snap.get("ticker"), tgt, days_overdue,
                                            )
                                        continue
                                    ep = snap.get("current_price", 0)
                                    ar = round((ap - ep) / ep * 100, 2)
                                    tlo = snap.get("target_price_lo") or 0
                                    thi = snap.get("target_price_hi") or 0
                                    direction = (snap.get("direction") or "NEUTRAL").upper()
                                    hit = _intraday_target_hit(direction, wh, wl, ap, tlo, thi, ep)
                                    if hit is None:
                                        db.mark_prediction_skipped(snap.get("id"))
                                        continue
                                    db.validate_prediction(snap.get("id"), ap, ar, hit, wh, wl)
                                    validated += 1
                                    if hit:
                                        hits += 1
                                    else:
                                        misses += 1
                                except Exception as exc:
                                    app.logger.warning("scheduler validate(%s): %s", snap.get("id"), exc)

                        app.logger.info(
                            "Validation scheduler done: %d validated (%d HIT, %d MISS)",
                            validated, hits, misses,
                        )

                        if validated > 0:
                            try:
                                learn_result = analyze_and_update()  # all history
                                if learn_result.get("status") != "insufficient_data":
                                    pruned = db.prune_validated_snapshots()
                                    if pruned:
                                        app.logger.info("Scheduler pruned %d validated snapshots", pruned)
                            except Exception as le:
                                app.logger.warning("Scheduler self-learning update failed: %s", le)

                    last_ran_date = today

            except Exception as exc:
                app.logger.warning("Validation scheduler error: %s", exc)

            _time.sleep(POLL_SECS)

    threading.Thread(target=_run, daemon=True, name="validation-scheduler").start()


def _start_intraday_refresh_scheduler():
    """Background thread: auto-refresh INTRADAY watchlist predictions every 15 min during market hours."""
    import threading, time as _time
    from datetime import timezone, timedelta

    REFRESH_INTERVAL = 180  # 3 minutes

    def _ist_now():
        return __import__("datetime").datetime.now(timezone(timedelta(hours=5, minutes=30)))

    def _run():
        _time.sleep(30)  # let Flask finish binding before starting
        while True:
            try:
                ist = _ist_now()
                # Run 09:00–15:30 IST on trading days — the 09:00 start pre-warms an INTRADAY
                # preview during PRE_MARKET so a directional lean is ready at the 09:15 bell.
                market_open = ist.hour * 60 + ist.minute >= 9 * 60
                market_close = ist.hour * 60 + ist.minute <= 15 * 60 + 30
                if market_open and market_close and nse_is_trading_day(ist.date()):
                    mkt_status = nse_market_status()
                    _status = mkt_status.get("status")
                    if _status in ("OPEN", "PRE_MARKET"):
                        _is_premarket = _status == "PRE_MARKET"
                        market_ctx = _watchlist_market_ctx()
                        wl = db.get_watchlist()
                        tickers = [item["ticker"] for item in wl]
                        now = _time.time()
                        for tk in tickers:
                            try:
                                start, end = timeframe_to_dates("INTRADAY")
                                pred = _gated_predict(
                                    tk, start, end,
                                    _market_ctx=market_ctx,
                                    _run_ai_forecast=True,
                                    _ai_fast_mode=True,
                                    _ai_fast_fail_on_rate_limit=True,
                                )
                                if not pred.get("error"):
                                    _reason = pred.get("no_trade_reason")
                                    if _is_premarket:
                                        pred["intraday_premarket"] = True
                                    # If the prior cached call's target was reached, this fresh
                                    # call is a re-evaluation off the new level — badge it.
                                    if not _is_premarket and _intraday_pred_has_target(pred):
                                        _prev = _WATCHLIST_PICK_CACHE.get((tk, "INTRADAY"))
                                        _prev_pred = _prev.get("pred") if _prev else None
                                        if (_intraday_pred_has_target(_prev_pred)
                                                and _intraday_target_reached(
                                                    _prev_pred, pred.get("price") or pred.get("current_price"))):
                                            pred["intraday_reevaluated"] = True
                                            pred["reeval_time"] = ist.strftime("%H:%M")
                                            pred["prev_target"] = (_prev_pred.get("target_price_hi")
                                                                   or _prev_pred.get("target_price_lo"))
                                    # Don't cache transient timeouts (let the next refresh/fetch retry);
                                    # short TTL for hard ai_unavailable.
                                    if _reason != "timeout":
                                        _ttl = (_WATCHLIST_PICK_AI_UNAVAILABLE_TTL
                                                if _reason == "ai_unavailable"
                                                else _cache_ttl_for_tf("INTRADAY"))
                                        _WATCHLIST_PICK_CACHE[(tk, "INTRADAY")] = {
                                            "ts": now,
                                            "pred": pred,
                                            "ttl": _ttl,
                                        }
                                    # Capture the freshest valid live call as the session's final
                                    # call (skip pre-market previews — not a real session call).
                                    if not _is_premarket:
                                        _remember_intraday_call(tk, pred)
                            except Exception as exc:
                                app.logger.debug("INTRADAY refresh failed for %s: %s", tk, exc)
                        app.logger.info("INTRADAY cache refreshed for %d tickers (%s)", len(tickers), _status)
            except Exception as exc:
                app.logger.warning("INTRADAY refresh scheduler error: %s", exc)
            _time.sleep(REFRESH_INTERVAL)

    threading.Thread(target=_run, daemon=True, name="intraday-refresh").start()


def _start_ollama_keepalive():
    """Ping Ollama every 10 min to prevent HF Space cold-start hangs during inference."""
    _ep = os.environ.get("OLLAMA_ENDPOINT", "").strip()
    if not _ep:
        return

    import threading, time as _time
    _INTERVAL = 600  # 10 minutes — HF free tier sleeps after ~15 min

    def _run():
        _time.sleep(30)  # give app startup a moment first
        while True:
            try:
                from ollama_client import warmup_ollama, get_ollama_model
                _m = get_ollama_model(_ep)
                _ok = warmup_ollama(_ep, model=_m, timeout=30)
                if _ok:
                    app.logger.debug("Ollama keepalive ping succeeded (%s)", _m)
                else:
                    app.logger.info("Ollama keepalive: Space not responding (cold/busy) — will retry in %ds", _INTERVAL)
            except Exception as _e:
                app.logger.debug("Ollama keepalive error: %s", _e)
            _time.sleep(_INTERVAL)

    threading.Thread(target=_run, daemon=True, name="ollama-keepalive").start()
    app.logger.info("Ollama keepalive started (interval=%ds, endpoint=%s)", _INTERVAL, _ep)


# Start background services at import time so both `python app.py` and
# WSGI servers (gunicorn) warm the top5 cache and run the trade monitor.
_prewarm_top5()
_start_trade_monitor()
_start_validation_scheduler()
_start_intraday_refresh_scheduler()
_start_ollama_keepalive()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    space_url = os.environ.get("SPACE_URL", f"http://localhost:{port}")
    print(f"\n  NSE Paper Trading Platform — Web UI")
    print(f"  Open {space_url} in your browser\n")
    # threaded=True is required: without it Werkzeug serves one request at a time, so a slow
    # AI/LLM forecast call (/api/watchlist-pick) blocks every other request — including the
    # "instant" /api/ml-predict calls — until it finishes (looks like ML is stuck loading).
    app.run(debug=False, port=port, host="0.0.0.0", threaded=True)
