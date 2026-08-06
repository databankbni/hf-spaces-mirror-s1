"""
sector_pulse.py — NSE sector heatmap and rotation detector.

Tracks 10 NSE sector indices via yfinance and detects leading/lagging sectors.
Cache: in-memory dict, 5-min TTL (same pattern as news_sentiment.py).

Usage:
    from sector_pulse import get_sector_pulse
    pulse = get_sector_pulse()
    # pulse["rotation_signal"]  → "DEFENSIVE" | "CYCLICAL" | "GROWTH" | "MIXED"
    # pulse["leading_sectors"]  → ["BANK", "IT"]
    # pulse["lagging_sectors"]  → ["METAL", "REALTY"]

Run standalone to test:
    python sector_pulse.py
"""

from __future__ import annotations
import logging
import time
from datetime import datetime
from typing import Optional

import requests as _requests

# ── NSE SECTOR INDICES (Yahoo Finance tickers) ────────────────────────────────
_SECTORS = [
    {"name": "BANK",    "ticker": "^NSEBANK",    "label": "Nifty Bank"},
    {"name": "IT",      "ticker": "^CNXIT",      "label": "Nifty IT"},
    {"name": "PHARMA",  "ticker": "^CNXPHARMA",  "label": "Nifty Pharma"},
    {"name": "FMCG",    "ticker": "^CNXFMCG",    "label": "Nifty FMCG"},
    {"name": "AUTO",    "ticker": "^CNXAUTO",    "label": "Nifty Auto"},
    {"name": "METAL",   "ticker": "^CNXMETAL",   "label": "Nifty Metal"},
    {"name": "REALTY",  "ticker": "^CNXREALTY",  "label": "Nifty Realty"},
    {"name": "ENERGY",  "ticker": "^CNXENERGY",  "label": "Nifty Energy"},
    {"name": "FINANCE", "ticker": "^CNXFINANCE", "label": "Nifty Financial Services"},
    {"name": "INFRA",   "ticker": "^CNXINFRA",   "label": "Nifty Infra"},
]

# ── SECTOR ROTATION CLASSIFICATION ───────────────────────────────────────────
# Defensive: FMCG, PHARMA (outperform in risk-off environments)
# Cyclical:  METAL, ENERGY, AUTO (outperform in economic expansion)
# Growth:    IT, BANK, FINANCE (outperform in low-rate / high-growth)
_DEFENSIVE = {"FMCG", "PHARMA"}
_CYCLICAL  = {"METAL", "ENERGY", "AUTO"}
_GROWTH    = {"IT", "BANK", "FINANCE"}

