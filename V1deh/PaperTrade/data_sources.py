"""
data_sources.py — Multi-source OHLCV + market data fetcher (free sources only).

Priority order (OHLCV / live price):
  1. NSE Official   (free, no key, .NS tickers — circuit-breaker if blocked)
  2. BSE Official   (free, no key, .BO tickers — circuit-breaker if blocked)
  3. jugaad-data    (free, no key — wraps NSE API with built-in caching)
  4. openchart      (free, no key — NSE charting endpoint, different from historical API)
  5. Stooq          (free, no key, universal)
  6. Yahoo Finance  (last resort — 15-min delayed, intermittent failures for NSE)

Market data (Nifty/VIX): NSE unofficial → Yahoo Finance.

Public API:
  fetch_ohlcv(ticker_ns, period="1y")  → (sc, sh, sl, sv) DataFrames  or raises ValueError
  fetch_live_price(ticker_ns)          → float or None
  fetch_market_data(period_days=365)   → (nifty_c, vix_c) Series
"""

from __future__ import annotations
import concurrent.futures
import logging
import os, pickle, sqlite3, threading, time, warnings
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import requests
from requests.adapters import HTTPAdapter

warnings.filterwarnings("ignore")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Accept": "application/json",
})

# The app runs many parallel NSE/BSE requests; default urllib3 pool size (10)
# gets saturated and emits "Connection pool is full" warnings.
_ADAPTER = HTTPAdapter(pool_connections=64, pool_maxsize=64, max_retries=0)
_SESSION.mount("https://", _ADAPTER)
_SESSION.mount("http://", _ADAPTER)

_TIMEOUT = 8  # seconds per HTTP call — keep short so 6-source fallback chain completes fast


# ── Persistent OHLCV SQLite cache ────────────────────────────────────────────
# Survives Flask restarts and eliminates redundant network fetches.
# Two-layer caching: in-memory 5-min TTL (predictor_core) → SQLite forever.
# Fresh = last bar is within 1 trading day of today. Stale data is served
# instead of raising ValueError so network outages don't break predictions.
# The OHLCV cache lives in its OWN file (ohlcv_cache.db). It previously shared
# paper_trading.db, which put large pickled BLOBs + heavy concurrent cache writes on the
# trade DB and — combined with the non-atomic HF backup that never checkpointed the WAL —
# was a primary cause of "database disk image is malformed". Isolating the regenerable price
# cache from the small must-survive trade DB removes that corruption vector.

def _ohlcv_data_dir() -> str:
    """Use /data on HF Spaces (persistent across rebuilds), else project root."""
    hf_data = "/data"
    if os.path.isdir(hf_data) and os.access(hf_data, os.W_OK):
        return hf_data
    return os.path.dirname(os.path.abspath(__file__))

_OHLCV_DB_PATH = os.path.join(_ohlcv_data_dir(), "ohlcv_cache.db")

# Per-ticker mutex: prevents thundering herd where 4 TF threads all see cache-miss
# for the same stock and hammer Yahoo Finance concurrently (causing throttling/hangs).
# Only one thread fetches per ticker; others wait and pick up the cached result.
_OHLCV_TICKER_LOCKS: dict = {}
_OHLCV_TICKER_LOCKS_LOCK = threading.Lock()

# Negative result cache: if all sources fail for (ticker, period), mark it so
# subsequent TF threads that are waiting on the per-ticker lock skip the full
# 73s fallback chain and return immediately. TTL=60s (retry after 1 min).
_OHLCV_FAIL_UNTIL: dict = {}  # (ticker, period) -> unix timestamp
_OHLCV_FAIL_LOCK = threading.Lock()

# Global yfinance semaphore: Yahoo Finance throttles concurrent requests from the same
# IP. Limit to 2 simultaneous yf.download calls to avoid triggering rate limits while
# still allowing some parallelism across different stocks.
_YF_SEMAPHORE = threading.Semaphore(2)

# Write serialization lock for ohlcv_cache.db. SQLite WAL allows only one writer at a
# time — under high concurrency (10+ top5 workers + 9+ watchlist workers) threads queue
# on the internal write lock and can exceed busy_timeout, causing silent write failures.
# This Python-side lock collapses all writers to serial BEFORE touching SQLite, keeping
# the SQLite queue depth at 1 and making busy_timeout irrelevant.
_OHLCV_WRITE_LOCK = threading.Lock()


def _ohlcv_mark_failed(ticker: str, period: str, ttl: float = 60.0) -> None:
    with _OHLCV_FAIL_LOCK:
        _OHLCV_FAIL_UNTIL[(ticker, period)] = time.time() + ttl


def _ohlcv_is_failed(ticker: str, period: str) -> bool:
    with _OHLCV_FAIL_LOCK:
        return _OHLCV_FAIL_UNTIL.get((ticker, period), 0) > time.time()


def _get_ticker_lock(ticker: str) -> threading.Lock:
    with _OHLCV_TICKER_LOCKS_LOCK:
        if ticker not in _OHLCV_TICKER_LOCKS:
            _OHLCV_TICKER_LOCKS[ticker] = threading.Lock()
        return _OHLCV_TICKER_LOCKS[ticker]


