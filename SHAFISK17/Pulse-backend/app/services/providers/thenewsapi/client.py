"""
providers/thenewsapi/client.py
─────────────────────────────────────────────────────────────────────────────
TheNewsAPI.com Provider for Segmento Pulse.

What this does:
    Fetches fresh technology news articles from TheNewsAPI.com.
    This is a paid API but has the cleanest JSON structure of all paid
    providers — most of its field names even match our Pydantic Article model.

Free Tier Limits:
    - 100 requests per day (resets midnight UTC)
    - Requires an API key (THENEWSAPI_API_KEY in your .env file)

Where it sits in the pipeline:
    PAID_CHAIN position 4 (after GNews → NewsAPI → NewsData).
    Only fires if all three above it have already failed or hit their limits.
    Once it returns articles, the paid chain stops — credits protected.

The special data quirk (categories array):
    TheNewsAPI returns a 'categories' field as a LIST, not a single string.
    Example: { "categories": ["tech", "science"] }

    We grab only the FIRST item from that list.
    Example: "tech"

    This raw value ("tech") is then passed through our pipeline.
    The keyword gate in data_validation.is_relevant_to_category() handles
    whether the article truly belongs in our system.

    We do NOT try to translate "tech" → "magazines" ourselves here.
    That mapping belongs in the validation/data layer, not the fetcher layer.
    Keep the fetcher dumb — let the pipeline be smart.

Client-side constraint note:
    TheNewsAPI supports date filters (published_after, published_before) and
    language filters (language=en). We use language=en to avoid non-English
    articles. We do NOT apply date filters because the freshness gate in
    data_validation.is_valid_article() handles that more accurately in IST.
"""

# ── Standard Library ──────────────────────────────────────────────────────────
import logging
from datetime import datetime, timezone
from typing import List, Optional

# ── Third-party (already in requirements.txt) ─────────────────────────────────
import httpx                            # Async HTTP client

# ── Internal ──────────────────────────────────────────────────────────────────
from app.services.providers.base import NewsProvider, ProviderStatus
from app.models import Article
from app.config import settings         # Single source of truth for all keys
# Phase 16: Import the Redis counter utility to make the daily budget
# restart-proof. TheNewsAPI only allows 3 real calls per day on the free tier.
# Without Redis, a server restart resets request_count to 0 and lets us
# make 3 more calls — potentially 9+ calls on a restart-heavy day.
from app.services.utils.provider_state import (
    get_provider_counter,
    increment_provider_counter,
)

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# Base URL for all TheNewsAPI endpoints
THENEWSAPI_BASE_URL = "https://api.thenewsapi.com/v1/news/all"

# How long (seconds) to wait before giving up on a request
HTTP_TIMEOUT_SECONDS = 10.0

# How many articles to request per call. 25 is their recommended page size.
ARTICLES_PER_REQUEST = 25


