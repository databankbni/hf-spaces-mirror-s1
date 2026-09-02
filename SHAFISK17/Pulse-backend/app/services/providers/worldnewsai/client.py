"""
providers/worldnewsai/client.py
─────────────────────────────────────────────────────────────────────────────
The WorldNewsAI Provider for Segmento Pulse.

What this does:
    Fetches technology news from WorldNewsAI.com — a global news crawler
    that indexes tens of thousands of sources worldwide, including many
    non-English and non-US-centric publications.

Paid provider — needs WORLDNEWS_API_KEY in your .env file.
Position 5 in the PAID_CHAIN (last paid failover).

── THE CRITICAL QUOTA PROBLEM AND HOW WE SOLVE IT ──────────────────────────

WorldNewsAI does NOT use a simple "100 requests per day" model.
It uses a POINT system:
    - Each search call costs points
    - Each article returned in the response costs additional points
    - If you run out of points, the API returns HTTP 402 (not 429)

If we called this for all 22 categories every hour, we would exhaust our
free-tier point budget before lunchtime.

Our two-layer protection:
    1. Position 5 in PAID_CHAIN: Only fires as the last fallback after
       GNews, NewsAPI, NewsData, and TheNewsAPI have all failed.
       In a healthy system, it will rarely be called at all.
    2. daily_limit = 50: The quota tracker caps total calls per day.
       Once 50 calls are used, the circuit breaker prevents further calls.

── THE CONTENT SAFETY PROBLEM AND HOW WE SOLVE IT ──────────────────────────

WorldNewsAI returns the FULL article body in the 'text' field.
A typical article body is 500-3,000 words — far too large to store in
our database for each article, and potentially a copyright issue.

Fix: We take only the first 200 characters from the 'text' field
and use that as the article's description. This is the same "snippet"
approach used by Google News, Bing News, and other aggregators.
200 characters is enough to show a preview without reproducing the article.
"""

# ── Standard Library ──────────────────────────────────────────────────────
import logging
from datetime import datetime, timezone
from typing import List, Optional

# ── Third-party (already in requirements.txt) ──────────────────────────────────
import httpx                            # Async HTTP client

# ── Internal ─────────────────────────────────────────────────────────────────
from app.services.providers.base import NewsProvider, ProviderStatus
from app.models import Article
from app.config import settings
# Phase 16: Import the Redis counter utility to make the daily budget
# restart-proof. Without this, self.request_count lives in RAM and resets
# to 0 on every Hugging Face Space restart, letting us overspend the quota.
from app.services.utils.provider_state import (
    get_provider_counter,
    increment_provider_counter,
)

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# WorldNewsAI search endpoint (v1)
WORLDNEWSAI_SEARCH_URL = "https://api.worldnewsapi.com/search-news"

# Request timeout in seconds
HTTP_TIMEOUT_SECONDS = 10.0

# Articles per call. Keep it modest to save points per request.
ARTICLES_PER_REQUEST = 10

# How many characters of article body text to keep as the description.
# Enough for a readable summary, small enough to avoid copyright concerns
# and database bloat. Matches the 200-char limit used by our RSS parser.
DESCRIPTION_MAX_CHARS = 200

# ── REFERENCE BACKUP (no longer used at runtime — Phase 22) ─────────────────
# The old, hardcoded keyword phrases for WorldNewsAI's free-text search.
# The live query is now built dynamically by build_dynamic_query() below,
# applying the full Phase 19 taxonomy with UTC-clock round-robin rotation.
# To revert, replace the dynamic call in fetch_news() with:
#     search_text = CATEGORY_QUERY_MAP.get(category, "technology news")
CATEGORY_QUERY_MAP = {
    'ai':                      'artificial intelligence machine learning',
    'data-security':           'data security cybersecurity breach',
    'data-governance':         'data governance compliance regulation',
    'data-privacy':            'data privacy GDPR CCPA',
    'data-engineering':        'data engineering pipeline ETL',
    'data-management':         'data management master data catalog',
    'business-intelligence':   'business intelligence analytics BI',
    'business-analytics':      'business analytics reporting dashboards',
    'customer-data-platform':  'customer data platform CDP',
    'data-centers':            'data center infrastructure colocation',
    'cloud-computing':         'cloud computing technology',
    'magazines':               'technology news',
    'data-laws':               'data privacy law regulation AI act',
    'cloud-aws':               'Amazon Web Services AWS cloud',
    'cloud-azure':             'Microsoft Azure cloud',
    'cloud-gcp':               'Google Cloud Platform GCP',
    'cloud-oracle':            'Oracle Cloud OCI',
    'cloud-ibm':               'IBM Cloud Red Hat',
    'cloud-alibaba':           'Alibaba Cloud technology',
    'cloud-digitalocean':      'DigitalOcean cloud platform',
    'cloud-huawei':            'Huawei Cloud technology',
    'cloud-cloudflare':        'Cloudflare network security',
}