def _init_ohlcv_db() -> None:
    """One-time DDL: create ohlcv_cache table and set WAL mode. Called once at module load."""
    conn = sqlite3.connect(_OHLCV_DB_PATH, check_same_thread=False, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS ohlcv_cache (
        ticker   TEXT NOT NULL,
        period   TEXT NOT NULL,
        data     BLOB NOT NULL,
        saved_at REAL NOT NULL,
        PRIMARY KEY (ticker, period)
    )""")
    conn.commit()
    conn.close()


def _ohlcv_db():
    """Open a connection to ohlcv_cache.db with WAL settings. DDL is applied once at startup."""
    conn = sqlite3.connect(_OHLCV_DB_PATH, check_same_thread=False, timeout=10)
    # PRAGMAs are connection-level — must be set on every new connection.
    # CREATE TABLE is NOT re-run here: running DDL on every read call acquired a write lock
    # even during reads, negating WAL's read/write non-blocking property.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


# Apply DDL once at module load so _ohlcv_db() can stay DDL-free.
try:
    _init_ohlcv_db()
except Exception as _e:
    logging.warning("ohlcv_cache.db init failed (will retry on first write): %s", _e)


def _dedupe_cols(df):
    """Collapse duplicate ticker columns into one.

    Some historical cache rows were persisted with the ticker column present twice
    (e.g. a sparse 17-row column alongside the full series). `df[ticker]` then returns
    a 2-column DataFrame and `.dropna()` intersects them, silently shrinking the history
    to the sparse column's coverage — which surfaced downstream as a false
    "insufficient history" (ML n/a). Here we merge duplicates row-wise, keeping the
    first non-null value per row so the fuller series wins.
    """
    if df is None or getattr(df, "columns", None) is None:
        return df
    try:
        if not df.columns.duplicated().any():
            return df
        merged = {}
        for name in pd.unique(df.columns):
            sub = df.loc[:, df.columns == name]
            merged[name] = sub.bfill(axis=1).iloc[:, 0] if sub.shape[1] > 1 else sub.iloc[:, 0]
        out = pd.DataFrame(merged, index=df.index)
        out.index.name = df.index.name
        return out
    except Exception:
        return df


def _load_sql_cache(ticker_ns: str, period: str):
    """Load OHLCV from SQLite. Returns (sc, sh, sl, sv, is_fresh) or None."""
    try:
        conn = _ohlcv_db()
        row = conn.execute(
            "SELECT data FROM ohlcv_cache WHERE ticker=? AND period=?",
            (ticker_ns, period),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        sc, sh, sl, sv = pickle.loads(row[0])
        # Repair any legacy rows that were cached with duplicate ticker columns.
        sc, sh, sl, sv = _dedupe_cols(sc), _dedupe_cols(sh), _dedupe_cols(sl), _dedupe_cols(sv)
        is_fresh = _is_data_fresh(sc, ticker_ns)
        return sc, sh, sl, sv, is_fresh
    except Exception:
        return None   # treat as cache miss; caller falls through to live fetch


def _save_sql_cache(ticker_ns: str, period: str, sc, sh, sl, sv) -> None:
    """Persist OHLCV to SQLite. Errors are logged but never propagated to the caller."""
    with _OHLCV_WRITE_LOCK:
        try:
            conn = _ohlcv_db()
            # Never persist duplicate ticker columns — they corrupt downstream .dropna().
            sc, sh, sl, sv = _dedupe_cols(sc), _dedupe_cols(sh), _dedupe_cols(sl), _dedupe_cols(sv)
            blob = pickle.dumps((sc, sh, sl, sv))
            conn.execute(
                "INSERT OR REPLACE INTO ohlcv_cache VALUES (?,?,?,?)",
                (ticker_ns, period, blob, time.time()),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logging.warning("_save_sql_cache failed for %s/%s: %s", ticker_ns, period, e)


def cached_tickers(period: str = "1y") -> set[str]:
    """Return the set of tickers that have an OHLCV cache row for `period`.

    Cheap single query (no pickle load) — used to order a large scan cache-first so
    already-warmed stocks are processed instantly and cold fetches are deferred.
    """
    try:
        conn = _ohlcv_db()
        rows = conn.execute(
            "SELECT ticker FROM ohlcv_cache WHERE period=?", (period,)
        ).fetchall()
        conn.close()
        return {r[0] for r in rows}
    except Exception:
        return set()



# ── Ticker format helpers ─────────────────────────────────────────────────────

def _period_to_days(period: str) -> int:
    """Convert yfinance-style period string to integer days."""
    mapping = {"1d": 1, "5d": 5, "1mo": 30, "3mo": 90,
               "6mo": 180, "1y": 365, "2y": 730, "5y": 1825}
    return mapping.get(period.lower(), 365)


def _build_df(dates, opens, highs, lows, closes, volumes, ticker: str):
    """Assemble the four OHLCV DataFrames expected by predictor_core."""
    idx = pd.to_datetime(dates)
    sc = pd.DataFrame({ticker: closes}, index=idx, dtype=float)
    sh = pd.DataFrame({ticker: highs},  index=idx, dtype=float)
    sl = pd.DataFrame({ticker: lows},   index=idx, dtype=float)
    sv = pd.DataFrame({ticker: volumes}, index=idx, dtype=float)
    for df in (sc, sh, sl, sv):
        df.sort_index(inplace=True)
        df.index.name = "Date"
    return sc, sh, sl, sv


# ── Free-source helpers ──────────────────────────────────────────────────────

_NSE_HEADERS = {
    "Referer": "https://www.nseindia.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-IN,en;q=0.9",
}
_BSE_HEADERS = {
    "Referer": "https://www.bseindia.com/",
    "Accept": "application/json",
}
_BSE_CODE_CACHE: dict = {}
_NSE_HIST_BLOCK_UNTIL: float = 0.0   # circuit-breaker: epoch seconds; 0 = open
_BSE_BLOCK_UNTIL:      float = 0.0   # circuit-breaker: epoch seconds; 0 = open
_YF_BLOCK_UNTIL:       float = 0.0   # yfinance crumb/auth breaker
_CB_COOLDOWN = 300  # 5-minute cooldown before retrying blocked sources
_YF_COOLDOWN = 900  # 15-minute cooldown for repeated yfinance crumb errors


def _is_today_ist(ts: pd.Timestamp) -> bool:
    """Return True when timestamp falls on today's date in Asia/Kolkata."""
    try:
        now_ist = pd.Timestamp.now(tz="Asia/Kolkata")
        if ts.tzinfo is None:
            # Treat naive timestamps as exchange-local date for compatibility.
            return ts.date() == now_ist.date()
        return ts.tz_convert("Asia/Kolkata").date() == now_ist.date()
    except Exception:
        return False


def _nse_blocked() -> bool:
    return time.time() < _NSE_HIST_BLOCK_UNTIL


def _bse_blocked() -> bool:
    return time.time() < _BSE_BLOCK_UNTIL


def _block_nse():
    global _NSE_HIST_BLOCK_UNTIL
    _NSE_HIST_BLOCK_UNTIL = time.time() + _CB_COOLDOWN


def _block_bse():
    global _BSE_BLOCK_UNTIL
    _BSE_BLOCK_UNTIL = time.time() + _CB_COOLDOWN


def _yf_blocked() -> bool:
    return time.time() < _YF_BLOCK_UNTIL


def _block_yf(cooldown: int = _YF_COOLDOWN):
    global _YF_BLOCK_UNTIL
    _YF_BLOCK_UNTIL = time.time() + cooldown


def _is_yf_crumb_error(err: Exception | str) -> bool:
    txt = str(err).lower()
    return (
        "invalid crumb" in txt
        or "unauthorized" in txt
        or "401" in txt
    )


def _nse_warmup():
    try:
        _SESSION.get("https://www.nseindia.com", timeout=_TIMEOUT)
    except Exception:
        pass


def _to_nse(ticker_ns: str) -> str:
    """RELIANCE.NS → RELIANCE"""
    return ticker_ns.replace(".NS", "").replace(".BO", "")


def _to_stooq(ticker_ns: str) -> str:
    """RELIANCE.NS → reliance.in"""
    return ticker_ns.replace(".NS", "").replace(".BO", "").lower() + ".in"


def _resolve_bse_code(symbol: str) -> Optional[str]:
    """Resolve BSE scripcode via search; result cached in _BSE_CODE_CACHE."""
    if _bse_blocked():
        return None
    if symbol in _BSE_CODE_CACHE:
        return _BSE_CODE_CACHE[symbol]
    try:
        r = _SESSION.get(
            "https://api.bseindia.com/Msource/1D/getQouteSearch.aspx",
            params={"Type": "EQ", "text": symbol, "flag": "site"},
            headers=_BSE_HEADERS, timeout=_TIMEOUT,
        )
        if r.status_code in (403, 503):
            _block_bse()
            return None
        data = r.json()
        items = data if isinstance(data, list) else data.get("Table", [])
        for item in items:
            code = (item.get("scripcode") or item.get("SCRIP_CD") or
                    item.get("scrip_cd") or item.get("ScripCode"))
            if code:
                _BSE_CODE_CACHE[symbol] = str(code)
                return str(code)
    except Exception:
        pass
    return None


# ── Source 1: NSE Official (REMOVED — /api/historical/cm/equity is bot-blocked, 403) ──
# The NSE direct OHLCV API returns HTTP 403 "Access Denied" (Akamai bot protection)
# even from residential IPs, so it was removed from the fetch chain. Use yfinance
# (fetch_ohlcv_yfinance) for NSE OHLCV — it works everywhere incl. HF datacenter IPs.


# ── Source 2: BSE Official (free, .BO only, close-only OHLCV) ────────────────

def fetch_ohlcv_bse_official(ticker_ns: str, period: str = "1y"):
    if not ticker_ns.endswith(".BO") or _bse_blocked():
        return None
    sym  = _to_nse(ticker_ns)
    days = _period_to_days(period)
    flag = "3M" if days <= 90 else ("6M" if days <= 180 else "12M")
    code = _resolve_bse_code(sym)
    if not code:
        return None
    try:
        r = _SESSION.get(
            "https://api.bseindia.com/BseIndiaAPI/api/StockReachGraph/w",
            params={"scripcode": code, "flag": flag,
                    "fromdate": "", "todate": "", "seriesid": ""},
            headers=_BSE_HEADERS, timeout=_TIMEOUT,
        )
        if r.status_code in (403, 503):
            _block_bse()
            return None
        rows = r.json().get("Data", [])
        if not rows:
            return None
        dates, opens, highs, lows, closes, volumes = [], [], [], [], [], []
        for row in rows:
            price = (row.get("CurrRate") or row.get("CurrRateMin") or
                     row.get("yValue") or row.get("CurrVal"))
            date_str = (row.get("CurrDate") or row.get("dttm") or
                        row.get("DTTM") or row.get("Date"))
            if price is None or not date_str:
                continue
            parsed_date = None
            for fmt in ("%d %b %Y", "%d/%m/%Y", "%Y-%m-%d", "%Y%m%d"):
                try:
                    parsed_date = datetime.strptime(str(date_str)[:10], fmt).strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue
            if not parsed_date:
                continue
            c = float(price)
            dates.append(parsed_date)
            opens.append(c); highs.append(c); lows.append(c)
            closes.append(c); volumes.append(0.0)
        if not dates:
            return None
        return _build_df(dates, opens, highs, lows, closes, volumes, ticker_ns)
    except Exception:
        return None


# ── Source 3: Stooq (free, universal, full OHLCV) ────────────────────────────

def fetch_ohlcv_stooq(ticker_ns: str, period: str = "1y"):
    import io
    sym  = _to_stooq(ticker_ns)
    days = _period_to_days(period)
    try:
        r = _SESSION.get(
            "https://stooq.com/q/d/l/",
            params={"s": sym, "i": "d"},
            timeout=_TIMEOUT,
        )
        text = r.text.strip()
        if not text or "No data" in text or text.startswith("<"):
            return None
        df = pd.read_csv(io.StringIO(text))
        df.columns = [c.strip() for c in df.columns]
        if "Close" not in df.columns or "Date" not in df.columns:
            return None
        df["Date"] = pd.to_datetime(df["Date"])
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=days)
        df = df[df["Date"] >= cutoff].copy()
        if df.empty:
            return None
        dates   = df["Date"].dt.strftime("%Y-%m-%d").tolist()
        opens   = df["Open"].tolist()   if "Open"   in df.columns else df["Close"].tolist()
        highs   = df["High"].tolist()   if "High"   in df.columns else df["Close"].tolist()
        lows    = df["Low"].tolist()    if "Low"    in df.columns else df["Close"].tolist()
        closes  = df["Close"].tolist()
        volumes = df["Volume"].tolist() if "Volume" in df.columns else [0.0] * len(dates)
        return _build_df(dates, opens, highs, lows, closes, volumes, ticker_ns)
    except Exception:
        return None


