"""
fundamentals.py — NSE stock fundamentals scorer.

Implements the "Point 2 — Fundamentals Analyst" from CLAUDE.md.
Data source: yfinance Ticker.info, .quarterly_financials, .balance_sheet, .cashflow
Cache: fundamentals_cache.json, 24h TTL per ticker (quarterly data doesn't change intraday).

Usage:
    from fundamentals import get_fundamentals
    result = get_fundamentals("RELIANCE.NS")
    # result["fundamental_score"] → 0-100
    # result["summary"]           → one-sentence assessment

Run standalone to test:
    python fundamentals.py RELIANCE.NS
"""

from __future__ import annotations
import json
import logging
import math
import os
import time
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fundamentals_cache.json")
_CACHE_TTL_HOURS = 24
_YF_BLOCK_UNTIL = 0.0
_YF_COOLDOWN_SECS = 1800
_WARNED_FETCH_ERRORS: set[tuple[str, str]] = set()


# ── NSE SECTOR PE BENCHMARKS (approximate trailing PE, 2024-2025) ─────────────
# Used to classify a stock's PE as CHEAP / FAIR / EXPENSIVE relative to sector.
_SECTOR_PE = {
    "Financial Services":         22,
    "Banking":                    14,
    "Technology":                 28,
    "IT":                         28,
    "Healthcare":                 35,
    "Pharmaceutical":             32,
    "Consumer Defensive":         50,
    "FMCG":                       52,
    "Consumer Cyclical":          35,
    "Automobile":                 24,
    "Auto":                       24,
    "Basic Materials":            12,
    "Metals":                     11,
    "Energy":                     12,
    "Oil & Gas":                  12,
    "Real Estate":                30,
    "Utilities":                  18,
    "Power":                      16,
    "Industrials":                25,
    "Infrastructure":             22,
    "Communication Services":     18,
    "Consumer Electronics":       30,
}
_DEFAULT_SECTOR_PE = 22  # fallback when sector not matched


# ── CACHE ─────────────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    try:
        if not os.path.exists(_CACHE_FILE):
            return {}
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception as e:
        logging.debug("fundamentals: cache save failed: %s", e)


def _is_fresh(entry: dict, max_age_hours: float | None = None) -> bool:
    try:
        cached_at = entry.get("cached_at", "")
        age_hours = (time.time() - datetime.fromisoformat(cached_at).timestamp()) / 3600
        limit = max_age_hours if max_age_hours is not None else _CACHE_TTL_HOURS
        return age_hours < limit
    except Exception:
        return False


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _safe_float(val, default: float = 0.0) -> float:
    try:
        f = float(val)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _get_sector_pe(sector: str, industry: str) -> float:
    """Match sector/industry string to NSE sector PE benchmark.
    Tries exact match first, then substring — avoids 'Financial Services' matching 'Financial' (PE=22)
    when the stock is actually in Banking (PE=14)."""
    sector_l = (sector or "").lower()
    industry_l = (industry or "").lower()
    # 1. Exact match
    for key, pe in _SECTOR_PE.items():
        if key.lower() == sector_l or key.lower() == industry_l:
            return float(pe)
    # 2. Substring fallback
    for key, pe in _SECTOR_PE.items():
        if key.lower() in sector_l or key.lower() in industry_l:
            return float(pe)
    return float(_DEFAULT_SECTOR_PE)


def _pe_label(pe: float, sector_pe: float) -> str:
    if pe <= 0 or sector_pe <= 0:
        return "UNKNOWN"
    ratio = pe / sector_pe
    if ratio < 0.75:
        return "CHEAP"
    if ratio < 1.25:
        return "FAIR"
    return "EXPENSIVE"


def _debt_label(de: float) -> str:
    """Debt/equity ratio classification (yfinance returns % already, e.g. 150 = 1.5×)."""
    if de < 0:
        return "UNKNOWN"
    de_ratio = de / 100.0  # normalize from yfinance's % form
    if de_ratio < 0.3:
        return "LOW"
    if de_ratio < 0.8:
        return "MEDIUM"
    return "HIGH"


