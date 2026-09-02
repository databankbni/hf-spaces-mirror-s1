"""
providers/inshorts/client.py
─────────────────────────────────────────────────────────────────────────────
The Inshorts Provider for Segmento Pulse.

What this does:
    Fetches 60-word tech news summaries from the Inshorts community API.
    Inshorts takes long articles from the internet and rewrites them in
    exactly 60 words. This gives our users very quick, scannable reads.

Free. No API key needed. No rate limits.

Where it sits in the pipeline:
    FREE_SOURCES (always runs in parallel).
    Gated behind GENERAL_TECH_CATEGORIES — same rule as Hacker News.
    Inshorts "technology" news is broad. It does not know the difference
    between "cloud-alibaba" and "cloud-gcp". We only ask it for wide,
    general categories where its content is genuinely valuable.

The special data quirk (split date and time):
    Inshorts returns the article timestamp as TWO separate strings:
        "date": "Mon, 03 Mar 2026"
        "time": "10:30 AM, IST"

    Our Pydantic Article model needs a SINGLE published_at timestamp.
    So we join them: "Mon, 03 Mar 2026 10:30 AM, IST"
    Then we parse that combined string into a proper datetime object using
    dateutil.parser (the same library our rss_parser.py already uses).

    If parsing fails, we safely fall back to datetime.now() so the article
    still enters the pipeline and the freshness gate makes the final call.

API note:
    The endpoint used below is a well-known community-maintained mirror of
    the Inshorts API. It may change URLs over time. The try/except in
    fetch_news() wraps the entire fetch, so even if the endpoint goes down,
    the aggregator just gets an empty list and moves on without crashing.
"""

# ── Standard Library ──────────────────────────────────────────────────────────
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import List

# ── Third-party (already available — used by rss_parser.py line 209) ─────────
import httpx                    # Async HTTP client
from dateutil import parser as dateutil_parser   # Flexible date string parser

# ── Internal ──────────────────────────────────────────────────────────────────
from app.services.providers.base import NewsProvider, ProviderStatus
from app.models import Article

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# Inshorts community API endpoint.
# The 'category=technology' filter is the closest match to our content needs.
# Other available categories: national, business, sports, entertainment, etc.
INSHORTS_URL = "https://inshorts.deta.dev/news?category=technology"

# Request timeout in seconds. Kept generous because this is a community server.
HTTP_TIMEOUT_SECONDS = 10.0

# Max articles to take from one response. Inshorts usually sends 10-25.
MAX_ARTICLES = 20