# ── STOCK → SECTOR MAP (module-level so it can be inverted for sector→stocks) ──────────────────
# Large-cap constituents of the 10 tracked NSE sector indices. This is deliberately a curated
# large-cap list (the NSE constituent API is bot-blocked / unreliable from datacenter IPs), used
# both for the per-stock sector tag AND, inverted, as the candidate pool for the sector-driven
# Top Picks scan.
TICKER_SECTOR_MAP: dict[str, str] = {
    # Banking
    "HDFCBANK": "BANK", "ICICIBANK": "BANK", "KOTAKBANK": "BANK",
    "AXISBANK": "BANK", "SBIN": "BANK", "INDUSINDBK": "BANK",
    "BANKBARODA": "BANK", "IDFCFIRSTB": "BANK", "AUBANK": "BANK",
    "PNB": "BANK", "CANBK": "BANK", "FEDERALBNK": "BANK",
    # IT/Technology
    "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "HCLTECH": "IT",
    "TECHM": "IT", "LTIM": "IT", "PERSISTENT": "IT", "COFORGE": "IT",
    "MPHASIS": "IT", "OFSS": "IT",
    # Pharma
    "SUNPHARMA": "PHARMA", "DRREDDY": "PHARMA", "CIPLA": "PHARMA",
    "DIVISLAB": "PHARMA", "LUPIN": "PHARMA", "AUROPHARMA": "PHARMA",
    "BIOCON": "PHARMA", "TORNTPHARM": "PHARMA", "ZYDUSLIFE": "PHARMA",
    # FMCG
    "HINDUNILVR": "FMCG", "NESTLEIND": "FMCG", "BRITANNIA": "FMCG",
    "DABUR": "FMCG", "MARICO": "FMCG", "GODREJCP": "FMCG",
    "ITC": "FMCG", "TATACONSUM": "FMCG", "COLPAL": "FMCG",
    # Auto
    "MARUTI": "AUTO", "TATAMOTORS": "AUTO", "M&M": "AUTO",
    "BAJAJ-AUTO": "AUTO", "HEROMOTOCO": "AUTO", "EICHERMOT": "AUTO",
    "TVSMOTOR": "AUTO", "ASHOKLEY": "AUTO", "BOSCHLTD": "AUTO",
    # Metal
    "TATASTEEL": "METAL", "JSWSTEEL": "METAL", "HINDALCO": "METAL",
    "VEDL": "METAL", "COALINDIA": "METAL", "NMDC": "METAL",
    "JINDALSTEL": "METAL", "SAIL": "METAL", "HINDZINC": "METAL",
    # Energy
    "RELIANCE": "ENERGY", "ONGC": "ENERGY", "BPCL": "ENERGY",
    "IOC": "ENERGY", "NTPC": "ENERGY", "POWERGRID": "ENERGY",
    "GAIL": "ENERGY", "TATAPOWER": "ENERGY", "ADANIGREEN": "ENERGY",
    # Realty
    "DLF": "REALTY", "GODREJPROP": "REALTY", "LODHA": "REALTY",
    "OBEROIRLTY": "REALTY", "PHOENIXLTD": "REALTY", "PRESTIGE": "REALTY",
    # Finance (NBFCs)
    "BAJFINANCE": "FINANCE", "BAJAJFINSV": "FINANCE", "CHOLAFIN": "FINANCE",
    "MUTHOOTFIN": "FINANCE", "SHRIRAMFIN": "FINANCE", "SBICARD": "FINANCE",
    "HDFCLIFE": "FINANCE", "SBILIFE": "FINANCE", "ICICIPRULI": "FINANCE",
    # Infra
    "LT": "INFRA", "ADANIPORTS": "INFRA", "APOLLOHOSP": "INFRA",
    "SIEMENS": "INFRA", "ABB": "INFRA", "GMRINFRA": "INFRA",
}

# ── NSE OFFICIAL SECTOR SOURCE ───────────────────────────────────────────────
# Maps NSE index names (from /api/allIndices) to our internal sector keys.
_NSE_INDEX_TO_SECTOR = {
    "NIFTY BANK":               "BANK",
    "NIFTY IT":                 "IT",
    "NIFTY PHARMA":             "PHARMA",
    "NIFTY FMCG":               "FMCG",
    "NIFTY AUTO":               "AUTO",
    "NIFTY METAL":              "METAL",
    "NIFTY REALTY":             "REALTY",
    "NIFTY OIL & GAS":          "ENERGY",
    "NIFTY ENERGY":             "ENERGY",
    "NIFTY FINANCIAL SERVICES": "FINANCE",
    "NIFTY INFRASTRUCTURE":     "INFRA",
    "NIFTY INFRA":              "INFRA",
}

_NSE_SESSION = _requests.Session()
_NSE_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Referer":    "https://www.nseindia.com/",
    "Accept":     "application/json, text/plain, */*",
    "Accept-Language": "en-IN,en;q=0.9",
})


def _nse_warmup_sector() -> None:
    try:
        _NSE_SESSION.get("https://www.nseindia.com", timeout=8)
    except Exception:
        pass


