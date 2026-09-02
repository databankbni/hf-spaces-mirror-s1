"""
providers/direct_rss/client.py
─────────────────────────────────────────────────────────────────────────────
The Direct RSS Provider for Segmento Pulse.

What this does:
    Fetches the latest technology articles from the RSS feeds of the world's
    best tech publications: TechCrunch, Wired, The Verge, Engadget, and
    Ars Technica.

Why Direct RSS instead of using rss_parser.parse_provider_rss()?
    The existing rss_parser.parse_provider_rss() function is built for a
    specific use case: fetching official CLOUD PROVIDER blogs (AWS, GCP etc.)
    It hardcodes  category = f'cloud-{provider}'  on every article it creates.

    If we ran TechCrunch through that function, every TechCrunch article
    would be tagged "category = cloud-TechCrunch". Appwrite would not know
    where to route it, and articles would end up in the wrong collection —
    or worse, be silently dropped.

    So instead, we use the feedparser library directly (the same library
    rss_parser.py uses internally). We follow the exact same parsing pattern
    but set the category correctly from what the aggregator tells us.

    We DO still reuse two helper methods from rss_parser.py for consistency:
        - _extract_image_from_entry()  → finds images from media/enclosure tags
        - _parse_date()                → handles all date format variations

How it works:
    Step 1: Build a list of async HTTP tasks — one per RSS feed URL.
    Step 2: Fire all tasks at the same time using asyncio.gather().
    Step 3: Feed each successful XML response into feedparser.
    Step 4: Map each feedparser entry to a Pulse Article object.
    Step 5: Return the combined list from all feeds.

Client-side constraint note:
    RSS feeds give us whatever was published recently by that outlet —
    we cannot ask them for "only today's AI articles".
    The freshness gate (is_valid_article) and keyword gate
    (is_relevant_to_category) in data_validation.py handle all filtering
    after we return these articles. That is by design.
"""

# ── Standard Library ──────────────────────────────────────────────────────────
import asyncio
import logging
import re
import time
from typing import List

# ── Third-party (already in requirements.txt) ─────────────────────────────────
import feedparser          # XML/RSS feed parser — already used by rss_parser.py
import httpx               # Async HTTP client

# ── Internal ──────────────────────────────────────────────────────────────────
from app.services.providers.base import NewsProvider
from app.services.rss_parser import RSSParser   # Reuse helper methods, not the methods with hardcoded categories
from app.models import Article

logger = logging.getLogger(__name__)

# ── RSS Feed Registry ──────────────────────────────────────────────────────────
#
# These are the direct RSS feed URLs for the most trusted tech publications.
# Each entry is a tuple of (feed_url, source_name).
#
# "source_name" is the human-readable name we store on every article.
# It appears in the Segmento Pulse UI next to the article headline.
#
# To add a new RSS feed in the future, just add a new line here.
# The rest of the code picks it up automatically.
#
TECH_RSS_FEEDS: List[tuple] = [
    ("https://techcrunch.com/feed",                          "TechCrunch"),
    ("https://www.wired.com/feed/rss",                       "Wired"),
    ("https://www.theverge.com/rss/tech/index.xml",          "The Verge"),
    ("https://www.engadget.com/rss.xml",                     "Engadget"),
    ("https://feeds.arstechnica.com/arstechnica/technology-lab", "Ars Technica"),
]

# Maximum articles to take from each individual feed.
# 10 per feed × 5 feeds = up to 50 articles total per aggregator run.
MAX_ARTICLES_PER_FEED = 10

# How long (in seconds) to wait for a feed to respond before giving up.
HTTP_TIMEOUT_SECONDS = 10.0