# ── Source 3b: jugaad-data (free, no key — NSE scraper with built-in caching) ─

def fetch_ohlcv_jugaad(ticker_ns: str, period: str = "1y"):
    if not ticker_ns.endswith(".NS"):
        return None
    try:
        from jugaad_data.nse import stock_df
        from datetime import date as _date
        sym  = _to_nse(ticker_ns)
        days = _period_to_days(period)
        to_d   = _date.today()
        from_d = _date.fromordinal(to_d.toordinal() - days)
        df = stock_df(symbol=sym, from_date=from_d, to_date=to_d, series="EQ")
        if df is None or df.empty:
            return None
        df = df.copy()
        # jugaad-data columns may be uppercase or mixed; normalise
        df.columns = [c.strip().upper() for c in df.columns]
        date_col  = next((c for c in df.columns if "DATE" in c), None)
        close_col = next((c for c in df.columns if c in ("CLOSE", "LTP", "CH_CLOSING_PRICE")), None)
        open_col  = next((c for c in df.columns if c in ("OPEN", "CH_OPENING_PRICE")), None)
        high_col  = next((c for c in df.columns if c in ("HIGH", "CH_TRADE_HIGH_PRICE")), None)
        low_col   = next((c for c in df.columns if c in ("LOW",  "CH_TRADE_LOW_PRICE")),  None)
        vol_col   = next((c for c in df.columns if c in ("VOLUME", "TOTTRDQTY", "CH_TOT_TRADED_QTY")), None)
        if not (date_col and close_col):
            return None
        dates   = pd.to_datetime(df[date_col]).dt.strftime("%Y-%m-%d").tolist()
        closes  = df[close_col].astype(float).tolist()
        opens   = df[open_col].astype(float).tolist()  if open_col  else closes
        highs   = df[high_col].astype(float).tolist()  if high_col  else closes
        lows    = df[low_col].astype(float).tolist()   if low_col   else closes
        volumes = df[vol_col].astype(float).tolist()   if vol_col   else [0.0] * len(dates)
        return _build_df(dates, opens, highs, lows, closes, volumes, ticker_ns)
    except Exception:
        return None


