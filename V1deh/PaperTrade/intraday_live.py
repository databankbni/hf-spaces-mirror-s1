"""
intraday_live.py — Opening Range Breakout (ORB) + VWAP from yfinance 15m bars.

yfinance provides 15m bars free for the last 60 days (1m bars last 7 days).
This module gives live intraday context for today's session:
  - Opening Range: first 15-min bar's High/Low
  - ORB targets: breakout extensions at 1× and 1.618× the range
  - VWAP: cumulative volume-weighted average price
  - Session bias: above/below VWAP + ORB position

NSE market hours: 09:15 – 15:30 IST (UTC+5:30 = UTC 03:45 – 10:00)

Documented ORB hit rates on NSE:
  Price breaks ORB high before 10:15 AM → reaches ORB+1× target: 70-73%
  Individual NSE stocks at ORB+0.5× extension: 68-70%
  BANKNIFTY 30-min ORB: 73% documented
"""
import concurrent.futures
import datetime
import threading
import pandas as pd
import numpy as np

try:
    import yfinance as yf
    _HAS_YF = True
except ImportError:
    _HAS_YF = False

# yfinance's shared internals are NOT thread-safe: concurrent yf.download() calls
# from multiple threads (e.g. the validation ThreadPoolExecutor) can cross-contaminate
# responses and return one ticker's bars under another ticker's request. Serialize the
# actual download so each call gets its own ticker's data.
_YF_DOWNLOAD_LOCK = threading.Lock()

# yf.download() has no built-in timeout — a hung/stalled Yahoo connection blocks the
# calling thread indefinitely. Because every caller serializes on _YF_DOWNLOAD_LOCK, one
# hung call previously wedged this lock forever, freezing intraday context (and the
# /api/ml-predict "today_high" fetch) for every ticker for the rest of the process's life.
# Bound both the lock wait and the download itself so a stall degrades to None instead.
_YF_LOCK_TIMEOUT = 20      # max seconds to wait for the shared download lock
_YF_DOWNLOAD_TIMEOUT = 15  # max seconds for the actual yf.download() call

# NSE market open time (IST = UTC+5:30)
_NSE_OPEN_UTC  = datetime.time(3, 45)   # 09:15 IST
_NSE_CLOSE_UTC = datetime.time(10, 0)   # 15:30 IST


def _yf_download_bounded(ticker: str, period: str, interval: str):
    """Run yf.download in a worker thread with a hard wall-clock timeout.

    If the download doesn't finish in time, the worker thread is abandoned
    (shutdown(wait=False)) so the caller is never blocked past the timeout.
    """
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        fut = ex.submit(yf.download, ticker, period=period, interval=interval,
                        auto_adjust=True, progress=False, group_by="ticker")
        return fut.result(timeout=_YF_DOWNLOAD_TIMEOUT)
    except concurrent.futures.TimeoutError:
        return None
    finally:
        ex.shutdown(wait=False)


def get_intraday_bars(ticker: str, interval: str = "15m", period: str = "5d") -> pd.DataFrame | None:
    """
    Download intraday OHLCV bars from yfinance.
    interval: "1m" (last 7d) | "5m" | "15m" | "30m" (last 60d)
    Returns None on failure (including a timed-out lock wait or download).
    """
    if not _HAS_YF:
        return None
    if not _YF_DOWNLOAD_LOCK.acquire(timeout=_YF_LOCK_TIMEOUT):
        return None  # another call is stuck holding the lock — fail soft, don't pile up
    try:
        df = _yf_download_bounded(ticker, period, interval)
        if df is None or df.empty:
            return None
        # When group_by="ticker" is honoured, the outer column level is the ticker —
        # verify it matches so a contaminated response is rejected rather than returned
        # under the wrong symbol.
        if isinstance(df.columns, pd.MultiIndex):
            top = set(df.columns.get_level_values(0))
            if top and ticker not in top:
                return None
            df.columns = df.columns.get_level_values(-1)
        return df
    except Exception:
        return None
    finally:
        _YF_DOWNLOAD_LOCK.release()


