"""
social_sentiment.py — Reddit + StockTwits sentiment fetcher for NSE stocks.

Fetches recent posts/messages from Indian investment communities and formats
them as text blocks for injection into LLM prompts (bull/bear debate context).

Data sources:
  • Reddit  — r/IndiaInvestments, r/IndianStockMarket, r/Nifty (RSS, no API key)
  • StockTwits — public stream API (limited NSE coverage; graceful fallback)
"""

from __future__ import annotations
import json
import logging
import re
import time
import urllib.parse
import urllib.request

_TIMEOUT = 6  # seconds per request
_SOCIAL_CACHE: dict[str, tuple[str, float]] = {}
_SOCIAL_TTL = 300  # 5-minute cache — social posts don't change per-minute

# Better search terms for Reddit than raw tickers (people post "Reliance" not "RELIANCE.NS")
_SEARCH_OVERRIDES: dict[str, str] = {
    "HDFCBANK":   "HDFC Bank",
    "ICICIBANK":  "ICICI Bank",
    "KOTAKBANK":  "Kotak Bank",
    "AXISBANK":   "Axis Bank",
    "SBIN":       "SBI State Bank India",
    "INDUSINDBK": "IndusInd Bank",
    "BANKBARODA": "Bank of Baroda",
    "TCS":        "TCS Tata Consultancy",
    "INFY":       "Infosys",
    "WIPRO":      "Wipro",
    "HCLTECH":    "HCL Technologies",
    "TECHM":      "Tech Mahindra",
    "LTIM":       "LTIMindtree",
    "PERSISTENT": "Persistent Systems",
    "COFORGE":    "Coforge",
    "SUNPHARMA":  "Sun Pharma",
    "DRREDDY":    "Dr Reddys",
    "CIPLA":      "Cipla",
    "DIVISLAB":   "Divi Laboratories",
    "RELIANCE":   "Reliance Industries",
    "ONGC":       "ONGC oil gas",
    "BPCL":       "BPCL petroleum",
    "TATASTEEL":  "Tata Steel",
    "JSWSTEEL":   "JSW Steel",
    "HINDALCO":   "Hindalco",
    "VEDL":       "Vedanta",
    "MARUTI":     "Maruti Suzuki",
    "TATAMOTORS": "Tata Motors",
    "M&M":        "Mahindra",
    "BAJAJ-AUTO": "Bajaj Auto",
    "TITAN":      "Titan Company",
    "HINDUNILVR": "HUL Hindustan Unilever",
    "NESTLEIND":  "Nestle India",
    "BRITANNIA":  "Britannia",
    "LT":         "Larsen Toubro L&T",
    "NTPC":       "NTPC power",
    "POWERGRID":  "Power Grid India",
    "ADANIPORTS": "Adani Ports",
    "BAJFINANCE": "Bajaj Finance",
    "BAJAJFINSV": "Bajaj Finserv",
}


def _strip_html(text: str) -> str:
    """Decode HTML entities first, then remove HTML/XML tags."""
    # Decode entities before stripping tags (RSS body is double-encoded)
    for esc, char in [
        ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
        ("&#39;", "'"), ("&quot;", '"'), ("&nbsp;", " "),
    ]:
        text = text.replace(esc, char)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)  # strip comments
    text = re.sub(r"<[^>]+>", " ", text)                      # strip tags
    return " ".join(text.split())