class DirectRSSProvider(NewsProvider):
    """
    Fetches articles directly from the RSS feeds of premium tech publications.

    Free. No API key needed. No rate limits.
    Provides the best descriptions and images of all our free providers,
    because these are professionally edited by full-time journalists.

    Usage (wired into the aggregator in Phase 4):
        provider = DirectRSSProvider()
        articles = await provider.fetch_news(category="ai", limit=50)
    """

    def __init__(self):
        # Free provider — no API key, no daily limit.
        super().__init__(api_key=None)
        self.daily_limit = 0

        # Phase 17: Fetch-Once, Fan-Out cache
        #
        # Direct RSS fetches TechCrunch, Wired, The Verge, Engadget, and
        # Ars Technica. These do NOT change between categories — the same
        # 5 XML files contain the same articles whether the category is
        # "ai", "cloud-aws", or "data-security".
        #
        # Without a cache: 22 categories × 5 feeds = 110 outbound HTTP requests
        # per scheduler run, all downloading the exact same XML.
        #
        # With a cache: first category fetches 5 feeds once, stores results
        # here. The other 21 categories get the list instantly from memory.
        # Total outbound requests: 5. A 95% reduction.
        self._cached_articles: List[Article] = []
        self._cache_time: float = 0.0

        # asyncio.Lock prevents a race condition during the first run.
        # When the scheduler fires, asyncio.gather() calls fetch_news() for
        # multiple categories at the same time. Without the lock, all of them
        # would see an empty cache and all start their own 5-feed HTTP fetch
        # simultaneously. That defeats the whole purpose. With the lock,
        # only the FIRST caller fetches; the rest wait and then read from cache.
        self._lock = asyncio.Lock()

        # We borrow helpers from the existing RSSParser.
        # We do NOT call parse_google_news() or parse_provider_rss() —
        # those have category logic built in that would break our routing.
        # We only use the helper methods: _extract_image_from_entry, _parse_date.
        self._rss_helpers = RSSParser()

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN ENTRY POINT — called by the aggregator
    # ─────────────────────────────────────────────────────────────────────────

    async def fetch_news(self, category: str, limit: int = 50) -> List[Article]:
        """
        Fetch articles from all premium tech RSS feeds concurrently.

        Args:
            category (str): The category string passed from the aggregator.
                            We tag every article with this so the pipeline
                            can route it to the correct Appwrite collection.
                            The keyword gate will filter out irrelevant articles.
            limit (int):    Not strictly enforced here — we let the per-feed
                            cap (MAX_ARTICLES_PER_FEED) control volume, and
                            the aggregator deduplication handles the rest.

        Returns:
            List[Article]: All articles collected across all 5 feeds.
                           Returns [] if network is down for all feeds.
        """
        # ── Phase 17: Cache check (OUTER) ─────────────────────────────────────
        # 2700 seconds = 45 minutes. If we fetched the RSS feeds less than
        # 45 minutes ago, return the stored articles immediately.
        # No HTTP request. No XML parsing. Instant return.
        #
        # Why 45 minutes? Our freshness gate uses an hourly window. A 45-minute
        # cache is safely inside that window, giving us fresh-enough content
        # without hammering TechCrunch and Wired every minute.
        CACHE_TTL_SECONDS = 2700   # 45 minutes

        if time.time() - self._cache_time < CACHE_TTL_SECONDS and self._cached_articles:
            logger.debug(
                "[DirectRSS] Cache hit — returning %d cached articles for category='%s'. "
                "No HTTP calls made.",
                len(self._cached_articles), category
            )
            return self._cached_articles

        # ── Cache stale or empty: acquire the lock and fetch ───────────────────
        # Only one coroutine can be inside this block at a time.
        # Any other coroutine that reaches this point will WAIT here until
        # the first one has finished and released the lock.
        async with self._lock:

            # ── Cache check (INNER) — double-checked locking ──────────────
            # While THIS coroutine was waiting for the lock, the coroutine that
            # held the lock before us already fetched and filled the cache.
            # We check again so we don't fetch a second time.
            if time.time() - self._cache_time < CACHE_TTL_SECONDS and self._cached_articles:
                logger.debug(
                    "[DirectRSS] Cache hit after lock (another task fetched it) — "
                    "returning %d cached articles.",
                    len(self._cached_articles)
                )
                return self._cached_articles

            # Cache is genuinely stale — this coroutine won the race.
            # Do the full HTTP fetch now.
            logger.info("[DirectRSS] Cache stale/empty. Fetching all 5 RSS feeds...")

            try:
                async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:

                    # Step 1: Build one fetch task per RSS feed URL.
                    # All tasks run at the same time — we do not wait for feed #1
                    # before starting feed #2. This keeps total time under 2 seconds.
                    fetch_tasks = [
                        self._fetch_and_parse_feed(client, url, source_name, category)
                        for url, source_name in TECH_RSS_FEEDS
                    ]

                    # Step 2: Launch all tasks simultaneously.
                    results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

                    # Step 3: Combine all lists into one. Skip any that errored.
                    all_articles: List[Article] = []
                    for feed_url_source, result in zip(TECH_RSS_FEEDS, results):
                        source_name = feed_url_source[1]
                        if isinstance(result, Exception):
                            logger.warning(
                                f"[DirectRSS] [{source_name}] Feed fetch failed: {result}"
                            )
                        elif isinstance(result, list):
                            all_articles.extend(result)

                    logger.info(
                        "[DirectRSS] Fetched %d articles across %d feeds. "
                        "Caching for 45 minutes.",
                        len(all_articles), len(TECH_RSS_FEEDS)
                    )

                    # Save results and timestamp to the class-level cache.
                    self._cached_articles = all_articles
                    self._cache_time = time.time()
                    return all_articles

            except Exception as e:
                logger.error(f"[DirectRSS] Unexpected error: {e}", exc_info=True)
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
        Fetch one RSS feed URL and parse it into Article objects.

        Args:
            client (httpx.AsyncClient): Shared HTTP client from fetch_news().
            url (str):         The RSS feed URL (e.g., https://techcrunch.com/feed).
            source_name (str): Human-readable name (e.g., "TechCrunch").
            category (str):    The category from the aggregator — stored on each article.

        Returns:
            List[Article]: Parsed articles from this feed. Returns [] on any failure.
        """
        try:
            response = await client.get(
                url,
                # Politely identify ourselves. Some servers block unknown user agents.
                headers={"User-Agent": "SegmentoPulse-RSS-Reader/1.0"},
                follow_redirects=True,
            )

            if response.status_code == 429:
                self.handle_429()
                return []

            if response.status_code != 200:
                logger.warning(
                    f"[DirectRSS] [{source_name}] HTTP {response.status_code} — skipping."
                )
                return []

            xml_text = response.text

        except httpx.TimeoutException:
            logger.warning(f"[DirectRSS] [{source_name}] Timed out — skipping.")
            return []
        except Exception as e:
            logger.warning(f"[DirectRSS] [{source_name}] Fetch error: {e}")
            return []

        # Hand the raw XML to feedparser — it handles all RSS/Atom variants
        # (RSS 2.0, Atom 1.0, etc.) automatically.
        return self._parse_feed_xml(xml_text, source_name, category)

    def _parse_feed_xml(
        self,
        xml_text: str,
        source_name: str,
        category: str,
    ) -> List[Article]:
        """
        Parse raw XML text from a feed into a list of Article objects.

        Uses feedparser to decode the XML, then maps each entry to our
        Pydantic Article model. We reuse rss_parser's helper methods for
        image extraction and date parsing so the logic is consistent
        across all RSS sources in the system.

        Args:
            xml_text (str):    Raw XML string from the HTTP response.
            source_name (str): Name of the publication (e.g., "Wired").
            category (str):    Category to tag on every article.

        Returns:
            List[Article]: Parsed articles. May be [] if the feed is malformed.
        """
        try:
            feed = feedparser.parse(xml_text)
        except Exception as e:
            logger.warning(f"[DirectRSS] [{source_name}] feedparser failed: {e}")
            return []

        articles: List[Article] = []

        for entry in feed.entries[:MAX_ARTICLES_PER_FEED]:

            # ── Title ────────────────────────────────────────────────────────
            title = (entry.get("title") or "").strip()
            if not title:
                continue   # Every article must have a title

            # ── URL ──────────────────────────────────────────────────────────
            url = (entry.get("link") or "").strip()
            if not url or not url.startswith("http"):
                continue   # Every article must have a clickable link

            # ── Description ──────────────────────────────────────────────────
            # RSS feeds usually put a short summary in the 'summary' field.
            # We strip any HTML tags, then cap it at 200 characters.
            raw_desc = entry.get("summary", "") or ""
            description = re.sub(r"<[^>]+>", "", raw_desc).strip()
            if len(description) > 200:
                description = description[:200] + "..."

            # ── Image URL ────────────────────────────────────────────────────
            # We reuse the existing _extract_image_from_entry helper from
            # rss_parser.py. It checks media:content, media:thumbnail,
            # enclosures, and <img> tags inside the description.
            image_url = self._rss_helpers._extract_image_from_entry(entry)

            # ── Published Date ───────────────────────────────────────────────
            # We reuse the existing _parse_date helper from rss_parser.py.
            # It handles RFC 2822, ISO 8601, and other common date formats.
            raw_date = entry.get("published", "") or ""
            published_at = self._rss_helpers._parse_date(raw_date)

            # ── Build Article ────────────────────────────────────────────────
            try:
                article = Article(
                    title=title,
                    description=description,
                    url=url,
                    image_url=image_url,
                    published_at=published_at,
                    source=source_name,
                    # ── ROUTING RULE ──────────────────────────────────────
                    # We set the category that the aggregator passed in.
                    # The keyword gate will reject articles that don't
                    # actually match this category — that's completely fine.
                    # It is much safer than guessing a wrong category here.
                    category=category,
                )
                articles.append(article)

            except Exception as e:
                # One bad article should never cancel the rest of the feed
                logger.debug(
                    f"[DirectRSS] [{source_name}] Skipped entry '{title[:50]}': {e}"
                )
                continue

        logger.info(
            f"[DirectRSS] [{source_name}] Parsed {len(articles)} articles."
        )
        return articles