def _fetch_nse_live_1d() -> dict[str, dict]:
    """Fetch live 1D % change + current price for each sector from NSE allIndices.

    Returns a dict keyed by sector name (e.g. "BANK") with keys:
      change_1d_pct, current

    Returns {} on any failure — caller falls back to yfinance.
    """
    try:
        _nse_warmup_sector()
        r = _NSE_SESSION.get(
            "https://www.nseindia.com/api/allIndices",
            timeout=10,
        )
        if r.status_code != 200:
            return {}
        rows = r.json().get("data", [])
        result: dict[str, dict] = {}
        for row in rows:
            index_name = row.get("indexSymbol", "").strip().upper()
            sector = _NSE_INDEX_TO_SECTOR.get(index_name)
            if not sector:
                continue
            pct     = row.get("percentChange")
            current = row.get("last") or row.get("current")
            if pct is not None and current is not None:
                result[sector] = {
                    "change_1d_pct": round(float(pct), 2),
                    "current":       round(float(current), 2),
                }
        return result
    except Exception as exc:
        logging.debug("sector_pulse: NSE live fetch failed: %s", exc)
        return {}


# ── CACHE ─────────────────────────────────────────────────────────────────────
_CACHE: dict = {}
_CACHE_TTL = 300  # 5 minutes


def _is_fresh(entry: dict) -> bool:
    return time.time() - entry.get("_ts", 0) < _CACHE_TTL


# ── ROTATION LOGIC ────────────────────────────────────────────────────────────

def _classify_rotation(leading: list[str]) -> str:
    """
    Determine rotation signal from which sectors are leading.
    We count how many of the top sectors fall in each category bucket.
    """
    if not leading:
        return "MIXED"

    n_def = sum(1 for s in leading if s in _DEFENSIVE)
    n_cyc = sum(1 for s in leading if s in _CYCLICAL)
    n_grw = sum(1 for s in leading if s in _GROWTH)

    dominant = max(n_def, n_cyc, n_grw)
    if dominant == 0:
        return "MIXED"

    if n_def == dominant and n_def >= 2:
        return "DEFENSIVE"
    if n_cyc == dominant and n_cyc >= 2:
        return "CYCLICAL"
    if n_grw == dominant and n_grw >= 2:
        return "GROWTH"
    return "MIXED"


def _momentum_label(chg_5d: float) -> str:
    if chg_5d > 2.0:
        return "LEADING"
    if chg_5d > 0.5:
        return "RISING"
    if chg_5d > -0.5:
        return "FLAT"
    if chg_5d > -2.0:
        return "FALLING"
    return "LAGGING"


# ── DATA FETCH ────────────────────────────────────────────────────────────────