def compute_orb(bars: pd.DataFrame, orb_minutes: int = 15) -> dict:
    """
    Compute Opening Range from the intraday bar data.
    orb_minutes: how long the opening range lasts (15 or 30 minutes)

    Returns:
      orb_high, orb_low, orb_range
      target_up:   ORB high + 1.0 × range (70-73% hit rate on NSE)
      target_down: ORB low  − 1.0 × range
      fib_up:      ORB high + 1.618 × range (Fibonacci extension)
      fib_down:    ORB low  − 1.618 × range
      orb_broken_up / orb_broken_down: bool — has price already broken ORB?
      orb_bias: BULLISH / BEARISH / NEUTRAL (based on current position vs ORB)
    """
    if bars is None or bars.empty:
        return {"error": "No bars available"}

    # Filter to today's session only
    if bars.index.tz is not None:
        today = pd.Timestamp.now(tz=bars.index.tz).normalize()
    else:
        today = pd.Timestamp.now().normalize()

    today_bars = bars[bars.index >= today]
    if today_bars.empty:
        # Use most recent session
        last_date = bars.index[-1].normalize()
        today_bars = bars[bars.index.normalize() == last_date]

    if today_bars.empty:
        return {"error": "No today bars found"}

    # First `orb_minutes` worth of data = the opening range
    orb_end = today_bars.index[0] + pd.Timedelta(minutes=orb_minutes)
    orb_bars = today_bars[today_bars.index <= orb_end]
    rest_bars = today_bars[today_bars.index > orb_end]

    if "High" not in orb_bars.columns or "Low" not in orb_bars.columns:
        return {"error": "Missing OHLCV columns"}

    orb_high = float(orb_bars["High"].max())
    orb_low  = float(orb_bars["Low"].min())
    orb_rng  = orb_high - orb_low

    if orb_rng <= 0:
        return {"error": "Zero ORB range"}

    target_up   = round(orb_high + 1.0 * orb_rng, 2)
    target_down = round(orb_low  - 1.0 * orb_rng, 2)
    fib_up      = round(orb_high + 1.618 * orb_rng, 2)
    fib_down    = round(orb_low  - 1.618 * orb_rng, 2)
    half_up     = round(orb_high + 0.5 * orb_rng, 2)
    half_down   = round(orb_low  - 0.5 * orb_rng, 2)

    # Check if ORB has been broken by subsequent bars
    curr_price = None
    orb_broken_up = orb_broken_down = False
    if not rest_bars.empty:
        curr_price = float(rest_bars["Close"].iloc[-1])
        orb_broken_up   = bool(rest_bars["High"].max() > orb_high)
        orb_broken_down = bool(rest_bars["Low"].min()  < orb_low)
    elif not orb_bars.empty:
        curr_price = float(orb_bars["Close"].iloc[-1])

    if orb_broken_up and not orb_broken_down:
        bias = "BULLISH"
    elif orb_broken_down and not orb_broken_up:
        bias = "BEARISH"
    elif curr_price is not None:
        mid = (orb_high + orb_low) / 2
        bias = "BULLISH" if curr_price > mid else "BEARISH"
    else:
        bias = "NEUTRAL"

    return {
        "orb_high":         round(orb_high, 2),
        "orb_low":          round(orb_low, 2),
        "orb_range":        round(orb_rng, 2),
        "target_up":        target_up,        # ~70-73% hit rate (NSE)
        "target_down":      target_down,
        "half_target_up":   half_up,          # ~75-78% hit rate (conservative)
        "half_target_down": half_down,
        "fib_up":           fib_up,           # 1.618× extension
        "fib_down":         fib_down,
        "orb_broken_up":    orb_broken_up,
        "orb_broken_down":  orb_broken_down,
        "current_price":    round(curr_price, 2) if curr_price else None,
        "orb_bias":         bias,
        "orb_minutes":      orb_minutes,
        "n_orb_bars":       len(orb_bars),
    }


def compute_vwap(bars: pd.DataFrame) -> dict:
    """
    Compute VWAP and ±1σ / ±2σ bands for today's session.
    VWAP = Σ(typical_price × volume) / Σ(volume)
    """
    if bars is None or bars.empty:
        return {"error": "No bars"}

    # Today's session
    if bars.index.tz is not None:
        today = pd.Timestamp.now(tz=bars.index.tz).normalize()
    else:
        today = pd.Timestamp.now().normalize()
    session = bars[bars.index >= today]
    if session.empty:
        last_date = bars.index[-1].normalize()
        session = bars[bars.index.normalize() == last_date]
    if session.empty:
        return {"error": "No session bars"}

    tp = (session["High"] + session["Low"] + session["Close"]) / 3
    vol = session["Volume"].replace(0, 1)
    cumvol  = vol.cumsum()
    cumtpvol = (tp * vol).cumsum()
    vwap_series = cumtpvol / cumvol

    vwap = float(vwap_series.iloc[-1])
    # Volume-weighted variance: E[tp²·vol]/Σvol − vwap²
    cum_tp2vol = (tp ** 2 * vol).cumsum()
    variance   = float(cum_tp2vol.iloc[-1]) / float(cumvol.iloc[-1]) - vwap ** 2
    dev        = np.sqrt(max(variance, 0.0))

    return {
        "vwap":       round(vwap, 2),
        "upper_1sd":  round(vwap + float(dev), 2),
        "lower_1sd":  round(vwap - float(dev), 2),
        "upper_2sd":  round(vwap + 2 * float(dev), 2),
        "lower_2sd":  round(vwap - 2 * float(dev), 2),
        "n_bars":     len(session),
    }