def fetch_reddit_sentiment(ticker: str, company: str, max_posts: int = 5) -> str:
    """
    Fetch recent posts from Indian investment subreddits via RSS search.
    No API key required. Returns formatted text block or "" on failure.
    """
    base = ticker.replace(".NS", "").replace(".BO", "").upper()
    # Use hardcoded override → full company name (2-3 words) → bare ticker as last resort.
    # Bare ticker alone (e.g. "SCI", "ITC", "SAIL") matches unrelated US/global companies on Reddit.
    if _SEARCH_OVERRIDES.get(base):
        search_term = _SEARCH_OVERRIDES[base]
    elif company and len(company.split()) >= 2:
        words = company.split()
        search_term = " ".join(words[:3])  # e.g. "Shipping Corporation India"
    else:
        search_term = base

    subreddits = ["IndiaInvestments", "IndianStockMarket", "Nifty"]
    posts: list[str] = []
    seen: set[str] = set()

    for sub in subreddits:
        if len(posts) >= max_posts:
            break
        try:
            encoded = urllib.parse.quote(search_term)
            url = (
                f"https://www.reddit.com/r/{sub}/search.rss"
                f"?q={encoded}&t=week&sort=new&limit=5"
            )
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; PaperTradeResearch/1.0)",
                    "Accept": "application/rss+xml,application/xml",
                },
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                content = resp.read().decode("utf-8", errors="replace")

            # Atom feed uses <entry> blocks
            entries = re.findall(r"<entry>(.*?)</entry>", content, re.DOTALL)
            for entry in entries:
                if len(posts) >= max_posts:
                    break
                title_m   = re.search(r"<title[^>]*>(.*?)</title>", entry, re.DOTALL)
                date_m    = re.search(r"<published>(.*?)</published>", entry)
                content_m = re.search(r"<content[^>]*>(.*?)</content>", entry, re.DOTALL)
                if not title_m:
                    continue
                title = _strip_html(title_m.group(1))[:120]
                if not title or title in seen:
                    continue
                seen.add(title)
                date = (date_m.group(1) if date_m else "")[:10]
                body = _strip_html(content_m.group(1) if content_m else "")[:180]
                posts.append(f"  [{date} · r/{sub}] {title}\n    {body}")
        except Exception as exc:
            logging.debug("Reddit fetch failed r/%s query=%s: %s", sub, search_term, exc)

    if not posts:
        return ""

    return (
        f"Reddit ({len(posts)} posts — r/IndiaInvestments, r/IndianStockMarket, r/Nifty — last 7 days):\n"
        + "\n".join(posts)
    )


def fetch_stocktwits_sentiment(ticker: str) -> str:
    """
    Fetch StockTwits stream for the ticker.
    NSE coverage is limited to large-caps that trade on US markets (ADRs).
    Returns formatted text block or "" when no messages found.
    """
    base = ticker.replace(".NS", "").replace(".BO", "").upper()
    try:
        url = f"https://api.stocktwits.com/api/2/streams/symbol/{base}.json?limit=20"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; PaperTradeResearch/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        messages = data.get("messages", [])
        if not messages:
            return ""

        bull = sum(
            1 for m in messages
            if (m.get("entities") or {}).get("sentiment", {}).get("basic") == "Bullish"
        )
        bear = sum(
            1 for m in messages
            if (m.get("entities") or {}).get("sentiment", {}).get("basic") == "Bearish"
        )
        total = len(messages)
        bull_pct = round(bull / total * 100) if total else 0

        lines = [
            f"StockTwits ({total} messages — {bull} bullish / {bear} bearish — {bull_pct}% bull):"
        ]
        for msg in messages[:5]:
            sentiment_tag = (msg.get("entities") or {}).get("sentiment", {}).get("basic", "")
            body = (msg.get("body") or "")[:160]
            tag = f"[{sentiment_tag}] " if sentiment_tag else ""
            lines.append(f"  {tag}{body}")

        return "\n".join(lines)
    except Exception as exc:
        logging.debug("StockTwits fetch failed for %s: %s", base, exc)
        return ""


def fetch_social_sentiment(ticker: str, company: str) -> str:
    """
    Combined Reddit + StockTwits sentiment block.
    Results cached for 5 minutes per ticker to avoid serial Reddit latency on repeated calls.
    """
    cache_key = f"{ticker}::{company}"
    now = time.time()
    if cache_key in _SOCIAL_CACHE:
        cached_result, cached_ts = _SOCIAL_CACHE[cache_key]
        if (now - cached_ts) < _SOCIAL_TTL:
            return cached_result

    reddit = fetch_reddit_sentiment(ticker, company)
    twits  = fetch_stocktwits_sentiment(ticker)

    parts = [p for p in [reddit, twits] if p]
    result = "(No social sentiment data found for this ticker)" if not parts else "\n\n".join(parts)
    _SOCIAL_CACHE[cache_key] = (result, now)
    return result