def _fetch_sector_pulse() -> dict:
    try:
        import yfinance as yf
    except ImportError:
        return _empty_result("yfinance not installed")

    # Try NSE official API for live 1D data first; blend into yfinance historical.
    nse_live = _fetch_nse_live_1d()

    tickers = [s["ticker"] for s in _SECTORS]
    sector_data = []
    failed = []

    try:
        import pandas as pd
        raw = yf.download(tickers, period="35d", progress=False, auto_adjust=True)

        close = raw["Close"]
        if isinstance(close, pd.Series):
            close = close.to_frame()

        for s in _SECTORS:
            ytk = s["ticker"]
            if ytk not in close.columns:
                failed.append(s["name"])
                continue
            col = close[ytk].dropna()
            if len(col) < 2:
                failed.append(s["name"])
                continue

            yf_latest = float(col.iloc[-1])

            def _pct_ago(n: int) -> Optional[float]:
                if len(col) > n:
                    past = float(col.iloc[-n - 1])
                    if past > 0:
                        return round((yf_latest / past - 1) * 100, 2)
                return None

            chg_5d = _pct_ago(5) or 0.0
            chg_1m = _pct_ago(21) or 0.0

            # Prefer NSE live data for 1D and current price when available.
            nse = nse_live.get(s["name"], {})
            chg_1d  = nse.get("change_1d_pct", _pct_ago(1) or 0.0)
            current = nse.get("current", yf_latest)

            sector_data.append({
                "name":          s["name"],
                "label":         s["label"],
                "current":       round(current, 2),
                "change_1d_pct": chg_1d,
                "change_5d_pct": chg_5d,
                "change_1m_pct": chg_1m,
                "momentum":      _momentum_label(chg_5d),
                "source":        "nse+yf" if nse else "yf",
            })
    except Exception as e:
        logging.warning("sector_pulse: batch download failed: %s", e)
        # Try one-by-one fallback
        for s in _SECTORS:
            try:
                import pandas as pd
                df = yf.download(s["ticker"], period="35d", progress=False, auto_adjust=True)
                col = df["Close"].dropna() if not df.empty else pd.Series(dtype=float)
                if len(col) < 2:
                    failed.append(s["name"])
                    continue
                yf_latest = float(col.iloc[-1])

                def _pct(n: int) -> float:
                    if len(col) > n:
                        past = float(col.iloc[-n - 1])
                        return round((yf_latest / past - 1) * 100, 2) if past > 0 else 0.0
                    return 0.0

                nse = nse_live.get(s["name"], {})
                chg_1d  = nse.get("change_1d_pct", _pct(1))
                current = nse.get("current", yf_latest)

                sector_data.append({
                    "name": s["name"], "label": s["label"],
                    "current": round(current, 2),
                    "change_1d_pct": chg_1d, "change_5d_pct": _pct(5), "change_1m_pct": _pct(21),
                    "momentum": _momentum_label(_pct(5)),
                    "source": "nse+yf" if nse else "yf",
                })
            except Exception:
                failed.append(s["name"])

    if not sector_data:
        return _empty_result(f"all sector downloads failed ({', '.join(failed)})")

    # Sort by 5D return (best first)
    sector_data.sort(key=lambda x: x["change_5d_pct"], reverse=True)

    leading  = [s["name"] for s in sector_data[:3]]
    lagging  = [s["name"] for s in sector_data[-3:]]
    breadth  = sum(1 for s in sector_data if s["change_5d_pct"] > 0)
    rotation = _classify_rotation(leading)

    return {
        "sectors": sector_data,
        "rotation_signal": rotation,
        "leading_sectors": leading,
        "lagging_sectors": lagging,
        "breadth_score": breadth,  # 0–10 sectors with positive 5D return
        "fetched_at": datetime.now().isoformat(),
        "_failed": failed,
        "_ts": time.time(),
    }


def _empty_result(reason: str) -> dict:
    logging.warning("sector_pulse: returning empty result (%s)", reason)
    return {
        "sectors": [],
        "rotation_signal": "MIXED",
        "leading_sectors": [],
        "lagging_sectors": [],
        "breadth_score": 0,
        "fetched_at": datetime.now().isoformat(),
        "_error": reason,
        "_ts": time.time(),
    }


# ── PUBLIC API ────────────────────────────────────────────────────────────────

def get_sector_pulse(force_refresh: bool = False) -> dict:
    """
    Return NSE sector heatmap dict.

    Keys:
      sectors          — list of dicts: {name, label, current, change_1d/5d/1m_pct, momentum}
      rotation_signal  — "DEFENSIVE" | "CYCLICAL" | "GROWTH" | "MIXED"
      leading_sectors  — top-3 sector names by 5D return
      lagging_sectors  — bottom-3 sector names by 5D return
      breadth_score    — 0–10: number of sectors with positive 5D return
      fetched_at       — ISO timestamp
    """
    global _CACHE
    if not force_refresh and _is_fresh(_CACHE):
        return _CACHE

    result = _fetch_sector_pulse()
    _CACHE = result
    return result


def get_sector_for_ticker(ticker: str, pulse: dict | None = None) -> str | None:
    """
    Map an NSE ticker to its sector name (BANK, IT, etc.)
    Returns None if the ticker's sector is not in the NSE sector index map.
    Used by predictor_core.py for the sector-relative-strength bonus.
    """
    base = ticker.replace(".NS", "").replace(".BO", "").upper()
    return TICKER_SECTOR_MAP.get(base)