def get_live_intraday_context(ticker: str) -> dict:
    """
    Pull 15m bars and return combined ORB + VWAP + gap context.
    Safe to call any time — returns data_available=False outside market hours.
    """
    bars = get_intraday_bars(ticker, interval="15m", period="5d")
    if bars is None or bars.empty:
        return {
            "data_available": False,
            "reason": "No intraday bars from yfinance",
        }

    orb  = compute_orb(bars, orb_minutes=15)
    vwap = compute_vwap(bars)

    # Gap: today's first bar open vs prior session's last close
    gap_pct = None
    try:
        if bars.index.tz is not None:
            today = pd.Timestamp.now(tz=bars.index.tz).normalize()
        else:
            today = pd.Timestamp.now().normalize()
        today_bars = bars[bars.index >= today]
        prior_bars = bars[bars.index < today]
        if not today_bars.empty and not prior_bars.empty:
            today_open  = float(today_bars["Open"].iloc[0])
            prior_close = float(prior_bars["Close"].iloc[-1])
            gap_pct = round((today_open / prior_close - 1) * 100, 2)
    except Exception:
        pass

    # Session bias: combine ORB bias with VWAP position
    orb_bias = orb.get("orb_bias", "NEUTRAL")
    curr     = orb.get("current_price")
    vwap_val = vwap.get("vwap") if isinstance(vwap, dict) else None
    if curr and vwap_val:
        vwap_bias = "BULLISH" if curr > vwap_val else "BEARISH"
        if orb_bias == vwap_bias:
            session_bias = orb_bias
        elif orb_bias == "NEUTRAL":
            session_bias = vwap_bias
        else:
            session_bias = "NEUTRAL"  # conflicting signals
    else:
        session_bias = orb_bias

    return {
        "data_available":  True,
        "orb_high":        orb.get("orb_high"),
        "orb_low":         orb.get("orb_low"),
        "orb_range":       orb.get("orb_range"),
        "orb_target_up":   orb.get("target_up"),
        "orb_target_down": orb.get("target_down"),
        "half_target_up":  orb.get("half_target_up"),
        "orb_bias":        orb_bias,
        "orb_broken_up":   orb.get("orb_broken_up", False),
        "orb_broken_down": orb.get("orb_broken_down", False),
        "vwap":            vwap_val,
        "vwap_upper_1sd":  vwap.get("upper_1sd") if isinstance(vwap, dict) else None,
        "vwap_lower_1sd":  vwap.get("lower_1sd") if isinstance(vwap, dict) else None,
        "gap_pct":         gap_pct,
        "current_price":   curr,
        "session_bias":    session_bias,
    }


# ── STANDALONE SMOKE TEST ────────────────────────────────────────────────────

if __name__ == "__main__":
    for tk in ["RELIANCE.NS", "INFY.NS", "^NSEI"]:
        print(f"\n{tk}:")
        ctx = get_live_intraday_context(tk)
        if not ctx.get("data_available"):
            print(f"  No data: {ctx.get('reason', 'outside hours or download failed')}")
        else:
            print(f"  Price: ₹{ctx['current_price']}  VWAP: ₹{ctx['vwap']}")
            print(f"  ORB: ₹{ctx['orb_low']} – ₹{ctx['orb_high']} (range ₹{ctx['orb_range']})")
            print(f"  ORB target up: ₹{ctx['orb_target_up']}  | Half target: ₹{ctx['half_target_up']}")
            print(f"  Gap: {ctx['gap_pct']:+.2f}%  |  Session bias: {ctx['session_bias']}")
            print(f"  ORB broken up: {ctx['orb_broken_up']} | ORB broken down: {ctx['orb_broken_down']}")