def _rev_label(growth: float | None) -> str:
    if growth is None:
        return "UNKNOWN"
    if growth > 0.08:
        return "GROWING"
    if growth > -0.05:
        return "STABLE"
    return "DECLINING"


# ── SCORING WEIGHTS ───────────────────────────────────────────────────────────
# Each factor contributes up to its max_points toward the 0–100 score.

def _score_pe(pe_label: str) -> int:
    return {"CHEAP": 25, "FAIR": 15, "EXPENSIVE": 5, "UNKNOWN": 10}.get(pe_label, 10)


def _score_debt(debt_label: str) -> int:
    return {"LOW": 20, "MEDIUM": 12, "HIGH": 4, "UNKNOWN": 8}.get(debt_label, 8)


def _score_revenue(rev_label: str) -> int:
    return {"GROWING": 20, "STABLE": 12, "DECLINING": 3, "UNKNOWN": 8}.get(rev_label, 8)


def _score_fcf(fcf_positive: bool, has_data: bool) -> int:
    if not has_data:
        return 8
    return 15 if fcf_positive else 3


def _score_roe(roe: float) -> int:
    # ROE > 20% is excellent; 12–20% good; < 12% weak
    if roe >= 0.20:
        return 20
    if roe >= 0.12:
        return 14
    if roe >= 0.06:
        return 8
    return 3


# ── MAIN FETCH FUNCTION ───────────────────────────────────────────────────────

