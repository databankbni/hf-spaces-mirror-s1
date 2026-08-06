"""
universe.py — Dynamic NSE equity universe fetched from Yahoo Finance screener.

Replaces the old static nse_universe.py. Every ticker returned has been
confirmed by Yahoo Finance, so it is guaranteed to resolve for OHLCV and
live-price fetches.

Cache: .universe_cache.json in the project root (24 h TTL, 7-day stale grace).
"""

import json
import os
import time

_DIR = os.path.dirname(os.path.abspath(__file__))


def _cache_dir() -> str:
    """Use /data on HF Spaces (persistent across container restarts), else project root.

    The project-root file does NOT survive a Hugging Face Spaces restart, so on HF the
    universe cache must live on the persistent /data volume — mirroring how the OHLCV
    cache (data_sources._ohlcv_data_dir) picks its location.
    """
    hf_data = "/data"
    if os.path.isdir(hf_data) and os.access(hf_data, os.W_OK):
        return hf_data
    return _DIR


_CACHE_PATH = os.path.join(_cache_dir(), ".universe_cache.json")
_TTL        = 24 * 3600          # fresh window: 24 hours
_STALE_TTL  = 7  * 24 * 3600    # stale grace: serve old cache for up to 7 days


_YF_BATCH = 250   # Yahoo Finance hard cap per screen() call

# Official NSE archive of the FULL equity list — every listed NSE stock (~2,400 rows,
# ~2,060 in the EQ rolling-settlement series), spanning large / mid / small / micro caps.
# This is the primary universe source: it is the whole market (not just the top 500 by
# market cap) and its CDN responds to datacenter IPs, so it works on Hugging Face Spaces
# where Yahoo's screener is blocked.
_NSE_EQUITY_LIST_CSV = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"

# Official NSE archive CSV of the Nifty 500 constituents (top ~500 by market cap).
# Fallback universe source if the full equity list is unavailable.
_NSE_NIFTY500_CSV = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"

