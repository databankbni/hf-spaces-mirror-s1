"""
providers/sauravkanchan/client.py
─────────────────────────────────────────────────────────────────────────────
The SauravKanchan Static JSON Provider for Segmento Pulse.

What this does:
    Reads two static JSON files hosted on GitHub Pages by a developer named
    Saurav Kanchan. These files are automatically updated by a GitHub Action
    that scrapes the top tech headlines from NewsAPI.org and saves them as
    plain JSON files anyone can read for free.

    We fetch TWO files at the same time:
        in.json → Top tech headlines from India
        us.json → Top tech headlines from the United States

    Fetching both simultaneously means we get double the volume and double
    the geographic coverage in roughly the same time as fetching just one.

Why this is zero-cost and zero-rate-limit:
    These are not API calls — they are just reading a text file from the
    internet. GitHub Pages has no rate limit for public static file reads.
    No API key. No signup. No credit card. Completely free forever.

Why the data is high quality:
    The JSON structure is identical to the paid NewsAPI.org format, which
    means we get proper titles, descriptions, image URLs, publication dates,
    and source names — all cleanly pre-formatted for us.

Freshness note (important):
    Saurav's GitHub Action runs on its own schedule — typically a few times
    per day. This means some articles in the file may be several hours old
    by the time we read them. That is perfectly fine. Our freshness gate in
    data_validation.is_valid_article() will automatically reject anything
    older than our midnight IST cutoff. We never need to pre-filter here.

Client-side constraint note:
    These are static files — we cannot add query parameters. We get
    whatever is in the file. The keyword gate handles topic filtering.
"""

# ── Standard Library ──────────────────────────────────────────────────────────
import asyncio
import logging
import time
from typing import List, Optional

# ── Third-party (already in requirements.txt) ─────────────────────────────────
import httpx                            # Async HTTP client

# ── Internal ──────────────────────────────────────────────────────────────────
from app.services.providers.base import NewsProvider, ProviderStatus
from app.models import Article

logger = logging.getLogger(__name__)

# ── Static JSON URLs ───────────────────────────────────────────────────────────
#
# Both files are hosted on GitHub Pages and updated automatically by a
# GitHub Action. They follow the exact same JSON structure as NewsAPI.org.
#
# To change regions or add new ones (e.g., gb.json), just add a new entry here.
# The fetch loop picks it up automatically.
#
STATIC_FEED_URLS: List[tuple] = [
    (
        "https://saurav.tech/NewsAPI/top-headlines/category/technology/in.json",
        "in",       # Region code — used only in log messages
    ),
    (
        "https://saurav.tech/NewsAPI/top-headlines/category/technology/us.json",
        "us",       # Region code — used only in log messages
    ),
]

# HTTP request timeout. Static files are fast, but we keep this generous
# because GitHub Pages occasionally has slow cold starts.
HTTP_TIMEOUT_SECONDS = 10.0

# Max articles to take from each regional file.
# 100 articles per file × 2 files = up to 200 raw articles per call.
# The freshness gate will reject most of the older ones, leaving us
# with the freshest and most relevant subset.
MAX_ARTICLES_PER_REGION = 100


