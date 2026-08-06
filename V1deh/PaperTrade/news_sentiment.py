#!/usr/bin/env python3
"""
news_sentiment.py — AI-powered news sentiment for NSE stocks.

Provider chain: OpenRouter → Groq → HuggingFace → keyword scoring.

News fetch strategy:
  1. Google News RSS using company name (most relevant for NSE stocks)
  2. yfinance .news as secondary (often wrong/empty for Indian tickers)
"""

from __future__ import annotations
import json
import re
import time
import warnings
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime
warnings.filterwarnings("ignore")

from llm_client import make_chat_call as _llm_make_chat_call

# ── NEWS CACHE (5-min TTL, keyed by ticker) ───────────────────────────────────
import threading as _threading
_NEWS_CACHE: dict = {}
_NEWS_CACHE_TTL = 300  # seconds

# Per-ticker lock: prevents thundering herd when 4 TF threads for the same
# stock all see a cache miss and all try to call the LLM simultaneously.
_NEWS_LOCKS: dict = {}
_NEWS_LOCKS_LOCK = _threading.Lock()

def _get_news_lock(key: str) -> _threading.Lock:
    with _NEWS_LOCKS_LOCK:
        if key not in _NEWS_LOCKS:
            _NEWS_LOCKS[key] = _threading.Lock()
        return _NEWS_LOCKS[key]

# ── KEYWORD FALLBACK SETS ─────────────────────────────────────────────────────
_POS = {
    "surge", "rally", "gain", "profit", "strong", "beat", "upgrade",
    "bullish", "outperform", "growth", "rise", "high", "record", "breakout",
    "momentum", "positive", "robust", "boost", "contract", "win", "expansion",
    "dividend", "buyback", "order", "partnership", "acquisition", "merger",
    "beat", "exceeded", "upbeat", "optimistic", "recovery", "rebound",
}
_NEG = {
    "fall", "drop", "loss", "weak", "miss", "downgrade", "bearish", "underperform",
    "decline", "low", "crash", "cut", "reduce", "concern", "risk", "delay",
    "probe", "investigation", "fraud", "penalty", "fine", "slowdown", "crisis",
    "selloff", "slump", "disappointing", "bleak", "warning", "breach", "lawsuit",
}

def analyze_news(
    headlines:  list[str],
    ticker:     str,
    company:    str = "",
    dated:      list | None = None,
) -> dict:
    """
    Analyze news headlines using OpenRouter → Groq → HuggingFace.
    Returns { label, score, summary, key_headline, source }.
    Falls back to keyword scoring if no API key is set.

    `dated` (optional) is a list of (date 'YYYY-MM-DD', title) newest-first; when
    supplied the LLM is shown the publish dates so it can weight recent news higher.
    """
    if not headlines:
        return {"label": "NEUTRAL", "score": 0, "summary": "No recent news found.",
                "key_headline": "", "source": "none"}

    result = _llm_analyze(headlines, ticker, company or ticker, dated=dated)
    if result:
        return result

    return _keyword_fallback(headlines)