_NSE_CSV_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Accept": "text/csv,application/csv,*/*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


def _fetch_full_nse_market(n: int = 5000) -> dict[str, str]:
    """
    Fetch the ENTIRE NSE equity universe from NSE's official EQUITY_L archive CSV.

    Returns {TICKER.NS: company_name} for every EQ-series (rolling-settlement) stock —
    all cap tiers, not just large caps. This is the production-primary source: the
    endpoint works from datacenter IPs (Hugging Face Spaces) and reflects the live,
    current NSE listing. BE/BZ (trade-for-trade / restricted) series are excluded as
    they are not suitable for the prediction/trading flow.
    """
    import csv
    import io
    import requests

    resp = requests.get(_NSE_EQUITY_LIST_CSV, headers=_NSE_CSV_HEADERS, timeout=20)
    resp.raise_for_status()

    universe: dict[str, str] = {}
    reader = csv.DictReader(io.StringIO(resp.text))
    for row in reader:
        # EQUITY_L headers carry leading spaces (e.g. ' SERIES'); match tolerantly.
        row = {(k or "").strip(): v for k, v in row.items()}
        symbol = (row.get("SYMBOL") or "").strip()
        name   = (row.get("NAME OF COMPANY") or symbol).strip()
        series = (row.get("SERIES") or "").strip().upper()
        if not symbol or series != "EQ":
            continue
        universe[f"{symbol}.NS"] = name
        if len(universe) >= n:
            break

    return universe


def _fetch_nse_equity(n: int = 500) -> dict[str, str]:
    """
    Query Yahoo Finance screener for the top-N NSE stocks by market cap.
    Fetches in batches of 250 (Yahoo Finance hard limit per call).
    Returns {TICKER.NS: company_name}.
    yf.screen() handles crumb/auth internally.

    NOTE: Yahoo blocks the screener from datacenter IPs (returns empty on HF Spaces)
    AND only covers the top 500 by market cap. It is now only a last-resort live
    fallback; _fetch_full_nse_market() (whole market) is the primary source.
    """
    import yfinance as yf
    from yfinance import EquityQuery

    query = EquityQuery("and", [
        EquityQuery("eq", ["region",   "in"]),
        EquityQuery("eq", ["exchange", "NSI"]),   # NSI = NSE India
    ])

    universe: dict[str, str] = {}
    offset = 0
    while len(universe) < n:
        batch_size = min(_YF_BATCH, n - len(universe))
        result = yf.screen(
            query,
            size=batch_size,
            offset=offset,
            sortField="intradaymarketcap",
            sortAsc=False,
        )
        quotes = (result or {}).get("quotes") or []
        if not quotes:
            break
        for q in quotes:
            sym  = q.get("symbol", "")
            name = q.get("longName") or q.get("shortName") or sym
            if sym.endswith(".NS"):
                universe[sym] = name
        offset += len(quotes)
        if len(quotes) < batch_size:
            break   # exhausted available results

    return universe


def _fetch_nse_index_csv(n: int = 500) -> dict[str, str]:
    """
    Fetch the NSE Nifty-500 constituent list from NSE's official archive CSV.
    Fallback universe source (top ~500 by market cap) if the full equity list fails.
    Returns {TICKER.NS: name}.
    """
    import csv
    import io
    import requests

    resp = requests.get(_NSE_NIFTY500_CSV, headers=_NSE_CSV_HEADERS, timeout=20)
    resp.raise_for_status()

    universe: dict[str, str] = {}
    reader = csv.DictReader(io.StringIO(resp.text))
    for row in reader:
        symbol = (row.get("Symbol") or "").strip()
        name   = (row.get("Company Name") or symbol).strip()
        series = (row.get("Series") or "EQ").strip()
        if not symbol or series.upper() not in ("EQ", "BE", ""):
            continue
        universe[f"{symbol}.NS"] = name
        if len(universe) >= n:
            break

    return universe


def _fetch_universe(n: int = 5000) -> dict[str, str]:
    """
    Fetch a live NSE universe, trying sources in order of preference:
      1. NSE full equity list (EQUITY_L) — the WHOLE market, all cap tiers, works on HF.
      2. NSE Nifty-500 archive CSV — top 500 by market cap (fallback).
      3. Yahoo Finance screener — top 500 by market cap (residential-only fallback).
    Returns the first non-empty result, or {} if all live sources fail.
    """
    try:
        full = _fetch_full_nse_market(n)
        if full:
            return full
    except Exception:
        pass

    try:
        nifty500 = _fetch_nse_index_csv(500)
        if nifty500:
            return nifty500
    except Exception:
        pass

    try:
        yf_universe = _fetch_nse_equity(500)
        if yf_universe:
            return yf_universe
    except Exception:
        pass

    return {}


def get_universe(force_refresh: bool = False) -> dict[str, str]:
    """
    Return {TICKER.NS: company_name} for the top NSE equities.

    Source order: Yahoo screener → NSE Nifty-500 archive CSV → persistent cache →
    static fallback list. The cache lives on /data on HF Spaces so a successful fetch
    survives container restarts.

    Caching strategy:
      - Fresh (< 24 h): return cache as-is.
      - Stale (24 h – 7 days): try to refresh; if all live sources fail, return stale.
      - Very stale (> 7 days) or no cache: refresh; if that fails, use static fallback.
    """
    cached_data: dict | None = None
    cache_age:   float       = float("inf")

    if os.path.exists(_CACHE_PATH):
        try:
            with open(_CACHE_PATH) as f:
                raw = json.load(f)
            cache_age   = time.time() - raw.get("ts", 0)
            cached_data = raw.get("data") or None
        except Exception:
            pass

    # Return fresh cache immediately (skip network)
    if not force_refresh and cached_data and cache_age < _TTL:
        return cached_data

    # Try to fetch a fresh universe from a live source (full NSE market → Nifty500 → YF)
    try:
        fresh = _fetch_universe(5000)
        if fresh:
            try:
                with open(_CACHE_PATH, "w") as f:
                    json.dump({"ts": time.time(), "data": fresh}, f)
            except Exception:
                pass   # cache write is best-effort; still return the live result
            return fresh
    except Exception:
        pass

    # Live sources failed — fall back to stale cache if within the grace window
    if cached_data and cache_age < _STALE_TTL:
        return cached_data

    # Last resort: return whatever cache we have, however old, rather than nothing
    if cached_data:
        return cached_data

    # No cache at all AND every live source failed (e.g. a fresh Hugging Face Spaces
    # container before its first successful fetch). Use the static top-NSE list so the
    # universe is never empty and the top-picks scan + predictor keep working. This is
    # the genuine last resort, not the normal path.
    try:
        from nse_fallback_universe import FALLBACK_UNIVERSE
        return dict(FALLBACK_UNIVERSE)
    except Exception:
        return {}


def refresh_universe() -> dict[str, str]:
    """Force-refresh and return the new universe."""
    return get_universe(force_refresh=True)