# ── Source 3c: openchart (free, no key — NSE charting endpoint) ───────────────

def fetch_ohlcv_openchart(ticker_ns: str, period: str = "1y"):
    if not ticker_ns.endswith(".NS"):
        return None
    try:
        from openchart import NSEData
        import datetime as _dt
        sym    = _to_nse(ticker_ns)
        days   = _period_to_days(period)
        end_dt = _dt.datetime.now()
        st_dt  = end_dt - _dt.timedelta(days=days)
        nse    = NSEData()
        df = nse.historical(symbol=sym, exchange="NSE",
                            start=st_dt, end=end_dt, interval="1d")
        if df is None or df.empty:
            return None
        df = df.copy()
        df.columns = [c.strip().lower() for c in df.columns]
        dt_col  = next((c for c in df.columns if c in ("datetime", "date", "timestamp")), None)
        if dt_col is None:
            return None
        dates   = pd.to_datetime(df[dt_col]).dt.strftime("%Y-%m-%d").tolist()
        closes  = df["close"].astype(float).tolist()
        opens   = df["open"].astype(float).tolist()   if "open"   in df.columns else closes
        highs   = df["high"].astype(float).tolist()   if "high"   in df.columns else closes
        lows    = df["low"].astype(float).tolist()    if "low"    in df.columns else closes
        volumes = df["volume"].astype(float).tolist() if "volume" in df.columns else [0.0] * len(dates)
        return _build_df(dates, opens, highs, lows, closes, volumes, ticker_ns)
    except Exception:
        return None


# ── Source 6: Yahoo Finance (last resort) ────────────────────────────────────

def fetch_ohlcv_yfinance(ticker_ns: str, period: str = "1y", _timeout: int = 25):
    if _yf_blocked():
        return None

    try:
        import yfinance as yf
        import concurrent.futures as _cf

        # yf.download has no built-in timeout — wrap in a timed future.
        # IMPORTANT: use shutdown(wait=False) after timeout so the hung yf.download
        # thread doesn't block the caller. `with ThreadPoolExecutor` blocks on __exit__
        # even after future.result(timeout=N) fires — exactly the wrong behavior here.
        def _dl():
            return yf.download(ticker_ns, period=period, auto_adjust=True,
                               progress=False, threads=False)

        # Global semaphore: limit concurrent Yahoo calls to avoid IP-level throttling.
        with _YF_SEMAPHORE:
            _ex = _cf.ThreadPoolExecutor(max_workers=1)
            _fut = _ex.submit(_dl)
            try:
                hist = _fut.result(timeout=_timeout)
            except _cf.TimeoutError:
                logging.warning("yfinance download timed out after %ss for %s", _timeout, ticker_ns)
                _ex.shutdown(wait=False)  # don't block — let the hung thread die in background
                return None
            _ex.shutdown(wait=False)
        if hist is not None and not hist.empty and isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        if hist is None or hist.empty:
            return None
        # yfinance 1.x returns tz-aware index (Asia/Kolkata); strip tz so dates
        # align with nifty_c from yf.download() which is always tz-naive.
        if hist.index.tz is not None:
            hist.index = hist.index.tz_localize(None)
        C = hist[["Close"]].rename(columns={"Close": ticker_ns})
        H = hist[["High"]].rename(columns={"High": ticker_ns})
        L = hist[["Low"]].rename(columns={"Low": ticker_ns})
        V = hist[["Volume"]].rename(columns={"Volume": ticker_ns})
        return C.ffill(), H.ffill(), L.ffill(), V.ffill()
    except Exception as e:
        if _is_yf_crumb_error(e):
            logging.warning("Blocking yfinance temporarily due to crumb/auth errors: %s", e)
            _block_yf()
        return None


# ── Cache warming (call before predictions to guarantee fast SQLite hits) ─────

