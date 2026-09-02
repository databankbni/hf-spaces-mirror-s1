"""
providers/openrss/client.py
─────────────────────────────────────────────────────────────────────────────
The OpenRSS Provider for Segmento Pulse.

What this does:
    Fetches RSS feeds for websites that don't publish their own RSS feed,
    by using OpenRSS.org as a free feed generation service.

    Target blogs:
        dev.to            → openrss.org/dev.to
        hashnode.com      → openrss.org/hashnode.com
        github.com/blog   → openrss.org/github.com/blog

Free. No API key. No daily limits. Just XML text.

── THE IP BAN RISK AND HOW WE SOLVE IT ─────────────────────────────────────

OpenRSS.org says clearly in their documentation:
    "Aggregator use is not officially supported."
    "We will block IP addresses that ignore our Cache-Control headers."

A normal aggregator calls all its sources every hour.
If we did that with OpenRSS, we would get IP-banned within a day.

Our fix: A strict 60-minute (3600 second) internal cooldown timer.

    How it works:
        - When the provider is first created, self.last_fetched = 0
        - When fetch_news() is called, it first checks:
              time.time() - self.last_fetched < COOLDOWN_SECONDS?
        - If YES  → return [] immediately, do not touch the network at all
        - If NO   → update self.last_fetched, then fetch

    This guarantees that OpenRSS sees at most ONE request per hour,
    per URL, from our server — which respects their Cache-Control policy.

    Because our scheduler runs many categories per hour, without this timer,
    OpenRSS would get hit dozens of times per hour. With the timer, it gets
    hit at most once every 60 minutes regardless of how many categories fire.

── WHY WE DO NOT USE parse_provider_rss() ──────────────────────────────────

The user instruction suggests using parse_provider_rss() from rss_parser.py.
We discovered in Phase 4 (direct_rss provider) that this function hardcodes:

    category = f'cloud-{provider}'

on EVERY article it creates. If we passed "dev.to" as the provider name,
every article from dev.to would get category='cloud-dev.to'. Appwrite
would not know this collection exists, silently dropping those articles.

Decision (consistent with Phase 4): We use feedparser directly and borrow
only the two STATELESS helper methods from rss_parser.py:
    - _extract_image_from_entry()  → extracts images cleanly
    - _parse_date()                → handles all date format variants

This is the same engineering decision made in Phase 4 for direct_rss,
and it was reviewed and approved by the lead architect.
"""

# ── Standard Library ──────────────────────────────────────────────────────────
import asyncio
import logging
import re
import time
from typing import List

# ── Third-party (already in requirements.txt) ─────────────────────────────────
import feedparser      # XML/RSS feed parser — already used by rss_parser.py
import httpx           # Async HTTP client

# ── Internal ──────────────────────────────────────────────────────────────────
from app.services.providers.base import NewsProvider
from app.services.rss_parser import RSSParser   # Borrowed for helper methods only
from app.models import Article
# Phase 15: Import the Redis-backed state utility so the cooldown
# timer survives Hugging Face Space restarts.
from app.services.utils.provider_state import (
    get_provider_timestamp,
    set_provider_timestamp,
)

logger = logging.getLogger(__name__)

# ── OpenRSS Feed Registry ──────────────────────────────────────────────────────
#
# Each entry is a tuple of (openrss_url, source_name).
# source_name appears in the Pulse UI next to each article headline.
#
# To add more feeds in the future, just add a new tuple here.
# The fetch loop picks it up automatically — no other code changes needed.
#
# ⚠️ IMPORTANT: Be conservative. Every URL here gets fetched once per cooldown
# window. Adding too many URLs consumes more of our cooldown budget.
#
OPENRSS_FEEDS: List[tuple] = [
    ("https://openrss.org/dev.to",          "dev.to"),
    ("https://openrss.org/hashnode.com",    "Hashnode"),
    ("https://openrss.org/github.com/blog", "GitHub Blog"),
]

# ── Cooldown Timer ─────────────────────────────────────────────────────────────
# 3600 seconds = 60 minutes.
# This is the minimum safe polling interval as per OpenRSS's documentation.
# DO NOT reduce this value. Doing so risks an IP ban on Segmento Pulse's server.
COOLDOWN_SECONDS = 3600

# HTTP request timeout. OpenRSS is a third-party service; give it enough time.
HTTP_TIMEOUT_SECONDS = 10.0

# Max articles to take from each individual feed per cooldown window.
MAX_ARTICLES_PER_FEED = 10