class SauravKanchanProvider(NewsProvider):
    """
    Reads top tech headlines from two static JSON files on GitHub Pages.

    Covers India (in.json) and the United States (us.json) simultaneously.
    Free. Zero rate limits. No API key required.
    Gated behind GENERAL_TECH_CATEGORIES in the aggregator.

    Usage (wired in Phase 7):
        provider = SauravKanchanProvider()
        articles = await provider.fetch_news(category="ai", limit=50)
    """

    def __init__(self):
        # Free provider — no key, no daily limit.
        super().__init__(api_key=None)
        self.daily_limit = 0

        # Phase 17: Fetch-Once, Fan-Out cache
        #
        # Saurav's JSON files contain a snapshot of top India + US tech headlines.
        # The file contents are the same regardless of whether we ask for
        # category "ai" or category "cloud-gcp" — the files don't change.
        # Without a cache: the aggregator downloads IN + US files 22 separate
        # times (once per category), wasting bandwidth and GitHub's servers.
        # With a cache: downloaded once, stored here for 45 minutes.
        #
        # We store the FINAL Pydantic Article objects, not the raw JSON.
        # This means zero re-parsing on cache hits — callers get typed objects.
        self._cached_articles: List[Article] = []
        self._cache_time: float = 0.0

        # The lock prevents the "thundering herd" problem:
        # If 5 categories hit this provider at the exact same millisecond
        # (which asyncio.gather() will do), only the first one fetches.
        # The other 4 wait patiently at the lock, then return from cache.
        self._lock = asyncio.Lock()

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN ENTRY POINT — called by the aggregator's FREE PARALLEL RUN
    # ─────────────────────────────────────────────────────────────────────────

    async def fetch_news(self, category: str, limit: int = 50) -> List[Article]:
        """
        Fetch tech headlines from the India and US static JSON files.

        Both files are downloaded at the same time using asyncio.gather().
        Their article lists are then combined into one big list and returned.

        Args:
            category (str): The aggregator's category string (e.g., "ai").
                            We tag every article with it. The keyword gate
                            later filters which ones are truly relevant.
            limit (int):    Soft cap on total articles to return.
                            The per-region MAX_ARTICLES_PER_REGION cap is
                            the real control lever.

        Returns:
            List[Article]: Combined articles from IN + US feeds.
                           Returns [] if both feeds fail.
        """
        # ── Phase 17: Cache check (OUTER) ─────────────────────────────────────
        CACHE_TTL_SECONDS = 2700   # 45 minutes

        if time.time() - self._cache_time < CACHE_TTL_SECONDS and self._cached_articles:
            logger.debug(
                "[SauravKanchan] Cache hit — returning %d cached articles for category='%s'. "
                "No HTTP calls made.",
                len(self._cached_articles), category
            )
            return self._cached_articles

        # ── Cache stale or empty: acquire the lock and fetch ───────────────────
        async with self._lock:

            # ── Cache check (INNER) — double-checked locking ──────────────
            if time.time() - self._cache_time < CACHE_TTL_SECONDS and self._cached_articles:
                logger.debug(
                    "[SauravKanchan] Cache hit after lock — returning %d cached articles.",
                    len(self._cached_articles)
                )
                return self._cached_articles

            logger.info("[SauravKanchan] Cache stale/empty. Fetching IN + US JSON files...")

            try:
                async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:

                    # Build one fetch task per regional URL — both fire at the same time.
                    fetch_tasks = [
                        self._fetch_single_region(client, url, region_code, category)
                        for url, region_code in STATIC_FEED_URLS
                    ]

                    # Wait for both regional fetches to complete simultaneously.
                    results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

                    # Combine articles from both regions into one flat list.
                    all_articles: List[Article] = []
                    for (_, region_code), result in zip(STATIC_FEED_URLS, results):
                        if isinstance(result, Exception):
                            logger.warning(
                                f"[SauravKanchan] [{region_code.upper()}] "
                                f"Fetch failed: {result}"
                            )
                        elif isinstance(result, list):
                            all_articles.extend(result)

                    logger.info(
                        "[SauravKanchan] Fetched %d articles from %d regions. "
                        "Caching for 45 minutes.",
                        len(all_articles), len(STATIC_FEED_URLS)
                    )

                    # Store the fully-mapped Pydantic Article objects in the cache.
                    # Future category calls get typed objects with zero re-parsing.
                    self._cached_articles = all_articles
                    self._cache_time = time.time()
                    return all_articles

            except Exception as e:
                logger.error(f"[SauravKanchan] Unexpected error: {e}", exc_info=True)
                return []

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    async def _fetch_single_region(
        self,
        client: httpx.AsyncClient,
        url: str,
        region_code: str,
        category: str,
    ) -> List[Article]:
        """
        Download one regional JSON file and parse its articles.

        Args:
            client (httpx.AsyncClient): Shared HTTP client from fetch_news().
            url (str):                  The full static JSON URL to fetch.
            region_code (str):          Short label for logging (e.g., "us", "in").
            category (str):             The aggregator's category — tagged on articles.

        Returns:
            List[Article]: Parsed articles from this region. Returns [] on failure.
        """
        try:
            response = await client.get(
                url,
                headers={"User-Agent": "SegmentoPulse-Ingestion/1.0"},
                follow_redirects=True,
            )

            if response.status_code == 429:
                self.handle_429()
                return []

            if response.status_code != 200:
                logger.warning(
                    f"[SauravKanchan] [{region_code.upper()}] "
                    f"HTTP {response.status_code} — skipping."
                )
                return []

            data = response.json()

        except httpx.TimeoutException:
            logger.warning(
                f"[SauravKanchan] [{region_code.upper()}] Timed out — skipping."
            )
            return []
        except Exception as e:
            logger.warning(
                f"[SauravKanchan] [{region_code.upper()}] Fetch error: {e}"
            )
            return []

        # The JSON has the same shape as NewsAPI.org:
        # { "status": "ok", "totalResults": 20, "articles": [ ... ] }
        raw_articles = data.get("articles", [])

        if not isinstance(raw_articles, list) or not raw_articles:
            logger.info(
                f"[SauravKanchan] [{region_code.upper()}] "
                "No articles found in response."
            )
            return []

        articles = self._map_articles(
            raw_articles[:MAX_ARTICLES_PER_REGION],
            region_code,
            category,
        )
        logger.info(
            f"[SauravKanchan] [{region_code.upper()}] "
            f"Parsed {len(articles)} articles."
        )
        return articles

    def _map_articles(
        self,
        raw_articles: list,
        region_code: str,
        category: str,
    ) -> List[Article]:
        """
        Convert raw NewsAPI-format JSON items into Segmento Pulse Article objects.

        The field names in this JSON are camelCase (like JavaScript), so:
            urlToImage  →  image_url
            publishedAt →  published_at
            source.name →  source

        Everything else maps directly.

        Args:
            raw_articles (list): The 'articles' array from the JSON response.
            region_code (str):   "in" or "us" — appended to the source name
                                 so we know where the article came from.
            category (str):      The aggregator's category string.

        Returns:
            List[Article]: Clean Article objects for the pipeline.
        """
        articles: List[Article] = []

        for item in raw_articles:
            if not isinstance(item, dict):
                continue

            # ── Title ────────────────────────────────────────────────────
            title = (item.get("title") or "").strip()
            # NewsAPI sometimes puts "[Removed]" as a title for deleted articles
            if not title or title == "[Removed]":
                continue

            # ── URL ──────────────────────────────────────────────────────
            url = (item.get("url") or "").strip()
            if not url or not url.startswith("http"):
                continue

            # ── Description ───────────────────────────────────────────────
            description = (item.get("description") or "").strip()
            # Skip "[Removed]" placeholder descriptions too
            if description == "[Removed]":
                description = ""

            # ── Image URL (camelCase: urlToImage) ─────────────────────────
            image_url = (item.get("urlToImage") or "").strip()

            # ── Published Date (camelCase: publishedAt) ───────────────────
            # NewsAPI format is already ISO 8601 (e.g., "2026-03-03T06:00:00Z").
            # Our Pydantic Article model accepts this directly — no conversion.
            published_at = item.get("publishedAt") or ""

            # ── Source Name (nested object) ───────────────────────────────
            # NewsAPI wraps the source as { "id": "...", "name": "..." }.
            # We only want the 'name' string.
            source_obj = item.get("source") or {}
            raw_source_name = (source_obj.get("name") or "").strip()

            # Append the region code so it's clear in the UI where
            # this article came from, e.g., "The Verge (IN)" or "Wired (US)".
            if raw_source_name:
                source = f"{raw_source_name} ({region_code.upper()})"
            else:
                source = f"SauravKanchan ({region_code.upper()})"

            # ── Build Article ─────────────────────────────────────────────
            try:
                article = Article(
                    title=title,
                    description=description,
                    url=url,
                    image_url=image_url,
                    published_at=published_at,
                    source=source,
                    # ── ROUTING RULE ──────────────────────────────────────
                    # Pass through the aggregator's category.
                    # The keyword gate filters out off-topic articles.
                    # Unknown or empty categories safely route to
                    # the default 'News Articles' collection.
                    category=category,
                )
                articles.append(article)

            except Exception as e:
                logger.debug(
                    f"[SauravKanchan] Skipped item '{title[:50]}...': {e}"
                )
                continue

        return articles