class InshortsProvider(NewsProvider):
    """
    Fetches 60-word technology summaries from the Inshorts community API.

    Free. No API key. No daily limit.
    Sits in FREE_SOURCES, gated by GENERAL_TECH_CATEGORIES.

    Usage (wired in Phase 6):
        provider = InshortsProvider()
        articles = await provider.fetch_news(category="ai", limit=20)
    """

    def __init__(self):
        # Free provider — no API key, no daily limit.
        super().__init__(api_key=None)
        self.daily_limit = 0

        # Phase 17: Fetch-Once, Fan-Out cache
        #
        # Inshorts hits a community server — not a CDN like GitHub Pages.
        # Without a cache, every category loop sends a request to that
        # community server, increasing the chance of a 429 rate-limit block.
        # With a cache: 22 category calls → 1 real HTTP call per 45 minutes.
        self._cached_articles: List[Article] = []
        self._cache_time: float = 0.0

        # Lock prevents the "thundering herd": multiple concurrent calls
        # all seeing an empty cache and all fetching at the same time.
        self._lock = asyncio.Lock()

        # ── HF Spaces DNS-offline guard ───────────────────────────────────────
        # Inshorts community API is blocked at the DNS layer on Hugging Face
        # Spaces (ConnectError: [Errno -3] Temporary failure in name resolution).
        # After the first hard DNS failure, we flip this flag and skip all
        # subsequent calls so we don't spam the logs with full tracebacks on
        # every scheduler tick.
        self._permanently_unavailable: bool = False

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN ENTRY POINT — called by the aggregator's FREE PARALLEL RUN
    # ─────────────────────────────────────────────────────────────────────────

    async def fetch_news(self, category: str, limit: int = 20) -> List[Article]:
        """
        Fetch technology articles from the Inshorts community API.

        Args:
            category (str): Our internal category string (e.g., "ai").
                            We tag every article with it. The keyword gate
                            filters out articles that don't actually match.
            limit (int):    Max articles to return. Capped at MAX_ARTICLES.

        Returns:
            List[Article]: Mapped Article objects. Returns [] on any failure.
        """
        # ── Phase 17: Cache check (OUTER) ─────────────────────────────────────
        CACHE_TTL_SECONDS = 2700   # 45 minutes

        # ── HF Spaces / DNS offline guard ─────────────────────────────────────
        if self._permanently_unavailable:
            return []  # Silent fast-path — no log spam

        if time.time() - self._cache_time < CACHE_TTL_SECONDS and self._cached_articles:
            logger.debug(
                "[Inshorts] Cache hit — returning %d cached articles for category='%s'. "
                "No HTTP calls made.",
                len(self._cached_articles), category
            )
            return self._cached_articles

        # ── Cache stale or empty: acquire the lock and fetch ───────────────────
        async with self._lock:

            # ── Cache check (INNER) — double-checked locking ──────────────
            if time.time() - self._cache_time < CACHE_TTL_SECONDS and self._cached_articles:
                logger.debug(
                    "[Inshorts] Cache hit after lock — returning %d cached articles.",
                    len(self._cached_articles)
                )
                return self._cached_articles

            logger.info(
                "[Inshorts] Cache stale/empty. Fetching from community API for category='%s'...",
                category
            )

            try:
                async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:

                    response = await client.get(
                        INSHORTS_URL,
                        headers={"User-Agent": "SegmentoPulse-Ingestion/1.0"},
                        follow_redirects=True,
                    )

                    # ── Handle rate limit ──────────────────────────────────────
                    if response.status_code == 429:
                        self.handle_429()
                        return []

                    # ── Handle non-200 responses ──────────────────────────────
                    if response.status_code != 200:
                        logger.warning(
                            "[Inshorts] Unexpected HTTP %d. "
                            "The community API endpoint may have changed.",
                            response.status_code
                        )
                        return []

                    data = response.json()

                    # Inshorts wraps the article list inside a 'data' key.
                    raw_articles = data.get("data", [])

                    if not isinstance(raw_articles, list) or not raw_articles:
                        logger.info("[Inshorts] No articles in response.")
                        return []

                    all_articles = self._map_articles(
                        raw_articles[:min(limit, MAX_ARTICLES)],
                        category
                    )

                    logger.info(
                        "[Inshorts] Fetched %d articles. Caching for 45 minutes.",
                        len(all_articles)
                    )

                    # Save to class-level cache.
                    self._cached_articles = all_articles
                    self._cache_time = time.time()
                    return all_articles

            except httpx.ConnectError as e:
                err_str = str(e)
                if 'name resolution' in err_str or 'Errno -3' in err_str or 'Errno -2' in err_str:
                    # DNS failure — endpoint is unreachable in this environment
                    # (e.g. Hugging Face Spaces network sandbox).
                    # Flip the dead flag so we skip silently next time.
                    self._permanently_unavailable = True
                    logger.warning(
                        "[Inshorts] DNS resolution failed — endpoint appears unreachable "
                        "in this environment. Disabling Inshorts for the lifetime of this "
                        "process to avoid log spam."
                    )
                else:
                    logger.warning("[Inshorts] Connection error: %s", e)
                return []
            except httpx.TimeoutException:
                logger.warning("[Inshorts] Request timed out — endpoint may be slow.")
                return []
            except Exception as e:
                logger.error(f"[Inshorts] Unexpected error: {e}", exc_info=True)
                return []

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_inshorts_date(self, date_str: str, time_str: str) -> str:
        """
        Solve the split date/time problem.

        Inshorts gives us date and time as two separate strings.
        Example:
            date_str = "Mon, 03 Mar 2026"
            time_str = "10:30 AM, IST"

        Step 1: Join them → "Mon, 03 Mar 2026 10:30 AM, IST"
        Step 2: Parse with dateutil (handles many date formats automatically)
        Step 3: Convert to UTC-aware ISO 8601 string

        If parsing fails for any reason, we return the current time as a
        safe fallback. The freshness gate downstream will evaluate it.

        Args:
            date_str (str): The date portion from the API (e.g., "Mon, 03 Mar 2026")
            time_str (str): The time portion from the API (e.g., "10:30 AM, IST")

        Returns:
            str: ISO 8601 timestamp string (e.g., "2026-03-03T05:00:00+00:00")
        """
        # Clean up trailing ", IST" or "(IST)" markers — dateutil sometimes
        # gets confused by non-standard timezone abbreviations like IST.
        # We strip them and treat the time as IST = UTC+5:30 manually.
        cleaned_time = (
            time_str
            .replace(", IST", "")
            .replace("(IST)", "")
            .strip()
        )
        combined = f"{date_str.strip()} {cleaned_time}"

        try:
            # dateutil.parser is very flexible — it handles formats like:
            # "Mon, 03 Mar 2026 10:30 AM" without needing a strptime pattern.
            parsed_dt = dateutil_parser.parse(combined)

            # If the parsed datetime has no timezone info (which it won't after
            # we stripped IST), we tell Python it was in IST (UTC+5:30).
            if parsed_dt.tzinfo is None:
                from datetime import timedelta
                IST = timezone(timedelta(hours=5, minutes=30))
                parsed_dt = parsed_dt.replace(tzinfo=IST)

            # Convert to UTC for consistent storage across all providers.
            utc_dt = parsed_dt.astimezone(timezone.utc)
            return utc_dt.isoformat()

        except Exception as e:
            logger.debug(
                f"[Inshorts] Date parse failed for '{combined}': {e} — using now()."
            )
            # Safe fallback: use current UTC time.
            # The freshness gate will still check it and decide if it's valid.
            return datetime.now(tz=timezone.utc).isoformat()

    def _map_articles(self, raw_articles: list, category: str) -> List[Article]:
        """
        Convert raw Inshorts JSON items into Segmento Pulse Article objects.

        Key field mappings:
            Inshorts field       →  Article field
            ─────────────────────────────────────
            title                →  title
            content              →  description  (the famous 60-word summary)
            readMoreUrl          →  url
            imageUrl             →  image_url
            author               →  source
            date + time (joined) →  published_at

        Args:
            raw_articles (list): The list from the API's 'data' key.
            category (str):      The category from the aggregator.

        Returns:
            List[Article]: Clean, validated Article objects.
        """
        articles: List[Article] = []

        for item in raw_articles:
            if not isinstance(item, dict):
                continue

            # ── Title ────────────────────────────────────────────────────
            title = (item.get("title") or "").strip()
            if not title:
                continue

            # ── URL ──────────────────────────────────────────────────────
            # Inshorts calls this 'readMoreUrl' — the link to the full article.
            url = (item.get("readMoreUrl") or "").strip()
            if not url or not url.startswith("http"):
                continue   # Skip if no valid link

            # ── Description (the 60-word summary) ────────────────────────
            # Inshorts calls the summary field 'content'.
            description = (item.get("content") or "").strip()

            # ── Image URL ─────────────────────────────────────────────────
            # Inshorts calls this 'imageUrl' (camelCase).
            image_url = (item.get("imageUrl") or "").strip()

            # ── Source ───────────────────────────────────────────────────
            # The 'author' field holds the original publication name
            # (e.g., "TechCrunch", "NDTV Gadgets"). We use that as source.
            # Fall back to "Inshorts" if author is missing.
            source = (item.get("author") or "Inshorts").strip()
            if not source:
                source = "Inshorts"

            # ── Date Fix: Combine split date + time ───────────────────────
            # This is THE key transformation for this provider.
            # See _parse_inshorts_date() above for the full explanation.
            date_part = item.get("date") or ""
            time_part = item.get("time") or ""
            published_at = self._parse_inshorts_date(date_part, time_part)

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
                    # We pass through the aggregator's category.
                    # The keyword gate will filter irrelevant articles.
                    # Unknown categories safely route to 'News Articles'.
                    category=category,
                )
                articles.append(article)

            except Exception as e:
                logger.debug(
                    f"[Inshorts] Skipped item '{title[:50]}': {e}"
                )
                continue

        return articles