def warm_ohlcv_cache(ticker_ns: str, period: str = "1y") -> bool:
    """
    Pre-warm the SQLite OHLCV cache with a 60s timeout (vs 25s during predictions).
    Returns True if cache is now fresh. Call in parallel across all watchlist /
    top5 tickers before starting predictions — predictions then get instant cache hits.
    """
    if not ticker_ns.endswith((".NS", ".BO")):
        ticker_ns = ticker_ns + ".NS"

    # Already fresh? Nothing to do.
    sql_result = _load_sql_cache(ticker_ns, period)
    if sql_result is not None and sql_result[4]:
        logging.debug("warm_ohlcv_cache: %s already fresh", ticker_ns)
        return True

    # Skip if recently exhausted to avoid piling up retries
    if _ohlcv_is_failed(ticker_ns, period):
        return False

    logging.info("warm_ohlcv_cache: fetching %s period=%s", ticker_ns, period)
    _lock = _get_ticker_lock(ticker_ns)
    with _lock:
        # Double-check after acquiring lock
        sql_result = _load_sql_cache(ticker_ns, period)
        if sql_result is not None and sql_result[4]:
            return True
        if _ohlcv_is_failed(ticker_ns, period):
            return False

        # Try yfinance first with extended timeout (HF Spaces or any environment)
        result = fetch_ohlcv_yfinance(ticker_ns, period, _timeout=60)
        if result is not None:
            sc, sh, sl, sv = result
            _save_sql_cache(ticker_ns, period, sc, sh, sl, sv)
            logging.info("warm_ohlcv_cache: %s cached (%s)", ticker_ns, period)
            return True

        # Fell through — mark failed briefly (30s) so prediction threads skip
        _ohlcv_mark_failed(ticker_ns, period, ttl=30.0)
        logging.warning("warm_ohlcv_cache: all sources failed for %s", ticker_ns)
        return False


# ── Public entry point: OHLCV ─────────────────────────────────────────────────

def _prev_trading_day(today_ist: date) -> date:
    """Most recent NSE trading day before today_ist (weekday + not in holiday set)."""
    try:
        from market_calendar import is_trading_day
    except ImportError:
        # Fallback: weekday-only check (no holiday awareness)
        def is_trading_day(d):  # type: ignore[misc]
            return d.weekday() < 5

    probe = today_ist - timedelta(days=1)
    for _ in range(14):
        if is_trading_day(probe):
            return probe
        probe -= timedelta(days=1)
    return probe


def _is_data_fresh(sc: "pd.DataFrame", col: str) -> bool:
    """Return True if the DataFrame's last data date is within 1 trading day of today IST.

    Stale sources (e.g. jugaad returning June 28 when June 30 is a trading day) are
    rejected so the fallback chain continues to a fresher source like yfinance.
    """
    try:
        today_ist = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        clean = sc[col].dropna()
        if clean.empty:
            return False
        last_date = date.fromisoformat(str(clean.index[-1])[:10])
        prev_td = _prev_trading_day(today_ist)
        return last_date >= prev_td
    except Exception:
        return True  # on any error, assume fresh to avoid breaking other callers