def _fetch_fundamentals(ticker: str) -> dict:
    global _YF_BLOCK_UNTIL
    if time.time() < _YF_BLOCK_UNTIL:
        return _empty_result(ticker, "yfinance temporarily rate-limited")

    try:
        import yfinance as yf
    except ImportError:
        return _empty_result(ticker, "yfinance not installed")

    t = yf.Ticker(ticker)
    info = {}
    try:
        info = t.info or {}
    except Exception as e:
        err_txt = str(e).lower()
        if "too many requests" in err_txt or "rate limited" in err_txt or "429" in err_txt:
            _YF_BLOCK_UNTIL = time.time() + _YF_COOLDOWN_SECS
        if "nonetype" in err_txt and "iterable" in err_txt:
            key = (ticker, "nonetype")
            if key not in _WARNED_FETCH_ERRORS:
                _WARNED_FETCH_ERRORS.add(key)
                logging.warning("fundamentals: info fetch returned malformed payload for %s", ticker)
        else:
            key = (ticker, err_txt[:120])
            if key not in _WARNED_FETCH_ERRORS:
                _WARNED_FETCH_ERRORS.add(key)
                logging.warning("fundamentals: info fetch failed for %s: %s", ticker, e)
        return _empty_result(ticker, f"info fetch failed: {e}")

    # Validate this is actually an Indian stock — yf.Ticker("SCI") returns US Scientific Industries
    exchange = (info.get("exchange") or "").upper()
    country  = (info.get("country") or "")
    if exchange and exchange not in ("NSI", "BSE", "NSE", "NMS") and country not in ("India", ""):
        logging.warning("fundamentals: %s resolved to non-Indian stock (exchange=%s, country=%s) — skipping", ticker, exchange, country)
        return _empty_result(ticker, f"non-Indian stock: exchange={exchange} country={country}")

    # ── Primary fields from .info ──────────────────────────────────────────
    pe_trailing = _safe_float(info.get("trailingPE"), 0)
    pe_forward  = _safe_float(info.get("forwardPE"), 0)
    pe          = pe_trailing if pe_trailing > 0 else pe_forward  # prefer trailing
    de          = _safe_float(info.get("debtToEquity"), -1)       # yfinance returns %
    roe_raw     = _safe_float(info.get("returnOnEquity"), 0)       # decimal (0.18 = 18%)
    rev_growth  = info.get("revenueGrowth")                        # decimal YoY
    promoter    = _safe_float(info.get("heldPercentInsiders"), 0) * 100  # → %
    sector      = info.get("sector", "")
    industry    = info.get("industry", "")

    # ── FCF from cashflow statement ────────────────────────────────────────
    fcf_positive = False
    has_fcf = False
    try:
        cf = t.cashflow
        if cf is not None and not cf.empty:
            # yfinance cashflow rows vary; look for operating CF and capex
            rows = {str(r).lower(): r for r in cf.index}
            op_cf_key   = next((k for k in rows if "operating" in k), None)
            capex_key   = next((k for k in rows if "capital expenditure" in k or "capex" in k), None)
            if op_cf_key:
                op_cf_row = cf.loc[rows[op_cf_key]]
                op_cf = float(op_cf_row.dropna().iloc[0]) if not op_cf_row.dropna().empty else 0
                capex = 0
                if capex_key:
                    capex_row = cf.loc[rows[capex_key]]
                    capex = abs(float(capex_row.dropna().iloc[0])) if not capex_row.dropna().empty else 0
                fcf = op_cf - capex
                fcf_positive = fcf > 0
                has_fcf = True
    except Exception as e:
        logging.debug("fundamentals: cashflow fetch failed for %s: %s", ticker, e)

    # ── Revenue growth from quarterly financials if not in info ────────────
    if rev_growth is None:
        try:
            fin = t.quarterly_financials
            if fin is not None and not fin.empty:
                rows = {str(r).lower(): r for r in fin.index}
                rev_key = next((k for k in rows if "total revenue" in k or "revenue" in k), None)
                if rev_key:
                    rev_row = fin.loc[rows[rev_key]].dropna()
                    if len(rev_row) >= 5:
                        # Compare latest quarter vs same quarter 1 year ago
                        latest = float(rev_row.iloc[0])
                        year_ago = float(rev_row.iloc[4])
                        if year_ago > 0:
                            rev_growth = (latest / year_ago) - 1
        except Exception as e:
            logging.debug("fundamentals: quarterly financials failed for %s: %s", ticker, e)

    # ── Scoring ────────────────────────────────────────────────────────────
    sector_pe = _get_sector_pe(sector, industry)
    pe_lbl    = _pe_label(pe, sector_pe)
    debt_lbl  = _debt_label(de)
    rev_lbl   = _rev_label(rev_growth)

    score = (
        _score_pe(pe_lbl)
        + _score_debt(debt_lbl)
        + _score_revenue(rev_lbl)
        + _score_fcf(fcf_positive, has_fcf)
        + _score_roe(roe_raw)
    )
    score = max(0, min(100, score))

    # ── Summary sentence ───────────────────────────────────────────────────
    parts = []
    if pe_lbl != "UNKNOWN":
        parts.append(f"PE {pe_lbl.lower()} vs sector")
    if debt_lbl != "UNKNOWN":
        parts.append(f"{debt_lbl.lower()} debt")
    if rev_lbl != "UNKNOWN":
        parts.append(f"revenue {rev_lbl.lower()}")
    if has_fcf:
        parts.append("FCF positive" if fcf_positive else "negative FCF")
    if roe_raw > 0:
        parts.append(f"ROE {roe_raw*100:.1f}%")
    summary = "; ".join(parts) if parts else "Fundamentals data limited"

    return {
        "ticker": ticker,
        "fundamental_score": score,
        "pe_ratio": round(pe, 1) if pe > 0 else None,
        "sector_pe_benchmark": round(sector_pe, 1),
        "pe_relative": pe_lbl,
        "debt_level": debt_lbl,
        "de_ratio": round(de / 100, 2) if de >= 0 else None,
        "revenue_trend": rev_lbl,
        "revenue_growth_yoy": round(rev_growth * 100, 1) if rev_growth is not None else None,
        "fcf_positive": fcf_positive,
        "roe_pct": round(roe_raw * 100, 1),
        "promoter_holding_pct": round(promoter, 1),
        "sector": sector,
        "industry": industry,
        "summary": summary,
        "cached_at": datetime.now().isoformat(),
    }