def _llm_analyze(headlines: list[str], ticker: str, company: str,
                 dated: list | None = None) -> dict | None:
    """Call shared LLM provider chain for news sentiment. Falls back to None on failure."""
    # Prefix each headline with its publish date (when known) so the model weights
    # today's news above week-old stories. Falls back to plain numbering.
    if dated:
        numbered = "\n".join(
            f"{i+1}. [{(d or 'undated')}] {t}" for i, (d, t) in enumerate(dated[:8])
        )
    else:
        numbered = "\n".join(f"{i+1}. {h}" for i, h in enumerate(headlines[:8]))
    prompt = f"""You are a financial news analyst specializing in Indian equity markets.

Analyze these news headlines for {company} ({ticker}, NSE-listed stock):

{numbered}

Respond with ONLY a valid JSON object — no markdown, no explanation:
{{
  "sentiment": "BULLISH" | "BEARISH" | "NEUTRAL",
  "score": <integer from -30 (very bearish) to +30 (very bullish)>,
  "summary": "<one sentence: the dominant catalyst or theme driving this stock>",
  "key_headline": "<the single most market-moving headline from the list>"
}}

Rules:
- Weight RECENT headlines (bracketed dates) more heavily — today's news outweighs week-old news.
- BULLISH: positive earnings, contracts, upgrades, sector tailwinds, management guidance up
- BEARISH: misses, downgrades, regulatory issues, macro headwinds, management exits
- NEUTRAL: routine news, sector-level stories without stock-specific impact
- Score magnitude reflects conviction: ±5-10 = mild, ±15-25 = moderate, ±28-30 = strong"""

    try:
        content, provider, model = _llm_make_chat_call(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=250,
            temperature=0.2,
            fast_fail_on_rate_limit=True,
            max_retries=2,
        )
    except Exception:
        return None

    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", (content or "").strip(), flags=re.MULTILINE).strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None

    # Guard: validate label enum
    label = (data.get("sentiment") or "NEUTRAL").upper().strip()
    if label not in ("BULLISH", "BEARISH", "NEUTRAL"):
        label = "NEUTRAL"

    # Guard: clamp score to declared range [-30, +30]
    try:
        score = int(data.get("score", 0))
    except (TypeError, ValueError):
        score = 0
    score = max(-30, min(30, score))

    return {
        "label": label,
        "score": score,
        "summary": str(data.get("summary", ""))[:300],
        "key_headline": str(data.get("key_headline") or (headlines[0] if headlines else "")),
        "source": f"{provider}:{model}",
    }


def _keyword_fallback(headlines: list[str]) -> dict:
    text  = " ".join(headlines).lower()
    words = set(text.split())
    pos   = len(words & _POS)
    neg   = len(words & _NEG)
    raw   = pos - neg
    score = max(-30, min(30, raw * 3))
    label = "BULLISH" if score > 5 else ("BEARISH" if score < -5 else "NEUTRAL")
    return {
        "label":        label,
        "score":        score,
        "summary":      "",
        "key_headline": headlines[0] if headlines else "",
        "source":       "keywords",
    }