def fetch_ohlcv(ticker_ns: str, period: str = "1y"):
    """
    Fetch OHLCV for an NSE/BSE ticker, trying sources in priority order.
    Returns (sc, sh, sl, sv) DataFrames with ticker_ns as the column name.

    SQLite cache (two-layer):
      1. If SQLite cache is fresh (last bar >= last trading day): return instantly, no network.
      2. If SQLite cache is stale: try network; on success update DB; on failure serve stale.
      3. No DB row: full network fetch; on success insert into DB.
    Raises ValueError only when all sources AND DB cache are unavailable.
    """
    # ── 1. Fast cache check (no lock — reads are safe) ────────────────────────
    sql_result = _load_sql_cache(ticker_ns, period)
    if sql_result is not None:
        sc, sh, sl, sv, is_fresh = sql_result
        if is_fresh:
            return sc, sh, sl, sv  # instant hit — no network needed

    # ── 1b. Negative cache: skip full chain if a sibling thread already failed ─
    # Without this, 4 TF threads queue on the per-ticker lock and each tries the
    # full 73s fallback chain serially (4 × 73s = 292s >> 150s timeout).
    # With this, threads 2-4 see the failure mark (<1s) and skip to stale/error.
    if _ohlcv_is_failed(ticker_ns, period):
        sql_result = _load_sql_cache(ticker_ns, period)
        if sql_result is not None:
            return sql_result[0], sql_result[1], sql_result[2], sql_result[3]
        raise ValueError(f"OHLCV fetch for {ticker_ns} failed recently — skipping retry for 60s")

    # ── 2. Per-ticker lock + network fetch ────────────────────────────────────
    # Only ONE thread fetches per ticker. Others wait and get the cached result
    # after the first thread completes. Prevents thundering herd where 4 TF threads
    # for the same stock all hammer Yahoo Finance concurrently → throttling/hangs.
    _lock = _get_ticker_lock(ticker_ns)
    with _lock:
        # Double-check after acquiring lock — a sibling may have just fetched,
        # or the negative cache may now be set.
        if _ohlcv_is_failed(ticker_ns, period):
            sql_result = _load_sql_cache(ticker_ns, period)
            if sql_result is not None:
                return sql_result[0], sql_result[1], sql_result[2], sql_result[3]
            raise ValueError(f"OHLCV fetch for {ticker_ns} recently failed — skipping")
        sql_result = _load_sql_cache(ticker_ns, period)
        stale_cached = None
        if sql_result is not None:
            sc, sh, sl, sv, is_fresh = sql_result
            if is_fresh:
                return sc, sh, sl, sv  # sibling thread fetched while we waited
            stale_cached = (sc, sh, sl, sv)

        # ── 2a. Source order ───────────────────────────────────────────────────
        # NSE's direct OHLCV API (/api/historical/cm/equity) is bot-blocked (HTTP 403)
        # even from residential IPs, so it is NOT tried — it only wasted a warmup +
        # request per fetch. yfinance (Yahoo per-ticker endpoints) works everywhere
        # including HF Spaces datacenter IPs, so it is the primary source.
        sources = [
            fetch_ohlcv_yfinance,        # Yahoo Finance — primary, works everywhere
            fetch_ohlcv_stooq,           # Stooq         — free fallback
            fetch_ohlcv_openchart,       # openchart     — free fallback
            fetch_ohlcv_jugaad,          # jugaad-data   — free fallback
            fetch_ohlcv_bse_official,    # BSE direct    — .BO tickers only
        ]

        # ── 2b. Try each source ────────────────────────────────────────────────
        # A source can return correct data that just isn't "fresh" (doesn't reach
        # yesterday's bar yet, e.g. jugaad often lags a day) — that's still far
        # better than a multi-day-old SQL cache for callers validating a backdated
        # window. Remember the most-recent non-fresh result seen so 2d can prefer
        # it over stale_cached instead of raising / serving even-older data.
        best_live, best_live_last_date = None, None
        for fn in sources:
            try:
                result = fn(ticker_ns, period)
                if result is not None:
                    sc, sh, sl, sv = result
                    if ticker_ns in sc.columns and not sc[ticker_ns].dropna().empty:
                        if not _is_data_fresh(sc, ticker_ns):
                            last_date = str(sc.index[-1])[:10]
                            logging.warning(
                                "OHLCV source %s returned stale data for %s (last: %s), trying next",
                                fn.__name__, ticker_ns, last_date,
                            )
                            if best_live_last_date is None or last_date > best_live_last_date:
                                best_live_last_date = last_date
                                best_live = (sc.ffill(), sh.ffill(), sl.ffill(), sv.ffill())
                            continue
                        sc, sh, sl, sv = sc.ffill(), sh.ffill(), sl.ffill(), sv.ffill()
                        _save_sql_cache(ticker_ns, period, sc, sh, sl, sv)
                        return sc, sh, sl, sv
            except Exception as e:
                logging.warning("OHLCV source %s failed for %s: %s", fn.__name__, ticker_ns, e)
                continue

        # ── 2c. Cross-exchange fallback (.NS ↔ .BO) ───────────────────────────
        alt = ticker_ns.replace(".NS", ".BO") if ticker_ns.endswith(".NS") else ticker_ns.replace(".BO", ".NS")
        for fn in [fetch_ohlcv_stooq, fetch_ohlcv_yfinance]:
            try:
                result = fn(alt, period)
                if result is not None:
                    sc, sh, sl, sv = result
                    if alt in sc.columns and not sc[alt].dropna().empty:
                        logging.warning(
                            "data_sources: cross-exchange fallback %s → %s (volume indicators understated)",
                            ticker_ns, alt,
                        )
                        sc = sc.rename(columns={alt: ticker_ns})
                        sh = sh.rename(columns={alt: ticker_ns})
                        sl = sl.rename(columns={alt: ticker_ns})
                        sv = sv.rename(columns={alt: ticker_ns})
                        sc, sh, sl, sv = sc.ffill(), sh.ffill(), sl.ffill(), sv.ffill()
                        _save_sql_cache(ticker_ns, period, sc, sh, sl, sv)
                        return sc, sh, sl, sv
            except Exception:
                continue

        # ── 2d. Stale cache fallback ───────────────────────────────────────────
        # Mark this ticker as failed BEFORE returning stale data, so waiting TF
        # threads (1D, 3D, 5D all queued behind 5D that just exhausted all sources)
        # skip the full 73s chain and reach stale-cache / error in <1s.
        _ohlcv_mark_failed(ticker_ns, period)

        # Prefer a live source's non-fresh-but-recent data over the SQL cache if it's
        # newer (fixes backdated validation returning nothing when e.g. jugaad has the
        # target date but lags "today" by a day, while the SQL cache predates it further).
        stale_cache_last_date = str(stale_cached[0].index[-1])[:10] if stale_cached is not None else None
        if best_live is not None and (stale_cache_last_date is None or best_live_last_date > stale_cache_last_date):
            _save_sql_cache(ticker_ns, period, *best_live)
            logging.warning(
                "Using non-fresh live OHLCV for %s (last: %s) — newer than SQL cache (last: %s)",
                ticker_ns, best_live_last_date, stale_cache_last_date,
            )
            return best_live

        if stale_cached is not None:
            logging.warning(
                "All live sources failed for %s — serving stale cached OHLCV", ticker_ns,
            )
            return stale_cached

        raise ValueError(f"All data sources failed for {ticker_ns}")


def _yf_download_timed(ticker: str, timeout: int = 15, **kwargs):
    """Run yf.download with a hard wall-clock timeout.

    yf.download has no built-in timeout — a hung Yahoo connection blocks the caller
    indefinitely. We use the same ThreadPoolExecutor pattern as fetch_ohlcv_yfinance:
    submit to a single-worker pool and abandon the thread (shutdown(wait=False)) after
    the deadline fires so the caller is never blocked past `timeout` seconds.
    """
    import yfinance as yf
    _ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        fut = _ex.submit(yf.download, ticker, **kwargs)
        return fut.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        return None
    finally:
        _ex.shutdown(wait=False)


# ── Public entry point: live price ───────────────────────────────────────────

