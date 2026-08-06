"""
fred_data.py — US/global macro indicators that drive EM India equity risk regimes.

Primary source: FRED API (fredapi library, free key at https://fred.stlouisfed.org)
Fallback: yfinance Treasury yield proxies when no FRED key is configured.

Cache: fred_macro_cache.json, 24h TTL (FRED data is daily, no intraday updates).

Usage:
    from fred_data import get_fred_macro
    ctx = get_fred_macro()
    # ctx["risk_regime"] → "RISK_ON" | "CAUTIOUS" | "RISK_OFF"

Run standalone to test:
    python fred_data.py
"""

from __future__ import annotations
import json
import logging
import os
import time
from datetime import datetime, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

_FRED_API_KEY = os.getenv("FRED_API_KEY", "")
_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fred_macro_cache.json")
_CACHE_TTL_HOURS = 24


# ── CACHE ─────────────────────────────────────────────────────────────────────

def _load_cache() -> dict | None:
    try:
        if not os.path.exists(_CACHE_FILE):
            return None
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        cached_at = data.get("cached_at", "")
        if cached_at:
            age_hours = (time.time() - datetime.fromisoformat(cached_at).timestamp()) / 3600
            if age_hours < _CACHE_TTL_HOURS:
                return data
    except Exception as e:
        logging.debug("fred_data: cache load failed: %s", e)
    return None


def _save_cache(result: dict) -> None:
    try:
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f)
    except Exception as e:
        logging.debug("fred_data: cache save failed: %s", e)


# ── RISK SCORING ──────────────────────────────────────────────────────────────

def _compute_risk_score(
    yield_spread_bps: float,
    fed_rate: float,
    cpi_yoy: float,
    usd_strength: float,
) -> tuple[int, str]:
    """
    Composite risk score 0–100 (higher = more risk-off for Indian equities).
    Returns (score, regime).
    """
    score = 0

    # Yield curve: inversion or flattening is a leading recession indicator
    if yield_spread_bps < 0:
        score += 30      # inverted
    elif yield_spread_bps < 50:
        score += 15      # flattening

    # Fed rate: high rates attract capital back to US, hurt EM flows
    if fed_rate >= 5.5:
        score += 25
    elif fed_rate >= 4.5:
        score += 15
    elif fed_rate >= 3.5:
        score += 8

    # CPI: high US inflation keeps Fed hawkish
    if cpi_yoy >= 5.0:
        score += 15
    elif cpi_yoy >= 3.5:
        score += 7

    # USD broad index: strong dollar → INR pressure → FII outflows
    if usd_strength >= 110:
        score += 20
    elif usd_strength >= 105:
        score += 10
    elif usd_strength >= 102:
        score += 5

    score = min(100, score)

    if score >= 55:
        regime = "RISK_OFF"
    elif score >= 28:
        regime = "CAUTIOUS"
    else:
        regime = "RISK_ON"

    return score, regime


# ── FREDAPI FETCH ─────────────────────────────────────────────────────────────

def _fetch_via_fredapi() -> dict | None:
    """Fetch FRED series using the fredapi library. Returns None if unavailable."""
    try:
        import fredapi  # noqa: F401
    except ImportError:
        logging.info("fred_data: fredapi not installed; run: pip install fredapi")
        return None

    if not _FRED_API_KEY:
        logging.info("fred_data: FRED_API_KEY not set; skipping fredapi fetch")
        return None

    try:
        from fredapi import Fred
        fred = Fred(api_key=_FRED_API_KEY)

        end = datetime.today()
        start = end - timedelta(days=30)

        def _latest(series_id: str) -> float | None:
            try:
                s = fred.get_series(series_id, observation_start=start, observation_end=end)
                s = s.dropna()
                return float(s.iloc[-1]) if not s.empty else None
            except Exception as e:
                logging.warning("fred_data: FRED series %s failed: %s", series_id, e)
                return None

        t10y2y = _latest("T10Y2Y")       # 10Y-2Y spread (%, not bps)
        fedfunds = _latest("FEDFUNDS")   # Fed Funds Rate (%)
        cpi = _latest("CPIAUCSL")        # CPI level — need YoY %
        usd = _latest("DTWEXBGS")        # Broad USD index

        # CPI YoY: compare to 12 months ago
        cpi_yoy = None
        try:
            cpi_series = fred.get_series(
                "CPIAUCSL",
                observation_start=end - timedelta(days=400),
                observation_end=end,
            ).dropna()
            if len(cpi_series) >= 13:
                latest_cpi = float(cpi_series.iloc[-1])
                year_ago_cpi = float(cpi_series.iloc[-13])
                cpi_yoy = round((latest_cpi / year_ago_cpi - 1) * 100, 2)
        except Exception:
            pass

        if t10y2y is None and fedfunds is None:
            return None

        spread_bps = round(t10y2y * 100, 1) if t10y2y is not None else 0.0
        fed_rate = round(fedfunds, 2) if fedfunds is not None else 5.25
        cpi_val = round(cpi_yoy, 2) if cpi_yoy is not None else 3.5
        usd_val = round(usd, 2) if usd is not None else 104.0

        score, regime = _compute_risk_score(spread_bps, fed_rate, cpi_val, usd_val)

        return {
            "yield_curve_spread_bps": spread_bps,
            "yield_curve_inverted": spread_bps < 0,
            "fed_rate": fed_rate,
            "cpi_yoy": cpi_val,
            "usd_strength": usd_val,
            "macro_risk_score": score,
            "risk_regime": regime,
            "source": "fredapi",
            "cached_at": datetime.now().isoformat(),
        }
    except Exception as e:
        logging.warning("fred_data: fredapi fetch failed: %s", e)
        return None