# ── GOOGLE NEWS RSS FETCH ─────────────────────────────────────────────────────
def _fetch_google_news(query: str, max_items: int = 8, with_dates: bool = False):
    """
    Fetch headlines from Google News RSS for the given search query.
    Uses company name search (e.g. 'HDFC Bank stock NSE') for accurate results.

    Returns newest-first. By default a list[str] of titles; with_dates=True returns
    list[tuple[str, str]] of (pubDate 'YYYY-MM-DD', title) so callers can surface recency.
    """
    url = (
        f"https://news.google.com/rss/search"
        f"?q={urllib.parse.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        # Extract per-item titles + pubDate, sort newest-first, then slice
        items = re.findall(r"<item>(.*?)</item>", raw, re.DOTALL)
        parsed = []
        for item in items:
            m = re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>", item)
            if not m:
                m = re.search(r"<title>(.*?)</title>", item)
            if not m:
                continue
            title = m.group(1).strip()
            if not title:
                continue
            pub_ts = 0
            pub_date = ""
            pd = re.search(r"<pubDate>(.*?)</pubDate>", item)
            if pd:
                try:
                    _dt = parsedate_to_datetime(pd.group(1).strip())
                    pub_ts = _dt.timestamp()
                    pub_date = _dt.strftime("%Y-%m-%d")
                except Exception:
                    pass
            parsed.append((pub_ts, pub_date, title))
        parsed.sort(key=lambda x: x[0], reverse=True)  # newest first
        if with_dates:
            return [(d, t) for _ts, d, t in parsed[:max_items]]
        return [t for _ts, _d, t in parsed[:max_items]]
    except Exception:
        return []



def _fetch_yfinance_news(ticker: str, max_items: int = 8) -> list[str]:
    """Secondary: yfinance .news — often empty/wrong for NSE tickers, used as fallback."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        items = t.news or []
        parsed = []
        for item in items:
            # yfinance changed schema: try new path then old path
            title = (
                item.get("content", {}).get("title")
                or item.get("title")
                or ""
            )
            if not title:
                continue
            pub_ts = (
                item.get("content", {}).get("pubDate")
                or item.get("providerPublishTime")
                or 0
            )
            try:
                pub_ts = float(pub_ts)
            except (TypeError, ValueError):
                pub_ts = 0
            parsed.append((pub_ts, title))
        parsed.sort(key=lambda x: x[0], reverse=True)  # newest first
        return [title for _, title in parsed[:max_items]]
    except Exception:
        return []


# ── NEWS FETCH ────────────────────────────────────────────────────────────────
def fetch_and_analyze(ticker: str, company: str = "", max_items: int = 8) -> dict:
    """
    Fetch news for ticker and run sentiment analysis.

    Strategy:
      1. Google News RSS using company name (most accurate for NSE stocks)
      2. yfinance .news as fallback (often wrong/empty for Indian tickers)
    """
    key = ticker.upper()

    # Fast read — no lock needed for cache hits (reads are safe)
    entry = _NEWS_CACHE.get(key)
    if entry and time.time() - entry["ts"] < _NEWS_CACHE_TTL:
        return entry["data"]

    # Per-ticker lock: only 1 thread fetches news per ticker.
    # Without this, all 4 TF threads for the same stock call the LLM
    # simultaneously → immediate Cerebras/OpenRouter rate-limit → ai_unavailable.
    _lock = _get_news_lock(key)
    with _lock:
        # Double-check after acquiring lock — another thread may have just fetched.
        entry = _NEWS_CACHE.get(key)
        if entry and time.time() - entry["ts"] < _NEWS_CACHE_TTL:
            return entry["data"]

        # Build the search query: prefer company name, fall back to bare ticker
        bare = ticker.replace(".NS", "").replace(".BO", "")
        search_name = company.strip() if company.strip() else bare
        google_query = f"{search_name} stock NSE"

        # 1. Google News RSS (primary — searches by company name), newest-first with dates
        dated = _fetch_google_news(google_query, max_items, with_dates=True)
        headlines = [t for _d, t in dated]

        # 2. yfinance fallback if Google returned nothing
        if not headlines:
            headlines = _fetch_yfinance_news(ticker, max_items)
            dated = [("", h) for h in headlines]

        sentiment = analyze_news(headlines, ticker, company or bare, dated=dated)
        sentiment["headlines"] = headlines[:5]
        sentiment["headlines_dated"] = [{"date": d, "title": t} for d, t in dated[:5]]
        # Newest publish date across the fetched window (surfaced in the UI as "as of").
        sentiment["latest_date"] = next((d for d, _t in dated if d), "")
        _NEWS_CACHE[key] = {"ts": time.time(), "data": sentiment}
        return sentiment


# ── DATED / AS-OF NEWS (historical backfill, no lookahead) ────────────────────
# Google News RSS accepts `after:YYYY-MM-DD before:YYYY-MM-DD` operators, so we can
# fetch the COMPANY-SPECIFIC news that was published in the week (or any window) BEFORE
# a past date — exactly what a backtest needs to test "does news help?" without peeking
# at the future. Company-catalyst framing (orders, results, war/geopolitics affecting the
# company) comes from the same LLM prompt used live.
def _fetch_google_news_dated(query: str, start_date: str, end_date: str,
                             max_items: int = 8) -> list[tuple[str, str]]:
    """Return [(pubDate 'YYYY-MM-DD', title)] for `query` published in [start_date, end_date).

    `end_date` is EXCLUSIVE — items are additionally filtered so pubDate.date() < end_date,
    which guarantees no lookahead when end_date is the prediction day."""
    q = f"{query} after:{start_date} before:{end_date}"
    url = (f"https://news.google.com/rss/search"
           f"?q={urllib.parse.quote(q)}&hl=en-IN&gl=IN&ceid=IN:en")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return []
    out = []
    for item in re.findall(r"<item>(.*?)</item>", raw, re.DOTALL):
        m = re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>", item) or re.search(r"<title>(.*?)</title>", item)
        if not m:
            continue
        title = m.group(1).strip()
        pd_m = re.search(r"<pubDate>(.*?)</pubDate>", item)
        pub_date = ""
        if pd_m:
            try:
                pub_date = parsedate_to_datetime(pd_m.group(1).strip()).strftime("%Y-%m-%d")
            except Exception:
                pub_date = ""
        # Strict no-lookahead guard: drop anything dated on/after end_date.
        if pub_date and pub_date >= end_date:
            continue
        if title:
            out.append((pub_date, title))
    out.sort(key=lambda x: x[0], reverse=True)  # newest first
    return out[:max_items]


def _asof_cache_conn(cache_path: str):
    import sqlite3, os as _os
    _os.makedirs(_os.path.dirname(cache_path), exist_ok=True)
    con = sqlite3.connect(cache_path)
    con.execute("CREATE TABLE IF NOT EXISTS news_asof ("
                "k TEXT PRIMARY KEY, data TEXT)")
    return con


def fetch_news_asof(ticker: str, company: str = "", asof_date: str = "",
                    lookback_days: int = 7, use_llm: bool = False,
                    cache_path: str | None = None, max_items: int = 8) -> dict:
    """Company news published in the `lookback_days` window BEFORE `asof_date` (exclusive).

    Returns {label, score, summary, key_headline, headlines, source, asof, n}. Safe for
    backtests: no news dated on/after `asof_date` is included. Set `use_llm=False` (default)
    for the fast keyword scorer (no API calls — suitable for bulk backfill); `use_llm=True`
    uses the same LLM analyst as the live path (better catalyst reading, costs a call).
    Pass `cache_path` (e.g. research/cache/news_asof.sqlite) to memoize on disk."""
    from datetime import datetime, timedelta
    asof = asof_date[:10]
    ck = f"{ticker.upper()}|{asof}|{lookback_days}|{'llm' if use_llm else 'kw'}"
    con = None
    if cache_path:
        try:
            con = _asof_cache_conn(cache_path)
            row = con.execute("SELECT data FROM news_asof WHERE k=?", (ck,)).fetchone()
            if row:
                con.close()
                return json.loads(row[0])
        except Exception:
            con = None
    try:
        start = (datetime.strptime(asof, "%Y-%m-%d") - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    except Exception:
        start = asof
    bare = ticker.replace(".NS", "").replace(".BO", "")
    name = company.strip() or bare
    dated = _fetch_google_news_dated(f"{name} stock NSE", start, asof, max_items)
    headlines = [t for _d, t in dated]
    if not headlines:
        result = {"label": "NEUTRAL", "score": 0, "summary": "No news in window.",
                  "key_headline": "", "source": "none"}
    elif use_llm:
        result = _llm_analyze(headlines, ticker, name) or _keyword_fallback(headlines)
    else:
        result = _keyword_fallback(headlines)
    result["headlines"] = headlines[:5]
    result["asof"] = asof
    result["n"] = len(headlines)
    if con is not None:
        try:
            con.execute("INSERT OR REPLACE INTO news_asof(k, data) VALUES(?, ?)",
                        (ck, json.dumps(result)))
            con.commit()
            con.close()
        except Exception:
            pass
    return result


# ── QUICK SELF-TEST ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    test_headlines = [
        "Reliance Industries Q4 profit beats estimates, revenue up 12%",
        "Reliance Jio adds 8 million subscribers in March quarter",
        "RIL announces ₹75,000 Cr capital expenditure plan for FY27",
    ]
    result = analyze_news(test_headlines, "RELIANCE.NS", "Reliance Industries")
    print(f"Sentiment: {result['label']} (score: {result['score']})")
    print(f"Summary:   {result['summary']}")
    print(f"Source:    {result['source']}")