class WorldNewsAIProvider(NewsProvider):
    """
    Fetches global technology news from WorldNewsAI.com.

    Paid provider (point-based quota) — position 5 in the PAID_CHAIN.
    Only fires when GNews, NewsAPI, NewsData, and TheNewsAPI have all failed.
    Requires WORLDNEWS_API_KEY in the .env file.

    Usage (wired in Phase 8):
        provider = WorldNewsAIProvider(api_key="your_key_here")
        articles = await provider.fetch_news(category="ai", limit=10)
    """

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key=api_key)

        # Phase 16: This value is now the CEILING checked in Redis, not just
        # a RAM counter. Even if the server restarts mid-day, Redis remembers
        # exactly how many calls we have already made today.
        self.daily_limit = 50

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN ENTRY POINT — called by the aggregator's PAID WATERFALL
    # ─────────────────────────────────────────────────────────────────────────

    async def fetch_news(self, category: str, limit: int = 10) -> List[Article]:
        """
        Fetch global technology news from WorldNewsAI.

        Args:
            category (str): Our internal category slug (e.g., "ai").
                            We look it up in CATEGORY_QUERY_MAP to get
                            the search text for the API call.
            limit (int):    Max articles to return. Kept at 10 by default
                            to conserve the point budget per call.

        Returns:
            List[Article]: Mapped Article objects. Returns [] on any failure.
        """
        if not self.api_key:
            logger.debug("[WorldNewsAI] No API key configured — skipping.")
            return []

        # ── PHASE 16: Redis-backed daily budget guard ────────────────────────
        # Check how many times we have already called WorldNewsAI TODAY
        # using the Redis counter (not self.request_count which lives in RAM).
        #
        # Today's date string (UTC) is used as part of the Redis key so the
        # counter automatically resets at midnight UTC without any manual work.
        # Example key: "provider:state:worldnewsai:calls:2026-03-03"
        #
        # If Redis is unreachable: get_provider_counter returns 999999
        # (fail-safe) so we skip the call rather than risk overspending.
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        current_calls = await get_provider_counter("worldnewsai", today_str)

        if current_calls >= self.daily_limit:
            logger.warning(
                "[WorldNewsAI] Daily Redis budget exhausted — %d/%d calls used today. "
                "Skipping to protect the API quota.",
                current_calls, self.daily_limit
            )
            self.mark_rate_limited()
            return []

        # ── Phase 22: Dynamic query builder (Gate 1 alignment) ───────────────
        # build_dynamic_query uses the full Phase 19 taxonomy with the
        # Anchor + Round-Robin strategy, selecting 3 anchor terms that never
        # change + 4 rotating niche terms driven by the current UTC hour.
        #
        # api_type="gnews" → space-separated format (e.g. 'openai anthropic llm')
        # WorldNewsAI's free-text search engine understands plain space-separated
        # words natively — this matches how CATEGORY_QUERY_MAP was already formatted.
        from app.utils.query_builder import build_dynamic_query
        search_text = build_dynamic_query(category, api_type="gnews")

        params = {
            "text":     search_text,
            "language": "en",
            "number":   min(limit, ARTICLES_PER_REQUEST),
            "api-key":  self.api_key,
            # NOTE: No date filters applied here intentionally.
            # WorldNewsAI supports 'earliest-publish-date' and
            # 'latest-publish-date', but our freshness gate handles
            # date filtering more accurately using IST boundaries.
        }

        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
                print(
                    f"[WorldNewsAI] Fetching '{category}' "
                    f"(query='{search_text[:40]}...')..."
                )
                response = await client.get(WORLDNEWSAI_SEARCH_URL, params=params)

                # ── HTTP 402: Point quota fully exhausted ─────────────────
                # 402 means we are out of points for today — not just rate
                # limited, but completely blocked until tomorrow's reset.
                # We mark the provider as RATE_LIMITED (not ERROR) so it can
                # recover after the scheduler's daily quota reset cycle.
                if response.status_code == 402:
                    logger.warning(
                        "[WorldNewsAI] HTTP 402 — point quota exhausted. "
                        "No more calls until tomorrow's reset."
                    )
                    self.mark_rate_limited()
                    return []

                # ── HTTP 401: Invalid or expired API key ──────────────────
                if response.status_code == 401:
                    logger.error(
                        "[WorldNewsAI] HTTP 401 — API key is invalid or expired. "
                        "Check WORLDNEWS_API_KEY in your .env file."
                    )
                    self.status = ProviderStatus.ERROR
                    return []

                # ── HTTP 429: Too many requests (short-term rate limit) ───
                if response.status_code == 429:
                    self.handle_429()
                    return []

                # ── Any other non-200 ─────────────────────────────────────
                if response.status_code != 200:
                    logger.warning(
                        f"[WorldNewsAI] Unexpected HTTP {response.status_code}."
                    )
                    return []

                # ── Parse the response ─────────────────────────────────────────
                self.request_count += 1   # Keep RAM shadow in sync for debugging
                data = response.json()

                # WorldNewsAI wraps articles in a top-level 'news' key
                raw_articles = data.get("news", [])

                if not raw_articles:
                    logger.info(
                        f"[WorldNewsAI] No articles returned for '{category}'."
                    )
                    return []

                articles = self._map_articles(raw_articles, category)

                # ── PHASE 16: Increment the Redis counter after a successful call ──
                # We only count successful 200 responses, not failures.
                # A failed call that returns [] should NOT burn our daily budget.
                await increment_provider_counter("worldnewsai", today_str)

                logger.info("[WorldNewsAI] Got %d articles for '%s'.", len(articles), category)
                return articles

        except httpx.TimeoutException:
            logger.warning("[WorldNewsAI] Request timed out.")
            return []
        except Exception as e:
            logger.error(f"[WorldNewsAI] Unexpected error: {e}", exc_info=True)
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE HELPER — maps raw JSON items to Article objects
    # ─────────────────────────────────────────────────────────────────────────

    def _map_articles(self, raw_articles: list, category: str) -> List[Article]:
        """
        Convert WorldNewsAI JSON items into Segmento Pulse Article objects.

        Key transformations:
            - 'text' field is truncated to 200 characters (body is too long)
            - 'authors' is a list — we join it with ", " into one string
            - 'image' maps directly to image_url

        WorldNewsAI field   →  Article field
        ──────────────────────────────────────
        title               →  title
        url                 →  url
        image               →  image_url
        publish_date        →  published_at
        authors (list)      →  source (joined)
        text (truncated)    →  description

        Args:
            raw_articles (list): The 'news' array from the API response.
            category (str):      The aggregator's category for routing.

        Returns:
            List[Article]: Clean Article objects ready for the pipeline.
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
            url = (item.get("url") or "").strip()
            if not url or not url.startswith("http"):
                continue

            # ── Image URL ─────────────────────────────────────────────────
            image_url = (item.get("image") or "").strip()

            # ── Published Date ────────────────────────────────────────────
            # WorldNewsAI returns ISO 8601 format (e.g., "2026-03-03 06:00:00")
            # Our Article model's published_at validator can handle this.
            published_at = item.get("publish_date") or ""

            # ── Source (from authors list) ────────────────────────────────
            # 'authors' is a list of names, e.g., ["Jane Doe", "John Smith"]
            # We join them into a comma-separated string for the source field.
            authors = item.get("authors") or []
            if isinstance(authors, list) and authors:
                # Filter out empty strings first, then join
                clean_authors = [a.strip() for a in authors if a and a.strip()]
                source = ", ".join(clean_authors) if clean_authors else "WorldNewsAI"
            else:
                source = "WorldNewsAI"

            # ── Description (TRUNCATED body text) ─────────────────────────
            # WorldNewsAI returns the FULL article body in 'text'.
            # This is thousands of words — we MUST truncate it.
            # 200 characters gives a readable preview without storing
            # copyright-protected full content in our database.
            raw_text = (item.get("text") or item.get("summary") or "").strip()
            if len(raw_text) > DESCRIPTION_MAX_CHARS:
                description = raw_text[:DESCRIPTION_MAX_CHARS] + "..."
            else:
                description = raw_text

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
                    # Unknown categories safely route to 'News Articles'.
                    category=category,
                )
                articles.append(article)

            except Exception as e:
                logger.debug(
                    f"[WorldNewsAI] Skipped item '{title[:50]}': {e}"
                )
                continue

        return articles