def _empty_result(ticker: str, reason: str) -> dict:
    return {
        "ticker": ticker,
        "fundamental_score": 50,
        "pe_relative": "UNKNOWN",
        "debt_level": "UNKNOWN",
        "revenue_trend": "UNKNOWN",
        "fcf_positive": False,
        "roe_pct": 0.0,
        "promoter_holding_pct": 0.0,
        "sector": "",
        "industry": "",
        "summary": f"Fundamentals unavailable: {reason}",
        "cached_at": datetime.now().isoformat(),
    }


# ── PUBLIC API ────────────────────────────────────────────────────────────────

def get_fundamentals(ticker: str, force_refresh: bool = False) -> dict:
    """
    Return fundamentals dict for an NSE ticker.

    Keys:
      fundamental_score       — 0–100 (higher = stronger fundamentals)
      pe_ratio                — trailing PE (None if unavailable)
      sector_pe_benchmark     — median PE for this sector
      pe_relative             — "CHEAP" | "FAIR" | "EXPENSIVE" | "UNKNOWN"
      debt_level              — "LOW" | "MEDIUM" | "HIGH" | "UNKNOWN"
      de_ratio                — debt/equity decimal (1.5 = 150%)
      revenue_trend           — "GROWING" | "STABLE" | "DECLINING" | "UNKNOWN"
      revenue_growth_yoy      — % YoY (None if unavailable)
      fcf_positive            — bool
      roe_pct                 — Return on Equity %
      promoter_holding_pct    — insider/promoter holding %
      sector / industry       — from yfinance
      summary                 — one-sentence fundamental assessment
    """
    ticker = ticker.upper().strip()
    if "." not in ticker:
        ticker += ".NS"

    cache = _load_cache()
    if not force_refresh:
        entry = cache.get(ticker)
        if entry and _is_fresh(entry):
            return entry

    # During yfinance outage/rate-limit window, prefer stale cache — but cap at 7 days.
    if time.time() < _YF_BLOCK_UNTIL:
        stale = cache.get(ticker)
        if stale and _is_fresh(stale, max_age_hours=168):  # 7-day max stale grace
            return stale
        return _empty_result(ticker, "yfinance temporarily rate-limited")

    result = _fetch_fundamentals(ticker)

    cache[ticker] = result
    _save_cache(cache)

    return result


def build_fundamentals_block(result: dict) -> str:
    """
    Build a compact text block for injection into the AI debate prompt.
    Used by ai_forecast._build_fundamentals_prompt().
    """
    score = result.get("fundamental_score", 50)
    pe_lbl = result.get("pe_relative", "UNKNOWN")
    pe_val = result.get("pe_ratio")
    benchmark = result.get("sector_pe_benchmark")
    debt = result.get("debt_level", "UNKNOWN")
    de = result.get("de_ratio")
    rev = result.get("revenue_trend", "UNKNOWN")
    rev_g = result.get("revenue_growth_yoy")
    roe = result.get("roe_pct", 0)
    fcf = result.get("fcf_positive", False)
    promoter = result.get("promoter_holding_pct", 0)
    sector = result.get("sector", "")
    summary = result.get("summary", "")

    lines = [
        f"FUNDAMENTALS SCORE: {score}/100",
        f"Sector: {sector}",
    ]
    if pe_val:
        lines.append(f"PE: {pe_val:.1f}x  (sector median: {benchmark:.1f}x → {pe_lbl})")
    if de is not None:
        lines.append(f"Debt/Equity: {de:.2f}x  ({debt})")
    if rev_g is not None:
        lines.append(f"Revenue growth YoY: {rev_g:+.1f}%  ({rev})")
    else:
        lines.append(f"Revenue trend: {rev}")
    lines.append(f"ROE: {roe:.1f}%  |  FCF: {'Positive' if fcf else 'Negative/Unknown'}")
    if promoter > 0:
        lines.append(f"Promoter holding: {promoter:.1f}%")
    lines.append(f"Assessment: {summary}")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    import pprint
    ticker = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE.NS"
    print(f"Fetching fundamentals for {ticker}...")
    result = get_fundamentals(ticker, force_refresh=True)
    pprint.pprint(result)
    print("\n--- Block for LLM prompt ---")
    print(build_fundamentals_block(result))