# ── YFINANCE FALLBACK ─────────────────────────────────────────────────────────

def _fetch_via_yfinance() -> dict:
    """
    Fallback: derive yield curve from yfinance Treasury tickers.
    ^TNX = 10-Year Treasury yield (%).
    ^IRX = 13-Week T-Bill yield (closest free proxy for short rates on YF).
    DX-Y.NYB = USD index (DXY).
    """
    try:
        import yfinance as yf
    except ImportError:
        return _stale_fallback("yfinance not installed")

    def _get_yield(ticker: str) -> float | None:
        try:
            raw = yf.Ticker(ticker).fast_info
            price = getattr(raw, "last_price", None) or getattr(raw, "regularMarketPrice", None)
            if price and float(price) > 0:
                return float(price)
        except Exception:
            pass
        # Alternative: download last 5 days
        try:
            df = yf.download(ticker, period="5d", progress=False, auto_adjust=True)
            if not df.empty:
                close = df["Close"]
                if hasattr(close, "iloc"):
                    return float(close.dropna().iloc[-1])
        except Exception:
            pass
        return None

    t10y = _get_yield("^TNX")    # 10-Year (%)
    t3m  = _get_yield("^IRX")    # 13-Week T-Bill (%) — proxy for short end
    dxy  = _get_yield("DX-Y.NYB") or _get_yield("UUP")   # USD index

    spread_bps = 0.0
    if t10y is not None and t3m is not None:
        spread_bps = round((t10y - t3m) * 100, 1)
    elif t10y is not None:
        spread_bps = 50.0  # assume flat if only 10Y available

    fed_rate = t3m if t3m is not None else 5.25
    usd_val = round(dxy, 2) if dxy is not None else 104.0
    cpi_yoy = 3.5  # cannot derive CPI from yfinance; use recent approximate

    score, regime = _compute_risk_score(spread_bps, fed_rate, cpi_yoy, usd_val)

    return {
        "yield_curve_spread_bps": spread_bps,
        "yield_curve_inverted": spread_bps < 0,
        "fed_rate": round(fed_rate, 2),
        "cpi_yoy": cpi_yoy,
        "usd_strength": usd_val,
        "macro_risk_score": score,
        "risk_regime": regime,
        "source": "yfinance_fallback",
        "cached_at": datetime.now().isoformat(),
    }


def _stale_fallback(reason: str) -> dict:
    """Return a neutral baseline when all data sources fail."""
    logging.warning("fred_data: all sources failed (%s); returning neutral defaults", reason)
    return {
        "yield_curve_spread_bps": 30.0,
        "yield_curve_inverted": False,
        "fed_rate": 5.25,
        "cpi_yoy": 3.5,
        "usd_strength": 104.0,
        "macro_risk_score": 28,
        "risk_regime": "CAUTIOUS",
        "source": "fallback",
        "cached_at": datetime.now().isoformat(),
    }


# ── PUBLIC API ────────────────────────────────────────────────────────────────

def get_fred_macro(force_refresh: bool = False) -> dict:
    """
    Return US/global macro indicators dict.

    Keys:
      yield_curve_spread_bps  — 10Y-2Y (or 10Y-3M) spread in basis points
      yield_curve_inverted    — True if spread < 0
      fed_rate                — Federal Funds or short-term rate (%)
      cpi_yoy                 — US CPI year-over-year % (FRED only; 3.5 estimate for fallback)
      usd_strength            — Broad USD index level (100 = Jan 2006 baseline)
      macro_risk_score        — 0–100 composite (higher = more risk-off)
      risk_regime             — "RISK_ON" | "CAUTIOUS" | "RISK_OFF"
      source                  — "fredapi" | "yfinance_fallback" | "fallback" | "cache"
      cached_at               — ISO timestamp of last fetch
    """
    if not force_refresh:
        cached = _load_cache()
        if cached:
            cached["source"] = "cache"
            return cached

    result = _fetch_via_fredapi()
    if result is None:
        result = _fetch_via_yfinance()

    _save_cache(result)
    return result


def _regime_gate(result: dict) -> dict:
    """
    Return a simplified gate dict compatible with macro_context.MacroContext.get() format.
    Adds fred_risk_on key (True when regime is RISK_ON or CAUTIOUS).
    """
    regime = result.get("risk_regime", "CAUTIOUS")
    return {
        "fred_risk_on": regime in ("RISK_ON", "CAUTIOUS"),
        "fred_risk_regime": regime,
        "fred_yield_inverted": result.get("yield_curve_inverted", False),
        "fred_macro_risk_score": result.get("macro_risk_score", 50),
    }


def get_fred_gate() -> dict:
    """Convenience wrapper returning gate-compatible dict for macro_context integration."""
    return _regime_gate(get_fred_macro())


if __name__ == "__main__":
    import pprint
    print("Fetching US macro indicators...")
    result = get_fred_macro(force_refresh=True)
    pprint.pprint(result)
    print(f"\nRisk regime: {result['risk_regime']}  (score: {result['macro_risk_score']}/100)")
    print(f"Yield curve: {'INVERTED' if result['yield_curve_inverted'] else 'NORMAL'} "
          f"({result['yield_curve_spread_bps']:+.0f} bps)")
    print(f"Fed rate: {result['fed_rate']:.2f}%  |  USD index: {result['usd_strength']:.1f}")