class TheNewsAPIProvider(NewsProvider):
    """
    Fetches technology news from TheNewsAPI.com.

    Paid provider — needs THENEWSAPI_API_KEY in your .env file.
    Sits at position 4 in the PAID_CHAIN (last paid fallback).
    100 requests/day on the free tier.

    Usage (wired into the aggregator in Phase 5):
        provider = TheNewsAPIProvider(api_key="your_key_here")
        articles = await provider.fetch_news(category="ai", limit=25)
    """

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key=api_key)

        # Phase 16 Audit Fix: Corrected from 100 → 3.
        #
        # The free tier documentation lists "100 requests/day" but in practice
        # the Community (free) tier is hard-capped at 3 requests per day.
        # Our QA audit caught this discrepancy: with daily_limit=100, the old
        # code would keep calling this API expecting 100 slots, burning all 3
        # real calls immediately and then receiving 402s for the rest of the day.
        #
        # With daily_limit=3 + Redis persistence: we use at most 3 calls/day
        # even across multiple server restarts. The 3rd call is reserved as an
        # emergency slot — Redis budget enforcement kicks in at 2.
        self.daily_limit = 3

        # Category mapping: translate our internal category names into the
        # categories that TheNewsAPI actually understands.
        # TheNewsAPI uses these: tech, science, sports, business, health, entertainment, general
        # We map our fine-grained categories to the closest match.
        self.category_map = {
            'ai':                      'tech',
            'data-security':           'tech',
            'data-governance':         'tech',
            'data-privacy':            'tech',
            'data-engineering':        'tech',
            'data-management':         'tech',
            'business-intelligence':   'business',
            'business-analytics':      'business',
            'customer-data-platform':  'business',
            'data-centers':            'tech',
            'cloud-computing':         'tech',
            'magazines':               'tech',
            'data-laws':               'tech',
            # Cloud sub-categories → all map to 'tech' in TheNewsAPI's world
            'cloud-aws':               'tech',
            'cloud-azure':             'tech',
            'cloud-gcp':               'tech',
            'cloud-oracle':            'tech',
            'cloud-ibm':               'tech',
            'cloud-alibaba':           'tech',
            'cloud-digitalocean':      'tech',
            'cloud-huawei':            'tech',
            'cloud-cloudflare':        'tech',
        }

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN ENTRY POINT — called by the aggregator's PAID WATERFALL
    # ─────────────────────────────────────────────────────────────────────────

    async def fetch_news(self, category: str, limit: int = 20) -> List[Article]:
        """
        Fetch technology articles from TheNewsAPI.com.

        Args:
            category (str): Our internal category (e.g., "ai", "cloud-aws").
                            We look this up in self.category_map to get the
                            correct TheNewsAPI category keyword.
            limit (int):    Maximum number of articles to return.

        Returns:
            List[Article]: Mapped Article objects. Returns [] on failure.
        """
        # No API key means this provider cannot run.
        # The aggregator will have already checked this via is_available(),
        # but we double-check here for safety.
        if not self.api_key:
            logger.debug("[TheNewsAPI] No API key configured — skipping.")
            return []

        # ── PHASE 16: Redis-backed daily budget guard ────────────────────────
        # Real free-tier limit: 3 calls/day (corrected in this phase).
        # We check Redis FIRST before building any params or making any HTTP call.
        #
        # Why inside fetch_news and not inside is_available()?
        # is_available() is a synchronous function on the base class.
        # Redis calls are async (they use `await`). You cannot mix them:
        # calling an async function from a sync function crashes at runtime.
        # So we do the async Redis check here, at the very top of async fetch_news.
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        current_calls = await get_provider_counter("thenewsapi", today_str)

        if current_calls >= self.daily_limit:
            logger.warning(
                "[TheNewsAPI] Daily Redis budget exhausted — %d/%d calls used today. "
                "Skipping to protect the 3-call daily quota.",
                current_calls, self.daily_limit
            )
            self.mark_rate_limited()
            return []

        try:
            # Translate our internal category to TheNewsAPI's category keyword.
            # If the category is not in our map, default to 'tech'.
            api_category = self.category_map.get(category, "tech")

            params = {
                "api_token":  self.api_key,
                "language":   "en",           # English articles only
                "categories": api_category,   # TheNewsAPI category keyword
                "limit":      min(limit, ARTICLES_PER_REQUEST),
                # NOTE: We deliberately do NOT add 'published_after' or
                # 'published_before' date filters.
                # TheNewsAPI supports them, but our freshness gate
                # (is_valid_article in data_validation.py) already enforces
                # the correct IST-based date boundary. Letting the gate handle
                # it is safer and avoids timezone conversion bugs here.
            }

            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
                logger.info("[TheNewsAPI] Fetching '%s' (api_category='%s')...", category, api_category)
                response = await client.get(THENEWSAPI_BASE_URL, params=params)

                # ── Handle rate limit ─────────────────────────────────────
                if response.status_code == 429:
                    self.handle_429()
                    return []

                # ── Handle authentication failure ─────────────────────────
                if response.status_code == 401:
                    logger.error("[TheNewsAPI] 401 Unauthorized — API key is invalid or expired.")
                    self.status = ProviderStatus.ERROR
                    return []

                # ── Handle quota exhaustion ───────────────────────────────
                if response.status_code == 402:
                    logger.warning("[TheNewsAPI] 402 Payment Required — daily quota exhausted.")
                    self.mark_rate_limited()
                    return []

                # ── Handle other non-200 responses ────────────────────────
                if response.status_code != 200:
                    logger.warning(f"[TheNewsAPI] Unexpected HTTP {response.status_code}.")
                    return []

                # ── Parse and map the response ──────────────────────────────────
                self.request_count += 1   # Keep RAM shadow in sync for debugging
                data = response.json()

                # TheNewsAPI wraps articles in a 'data' key at the top level
                raw_articles = data.get("data", [])

                if not raw_articles:
                    logger.info(f"[TheNewsAPI] No articles returned for category='{category}'.")
                    return []

                articles = self._map_articles(raw_articles, category)

                # ── PHASE 16: Increment the Redis counter after a successful call ──
                # Only successful 200 responses count against the daily budget.
                # 402/429/timeout failures do not consume a slot.
                await increment_provider_counter("thenewsapi", today_str)

                logger.info("[TheNewsAPI] Got %d articles for '%s'.", len(articles), category)
                return articles

        except httpx.TimeoutException:
            logger.warning("[TheNewsAPI] Request timed out.")
            return []
        except Exception as e:
            logger.error(f"[TheNewsAPI] Unexpected error: {e}", exc_info=True)
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE HELPER — maps raw JSON items to Article objects
    # ─────────────────────────────────────────────────────────────────────────

    def _map_articles(self, raw_articles: list, category: str) -> List[Article]:
        """
        Convert TheNewsAPI JSON items into Segmento Pulse Article objects.

        The mapping is almost 1-to-1 with our Pydantic model, which is why
        this is the easiest of all paid providers to integrate.

        One special case: 'categories' is a list, not a string.
        We take [0] (the first item) as the article's category value.

        Args:
            raw_articles (list): The 'data' array from TheNewsAPI's response.
            category (str):      Our internal category (from the aggregator).

        Returns:
            List[Article]: Clean Article objects for the pipeline.
        """
        articles: List[Article] = []

        for item in raw_articles:

            # ── Title ─────────────────────────────────────────────────────
            title = (item.get("title") or "").strip()
            if not title:
                continue

            # ── URL ───────────────────────────────────────────────────────
            url = (item.get("url") or "").strip()
            if not url or not url.startswith("http"):
                continue

            # ── Description ───────────────────────────────────────────────
            # TheNewsAPI provides real summaries — a huge advantage over HN.
            description = (item.get("description") or "").strip()

            # ── Image URL ─────────────────────────────────────────────────
            # The field is ALREADY called 'image_url' in their API.
            # This is the cleanest mapping of any provider we have integrated.
            image_url = (item.get("image_url") or "").strip()

            # ── Published Date ────────────────────────────────────────────
            # TheNewsAPI returns ISO 8601 format (e.g., "2024-03-03T06:00:00.000000Z").
            # Our Pydantic Article model already handles this format in its
            # published_at validator — no conversion needed.
            published_at = item.get("published_at") or ""

            # ── Source Name ───────────────────────────────────────────────
            # TheNewsAPI's live response returns `source` as a plain string
            # (the publisher domain, e.g. "techcrunch.com"), NOT as a nested
            # dict like NewsAPI.org does. We handle both shapes defensively.
            raw_source = item.get("source") or ""
            if isinstance(raw_source, dict):
                # Nested object shape: {"name": "TechCrunch", "url": "..."}
                source = (raw_source.get("name") or "TheNewsAPI").strip()
            else:
                # Plain string shape: "techcrunch.com" — use it as-is.
                source = str(raw_source).strip() or "TheNewsAPI"

            # ── Category ──────────────────────────────────────────────────
            # TheNewsAPI returns categories as a LIST, e.g., ["tech", "science"]
            # We take only the first item. Our keyword gate will verify relevance.
            # ROUTING RULE: if the list is empty, fall back to our internal
            # category name. Both "" and category will safely route to the
            # default 'News Articles' collection if unrecognised.
            raw_categories = item.get("categories") or []
            if raw_categories and isinstance(raw_categories, list):
                article_category = raw_categories[0]
            else:
                article_category = category   # Fallback to aggregator's category

            # ── Build Article ─────────────────────────────────────────────
            try:
                article = Article(
                    title=title,
                    description=description,
                    url=url,
                    image_url=image_url,
                    published_at=published_at,
                    source=source,
                    category=article_category,
                )
                articles.append(article)

            except Exception as e:
                logger.debug(
                    f"[TheNewsAPI] Skipped item url='{url[:60]}': {e}"
                )
                continue

        return articles