def get_sector_constituents() -> dict[str, list[str]]:
    """Invert TICKER_SECTOR_MAP → {sector: [TICKER.NS, ...]}. The candidate pool for the
    sector-driven Top Picks scan (large-cap constituents of each tracked NSE sector index)."""
    out: dict[str, list[str]] = {}
    for base, sector in TICKER_SECTOR_MAP.items():
        out.setdefault(sector, []).append(f"{base}.NS")
    return out


# ── SECTOR VOLATILITY (avg daily range of the sector index) ───────────────────────────────────
_VOL_CACHE: dict = {}
_VOL_TTL = 1800  # 30-min cache


def get_sector_volatility(force_refresh: bool = False, window: int = 14) -> list[dict]:
    """Rank all tracked NSE sectors by realized VOLATILITY (not direction).

    Volatility = mean intraday range as a % of close, (High-Low)/Close×100, over the last
    `window` daily bars of each sector index. This is the "most violent sectors" signal used
    to drive the Top Picks candidate pool. Returns a list of
    {name, label, volatility_pct, atr_pct, change_5d_pct} sorted by volatility_pct DESC.
    Cached for 30 min; degrades to an empty list if all downloads fail.
    """
    global _VOL_CACHE
    now = time.time()
    if (not force_refresh and _VOL_CACHE.get("data") is not None
            and now - _VOL_CACHE.get("_ts", 0) < _VOL_TTL):
        return _VOL_CACHE["data"]

    rows: list[dict] = []
    try:
        import yfinance as yf
        import pandas as pd
        tickers = [s["ticker"] for s in _SECTORS]
        df = yf.download(tickers, period="35d", progress=False, auto_adjust=True, group_by="ticker")
        for s in _SECTORS:
            try:
                sub = df[s["ticker"]] if s["ticker"] in df.columns.get_level_values(0) else None
                if sub is None or sub.empty:
                    continue
                hi = sub["High"].dropna().tail(window)
                lo = sub["Low"].dropna().tail(window)
                cl = sub["Close"].dropna().tail(window)
                n = min(len(hi), len(lo), len(cl))
                if n < 3:
                    continue
                rng_pct = ((hi.iloc[-n:].values - lo.iloc[-n:].values) / cl.iloc[-n:].values) * 100.0
                vol_pct = float(pd.Series(rng_pct).mean())
                chg_5d = float((cl.iloc[-1] / cl.iloc[-6] - 1) * 100) if len(cl) > 6 else 0.0
                rows.append({
                    "name": s["name"], "label": s["label"],
                    "volatility_pct": round(vol_pct, 2),
                    "atr_pct": round(vol_pct, 2),  # alias — index range ≈ ATR% for an index
                    "change_5d_pct": round(chg_5d, 2),
                })
            except Exception:
                continue
    except Exception as e:
        logging.warning("sector_pulse: volatility fetch failed: %s", e)

    rows.sort(key=lambda r: r["volatility_pct"], reverse=True)
    _VOL_CACHE = {"data": rows, "_ts": now}
    return rows


def format_pulse_summary(pulse: dict) -> str:
    """One-line summary of sector pulse for LLM prompts."""
    leading = ", ".join(pulse.get("leading_sectors", []))
    lagging = ", ".join(pulse.get("lagging_sectors", []))
    rotation = pulse.get("rotation_signal", "MIXED")
    breadth = pulse.get("breadth_score", 0)
    return (
        f"NSE Sector Rotation: {rotation} | Breadth: {breadth}/10 sectors advancing "
        f"| Leading: {leading or 'N/A'} | Lagging: {lagging or 'N/A'}"
    )


if __name__ == "__main__":
    import pprint
    print("Fetching NSE sector pulse...")
    pulse = get_sector_pulse(force_refresh=True)
    print(f"\n{format_pulse_summary(pulse)}\n")
    for s in pulse["sectors"]:
        bar = "█" * max(0, int((s["change_5d_pct"] + 5) / 0.5))
        print(f"  {s['name']:<8} {s['change_5d_pct']:>+6.2f}% (5D)  {s['momentum']:<8}  {bar}")
    if pulse.get("_failed"):
        print(f"\n  [skipped: {', '.join(pulse['_failed'])}]")