class OpenRSSProvider(NewsProvider):
    """
    Fetches RSS feeds from dev.to, Hashnode, and GitHub Blog via OpenRSS.org.

    Free. No API key. Strictly rate-self-limited to once per 60 minutes.
    Runs for ALL categories in FREE_SOURCES — no category guardrail needed
    because the cooldown timer is the primary protection mechanism.

    Usage (wired in Phase 9):
        provider = OpenRSSProvider()
        articles = await provider.fetch_news(category="ai", limit=30)
    """

    def __init__(self):
        # Free provider — no API key, no daily limit.
        super().__init__(api_key=None)
        self.daily_limit = 0

        # Phase 15: The cooldown timer has moved to Redis.
        # self.last_fetched is kept as a local fallback cache: if Redis is
        # unreachable on startup, we fall back to 0.0 (fail-open — allowed
        # to run). On every successful Redis read in fetch_news(), this
        # local value is updated so it stays in sync.
        self.last_fetched: float = 0.0

        # Borrow stateless helpers from the existing RSSParser.
        # We do NOT call parse_provider_rss() — see module docstring above.
        self._rss_helpers = RSSParser()

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN ENTRY POINT — called by the aggregator's FREE PARALLEL RUN
    # ─────────────────────────────────────────────────────────────────────────

    async def fetch_news(self, category: str, limit: int = 30) -> List[Article]:
        """
        Fetch articles from all OpenRSS feeds — but only if 60 minutes have
        passed since the last successful fetch.

        Args:
            category (str): The aggregator's category — tagged on every article.
                            The keyword gate filters irrelevant articles downstream.
            limit (int):    Soft cap on total articles to return.

        Returns:
            List[Article]: Combined articles from all feeds.
                           Returns [] immediately if we are still in cooldown.
        """
        # ── SAFETY CHECK: Are we still in the cooldown window? ────────────────
        # Phase 15: Read the last-fetch timestamp from Redis instead of RAM.
        #
        # Before Phase 15:  self.last_fetched (pure RAM, wiped on restart)
        # After  Phase 15:  Redis key "provider:state:openrss:last_fetch"
        #                   survives restarts, deployments, and container OOM kills.
        #
        # If Redis is down: get_provider_timestamp returns 0.0 (fail-open).
        # This means the provider is allowed to run. One extra OpenRSS call
        # is far safer than permanently blocking the provider because Redis
        # happened to be unreachable for 10 seconds during a cold boot.
        redis_last_fetched = await get_provider_timestamp("openrss")

        # Keep the local RAM value in sync for logging and debugging purposes.
        # This does NOT affect the cooldown logic — only redis_last_fetched does.
        self.last_fetched = redis_last_fetched

        seconds_since_last_fetch = time.time() - redis_last_fetched
        if seconds_since_last_fetch < COOLDOWN_SECONDS:
            minutes_remaining = int(
                (COOLDOWN_SECONDS - seconds_since_last_fetch) / 60
            )
            logger.info(
                "[OpenRSS] Cooldown active — %d minute(s) remaining before next fetch. "
                "Skipping to protect against IP ban.",
                minutes_remaining
            )
            return []

        # ── OK to fetch: save the new timestamp to Redis BEFORE hitting the network ──
        # We write BEFORE the network calls, not after. Here is why:
        # If we save the timestamp AFTER and the fetch crashes halfway through,
        # the next scheduler cycle will see "last_fetched = 0" and fire again
        # immediately — hammering OpenRSS with rapid retries. That is the
        # exact behaviour that triggers IP bans.
        # By writing the timestamp FIRST, any crash still waits the full
        # 60 minutes before the next attempt. Better to miss one batch than
        # to risk a permanent IP ban.
        current_time = time.time()
        self.last_fetched = current_time   # Keep RAM copy in sync
        await set_provider_timestamp("openrss", current_time)

        logger.info(
            "[OpenRSS] Cooldown clear (Redis-backed). Starting fetch of %d feeds...",
            len(OPENRSS_FEEDS)
        )


        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:

                # Build one fetch task per feed URL — all fire simultaneously.
                fetch_tasks = [
                    self._fetch_and_parse_feed(client, url, source_name, category)
                    for url, source_name in OPENRSS_FEEDS
                ]

                # Wait for all feeds to complete at the same time.
                results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

                # Combine all articles from all feeds.
                all_articles: List[Article] = []
                for (_, source_name), result in zip(OPENRSS_FEEDS, results):
                    if isinstance(result, Exception):
                        logger.warning(
                            f"[OpenRSS] [{source_name}] Feed fetch failed: {result}"
                        )
                    elif isinstance(result, list):
                        all_articles.extend(result)

                logger.info(
                    f"[OpenRSS] Collected {len(all_articles)} articles "
                    f"from {len(OPENRSS_FEEDS)} feeds for category='{category}'"
                )
                return all_articles

        except Exception as e:
            logger.error(f"[OpenRSS] Unexpected error: {e}", exc_info=True)
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    async def _fetch_and_parse_feed(
        self,
        client: httpx.AsyncClient,
        url: str,
        source_name: str,
        category: str,
    ) -> List[Article]:
        """
        Fetch one OpenRSS feed URL and parse its XML into Article objects.

        Args:
            client (httpx.AsyncClient): Shared HTTP client from fetch_news().
            url (str):         Full OpenRSS URL (e.g., openrss.org/dev.to).
            source_name (str): Human-readable label (e.g., "dev.to").
            category (str):    The aggregator's category — tagged on each article.

        Returns:
            List[Article]: Parsed articles. Returns [] on any failure.
        """
        try:
            response = await client.get(
                url,
                headers={
                    "User-Agent": "SegmentoPulse-RSS-Reader/1.0",
                    # Sending Cache-Control: no-cache would be rude.
                    # We rely on our cooldown timer to manage freshness,
                    # not by asking OpenRSS to skip their cache.
                },
                follow_redirects=True,
            )

            if response.status_code == 429:
                # If OpenRSS sends a 429 despite our cooldown, double the wait
                # by resetting the timer to now (conservative recovery).
                self.handle_429()
                return []

            if response.status_code != 200:
                logger.warning(
                    f"[OpenRSS] [{source_name}] HTTP {response.status_code} — skipping."
                )
                return []

            xml_text = response.text

        except httpx.TimeoutException:
            logger.warning(f"[OpenRSS] [{source_name}] Timed out — skipping.")
            return []
        except Exception as e:
            logger.warning(f"[OpenRSS] [{source_name}] Fetch error: {e}")
            return []

        return self._parse_feed_xml(xml_text, source_name, category)

    def _parse_feed_xml(
        self,
        xml_text: str,
        source_name: str,
        category: str,
    ) -> List[Article]:
        """
        Parse raw XML from an OpenRSS feed into Article objects.

        Uses feedparser directly — not parse_provider_rss() — because
        parse_provider_rss hardcodes category='cloud-{provider}'.
        We borrow _extract_image_from_entry and _parse_date for consistency.

        Args:
            xml_text (str):    Raw XML string from the HTTP response.
            source_name (str): The blog name (e.g., "dev.to").
            category (str):    Aggregator category — tagged on every article.

        Returns:
            List[Article]: Parsed article objects.
        """
        try:
            feed = feedparser.parse(xml_text)
        except Exception as e:
            logger.warning(f"[OpenRSS] [{source_name}] feedparser failed: {e}")
            return []

        articles: List[Article] = []

        for entry in feed.entries[:MAX_ARTICLES_PER_FEED]:

            # ── Title ────────────────────────────────────────────────────
            title = (entry.get("title") or "").strip()
            if not title:
                continue

            # ── URL ──────────────────────────────────────────────────────
            url = (entry.get("link") or "").strip()
            if not url or not url.startswith("http"):
                continue

            # ── Description ───────────────────────────────────────────────
            raw_desc = entry.get("summary", "") or ""
            description = re.sub(r"<[^>]+>", "", raw_desc).strip()
            if len(description) > 200:
                description = description[:200] + "..."

            # ── Image URL ─────────────────────────────────────────────────
            # Reuse rss_parser's helper — checks media:content, enclosures, etc.
            image_url = self._rss_helpers._extract_image_from_entry(entry)

            # ── Published Date ────────────────────────────────────────────
            # Reuse rss_parser's _parse_date — handles all date format variants.
            raw_date = entry.get("published", "") or ""
            published_at = self._rss_helpers._parse_date(raw_date)

            # ── Build Article ─────────────────────────────────────────────
            try:
                article = Article(
                    title=title,
                    description=description,
                    url=url,
                    image_url=image_url,
                    published_at=published_at,
                    source=source_name,
                    # ── ROUTING RULE ──────────────────────────────────────
                    # Tag with the aggregator's category so the pipeline
                    # can route this correctly. Unknown categories safely
                    # fall back to the default 'News Articles' collection.
                    category=category,
                )
                articles.append(article)

            except Exception as e:
                logger.debug(
                    f"[OpenRSS] [{source_name}] Skipped entry '{title[:50]}': {e}"
                )
                continue

        logger.info(f"[OpenRSS] [{source_name}] Parsed {len(articles)} articles.")
        return articles