def fetch_live_price(ticker_ns: str, allow_delayed: bool = True) -> Optional[float]:
    """
        Fetch last traded price for an NSE/BSE ticker.
        Tries: NSE Official → BSE Official → Yahoo Finance.

        Parameters:
            allow_delayed: when False, skips delayed Yahoo-based fallbacks and returns
            None unless a real-time source succeeds.
    Returns float or None if all sources fail.
    """
    # NSE's official live-quote API (/api/quote-equity) and jugaad-data's NSELive both
    # hit the bot-blocked www.nseindia.com API and return HTTP 403 ("Access Denied")
    # even from residential IPs — they were removed as they only wasted time. yfinance
    # (below) is the working same-day source; BSE is kept for .BO tickers.

    # Source 1: BSE Official live quote (free, real-time, .BO only)
    if ticker_ns.endswith(".BO") and not _bse_blocked():
        try:
            code = _resolve_bse_code(_to_nse(ticker_ns))
            if code:
                r = _SESSION.get(
                    "https://api.bseindia.com/BseIndiaAPI/api/getScripHeaderData/w",
                    params={"scripcode": code},
                    headers=_BSE_HEADERS, timeout=_TIMEOUT,
                )
                if r.status_code in (403, 503):
                    _block_bse()
                else:
                    d   = r.json()
                    ltp = (d.get("CurrRate", {}).get("LTP") or
                           d.get("Header",   {}).get("LTP") or d.get("LTP"))
                    if ltp:
                        return round(float(ltp), 2)
        except Exception:
            pass

    # Source 2: Yahoo Finance — freshness-safe fallback.
    # Prefer 1-minute bars (same-day, near real-time); fall back to daily close
    # only when the bar date is today in IST.
    if allow_delayed and not _yf_blocked():
        try:
            intraday = _yf_download_timed(
                ticker_ns,
                timeout=15,
                period="1d",
                interval="1m",
                auto_adjust=True,
                progress=False,
                threads=False,
            )
            if intraday is not None and not intraday.empty:
                if isinstance(intraday.columns, pd.MultiIndex):
                    intraday.columns = intraday.columns.get_level_values(0)
                closes = intraday["Close"].dropna() if "Close" in intraday.columns else pd.Series(dtype=float)
                if not closes.empty:
                    last_ts = closes.index[-1]
                    if _is_today_ist(pd.Timestamp(last_ts)):
                        return round(float(closes.iloc[-1]), 2)

            hist = _yf_download_timed(ticker_ns, timeout=15, period="5d", auto_adjust=True, progress=False, threads=False)
            if hist is not None and not hist.empty:
                if isinstance(hist.columns, pd.MultiIndex):
                    hist.columns = hist.columns.get_level_values(0)
                closes = hist["Close"].dropna() if "Close" in hist.columns else pd.Series(dtype=float)
                # Require today's date (IST) so we don't serve yesterday's close on
                # weekends, holidays, or after intraday bars are unavailable.
                if not closes.empty and _is_today_ist(pd.Timestamp(closes.index[-1])):
                    return round(float(closes.iloc[-1]), 2)
        except Exception as e:
            if _is_yf_crumb_error(e):
                _block_yf()

    # Source 6: cross-exchange fallback via yfinance (same freshness checks)
    alt = ticker_ns.replace(".NS", ".BO") if ticker_ns.endswith(".NS") else ticker_ns.replace(".BO", ".NS")
    if allow_delayed and not _yf_blocked():
        try:
            intraday = _yf_download_timed(
                alt,
                timeout=15,
                period="1d",
                interval="1m",
                auto_adjust=True,
                progress=False,
                threads=False,
            )
            if intraday is not None and not intraday.empty:
                if isinstance(intraday.columns, pd.MultiIndex):
                    intraday.columns = intraday.columns.get_level_values(0)
                closes = intraday["Close"].dropna() if "Close" in intraday.columns else pd.Series(dtype=float)
                if not closes.empty and _is_today_ist(pd.Timestamp(closes.index[-1])):
                    return round(float(closes.iloc[-1]), 2)

            hist = _yf_download_timed(alt, timeout=15, period="5d", auto_adjust=True, progress=False, threads=False)
            if hist is not None and not hist.empty:
                if isinstance(hist.columns, pd.MultiIndex):
                    hist.columns = hist.columns.get_level_values(0)
                closes = hist["Close"].dropna() if "Close" in hist.columns else pd.Series(dtype=float)
                if not closes.empty and _is_today_ist(pd.Timestamp(closes.index[-1])):
                    return round(float(closes.iloc[-1]), 2)
        except Exception as e:
            if _is_yf_crumb_error(e):
                _block_yf()

    return None


# ── Market data: Nifty50 + India VIX ─────────────────────────────────────────

def _fetch_market_nse_unofficial() -> tuple:
    """Try NSE India unofficial API — no key, just needs browser UA."""
    try:
        _SESSION.get("https://www.nseindia.com", timeout=_TIMEOUT)
        r = _SESSION.get(
            "https://www.nseindia.com/api/allIndices",
            timeout=_TIMEOUT,
        )
        data = r.json()
        indices = {item["index"]: item for item in data.get("data", [])}
        vix_val   = float(indices.get("INDIA VIX", {}).get("last", 0) or 0)
        nifty_val = float(indices.get("NIFTY 50",  {}).get("last", 0) or 0)
        if vix_val > 0 and nifty_val > 0:
            today = pd.Timestamp.today().normalize()
            nifty_c = pd.Series({today: nifty_val}, name="^NSEI", dtype=float)
            vix_c   = pd.Series({today: vix_val},   name="^INDIAVIX", dtype=float)
            return nifty_c, vix_c
    except Exception as e:
        logging.warning("NSE unofficial market fetch failed: %s", e)
    return None, None


def _fetch_market_stooq(period_days: int = 365) -> tuple:
    """Fallback historical Nifty from Stooq when NSE/Yahoo are unavailable."""
    try:
        # Common stooq symbols for Indian benchmarks can vary by mirror; try a few.
        candidates = ["^NSEI", "NSEI", "NIFTY", "NIFTY50"]
        for sym in candidates:
            try:
                url = f"https://stooq.com/q/d/l/?s={sym.lower()}&i=d"
                r = _SESSION.get(url, timeout=_TIMEOUT)
                if r.status_code != 200 or "Date,Open,High,Low,Close,Volume" not in r.text:
                    continue
                from io import StringIO
                df = pd.read_csv(StringIO(r.text))
                if df is None or df.empty or "Close" not in df.columns:
                    continue
                df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
                df = df.dropna(subset=["Date", "Close"]).sort_values("Date")
                if len(df) < 50:
                    continue
                cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=period_days)
                df = df[df["Date"] >= cutoff]
                nifty_c = pd.Series(df["Close"].astype(float).values, index=df["Date"], name="^NSEI")
                return nifty_c, None
            except Exception:
                continue
    except Exception as e:
        logging.warning("Stooq market fetch failed: %s", e)
    return None, None


def _synthetic_nifty_from_spot(nifty_spot: float, bars: int = 220) -> pd.Series:
    """Create synthetic historical series from live spot when no historical source is available."""
    end = pd.Timestamp.today().normalize()
    idx = pd.bdate_range(end=end, periods=bars)
    vals = [float(nifty_spot)] * len(idx)
    return pd.Series(vals, index=idx, name="^NSEI", dtype=float)


def _fetch_market_yfinance(period_days: int = 365) -> tuple:
    if _yf_blocked():
        return None, None

    try:
        import yfinance as yf
        period = "1y" if period_days <= 365 else "2y"
        raw = yf.download(["^NSEI", "^INDIAVIX"], period=period,
                          progress=False, auto_adjust=True, threads=False)
        if raw.empty:
            return None, None
        C = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw
        nifty_c = C["^NSEI"].dropna()     if "^NSEI"     in C.columns else None
        vix_c   = C["^INDIAVIX"].dropna() if "^INDIAVIX" in C.columns else None
        return nifty_c, vix_c
    except Exception as e:
        if _is_yf_crumb_error(e):
            _block_yf()
        logging.warning("Yahoo Finance market fetch failed: %s", e)
        return None, None


def fetch_market_data(period_days: int = 365) -> tuple:
    """
    Returns (nifty_c, vix_c) as pandas Series.
    Tries: NSE unofficial → Yahoo Finance.
    nifty_c must have >= 50 bars for EMA200 gate. NSE unofficial returns only a
    spot price (1 bar) so it fails this check automatically and falls through to
    Yahoo — but its VIX reading is still captured as the best real-time value.
    """
    vix_c = None
    nse_spot = None
    for fn in [
        _fetch_market_nse_unofficial,
        lambda: _fetch_market_stooq(period_days),
        lambda: _fetch_market_yfinance(period_days),
    ]:
        try:
            nifty_c, vc = fn()
            if vix_c is None and vc is not None and len(vc) > 0:
                vix_c = vc
            if nifty_c is not None and len(nifty_c) == 1 and nse_spot is None:
                nse_spot = float(nifty_c.iloc[-1])
            if nifty_c is not None and len(nifty_c) >= 50:
                return nifty_c, vix_c
        except Exception as e:
            logging.warning("Market data source failed: %s", e)
            continue

    # Last-resort fallback: build synthetic Nifty history from NSE live spot.
    if nse_spot is not None:
        logging.warning("Using synthetic Nifty history from NSE spot due to upstream outages")
        return _synthetic_nifty_from_spot(nse_spot), vix_c

    logging.warning("All market data sources exhausted — Nifty EMA gate will be skipped")


# ── New cache functions for cached OHLCV + live price prediction ──────────────

def get_cached_ohlcv(ticker: str) -> Optional[pd.DataFrame]:
    """
    Read cached OHLCV from SQLite without fetching fresh data.
    Used by predict_stock_v2 when _skip_fresh_fetch=True to avoid network timeouts.

    Returns DataFrame with columns [Date, Open, High, Low, Close, Volume, ticker]
    or None if cache miss.
    """
    try:
        result = _load_sql_cache(ticker, period="1y")
        if result is None:
            logging.debug(f"Cache MISS: {ticker}")
            return None

        sc, sh, sl, sv, is_fresh = result
        # Reconstruct DataFrame from pickle
        df = pd.DataFrame({
            "Date": sc.index,
            "Open": sc.values,
            "High": sh.values,
            "Low": sl.values,
            "Close": sc.values,  # sc is close series
            "Volume": sv.values,
        })
        df["ticker"] = ticker
        logging.debug(f"Cache HIT: {ticker} ({len(df)} rows, fresh={is_fresh})")
        return df
    except Exception as e:
        logging.warning(f"Error reading cache for {ticker}: {e}")
        return None


def update_cached_ohlcv(ticker: str, ohlcv_df: pd.DataFrame) -> bool:
    """
    Write fresh OHLCV to SQLite. Called from background thread.
    Expected columns: Date, Open, High, Low, Close, Volume.

    Thread-safe using SQLite's built-in locking.
    Returns True if successful, False otherwise.
    """
    try:
        if ohlcv_df is None or ohlcv_df.empty:
            return False

        # Reconstruct the pickle format used by _save_sql_cache
        sc = pd.Series(
            ohlcv_df["Close"].values,
            index=pd.to_datetime(ohlcv_df["Date"]),
            name="Close"
        )
        sh = pd.Series(
            ohlcv_df["High"].values,
            index=sc.index,
            name="High"
        )
        sl = pd.Series(
            ohlcv_df["Low"].values,
            index=sc.index,
            name="Low"
        )
        sv = pd.Series(
            ohlcv_df["Volume"].values,
            index=sc.index,
            name="Volume"
        )

        _save_sql_cache(ticker, period="1y", sc=sc, sh=sh, sl=sl, sv=sv)
        logging.info(f"Cache UPDATE: {ticker} ({len(ohlcv_df)} rows)")
        return True
    except Exception as e:
        logging.warning(f"Error updating cache for {ticker}: {e}")
        return False


def fetch_and_cache_ohlcv(
    ticker: str,
    force: bool = False,
    start_date: str = None,
    end_date: str = None
) -> Optional[pd.DataFrame]:
    """
    Fetch fresh OHLCV and update cache. Called from background thread.

    Args:
        ticker: Stock ticker (e.g., "RELIANCE.NS")
        force: If True, always fetch fresh even if cache is recent
        start_date, end_date: Date range for fetch (optional)

    Returns:
        DataFrame if fetch successful, None otherwise.
    """
    try:
        # Check cache age if not forced
        if not force:
            cached = get_cached_ohlcv(ticker)
            if cached is not None and not cached.empty:
                cache_age = (datetime.now() - pd.to_datetime(cached["Date"]).max()).days
                if cache_age < 1:  # < 1 day old
                    logging.debug(f"Cache for {ticker} is fresh ({cache_age}d old), skipping refresh")
                    return cached

        # Fetch fresh OHLCV
        fresh_df = fetch_ohlcv(ticker, start_date=start_date or "", end_date=end_date or "")
        if fresh_df is not None and not fresh_df.empty:
            # Reconstruct for cache storage
            if "Date" not in fresh_df.columns:
                fresh_df = fresh_df.reset_index()
            update_cached_ohlcv(ticker, fresh_df)
            logging.info(f"Fetched and cached fresh OHLCV for {ticker}: {len(fresh_df)} rows")
            return fresh_df
    except Exception as e:
        logging.warning(f"Error fetching fresh OHLCV for {ticker}: {e}")
    return None
    return pd.Series(dtype=float), vix_c
