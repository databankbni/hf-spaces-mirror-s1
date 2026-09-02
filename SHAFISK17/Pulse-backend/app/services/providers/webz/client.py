"""
providers/webz/client.py
─────────────────────────────────────────────────────────────────────────────
The Webz.io Provider for Segmento Pulse.

What this does:
    Fetches enterprise-grade news articles from Webz.io's News API Lite.
    Webz crawls 3.5 million articles per day from across the open web,
    making it one of the richest news sources we have available.

Paid provider — needs WEBZ_API_KEY in your .env file.
Position 6 in the PAID_CHAIN (absolute final paid failover).

── THE MONTHLY BUDGET PROBLEM AND HOW WE SOLVE IT ──────────────────────────

Webz free tier gives us 1,000 calls per MONTH — not per day.
Our scheduler runs many categories every hour. Without a limit, we would
exhaust the entire 1,000-call monthly budget in less than 48 hours.

Our fix: daily_limit = 30 inside this class.
The quota tracker caps us at 30 calls per calendar day.
30 calls/day × 30 days = 900 calls/month — safely under 1,000.
This paces the budget across the whole month as an even, predictable cost.

Math visible to future engineers:
    1,000 calls ÷ 30 days = 33.3 calls/day max to exactly hit the limit.
    We use 30 to leave a 10% safety margin for edge cases (month resets,
    server restarts that lose the quota counter's in-memory state, etc.).

── THE NESTED IMAGE PROBLEM AND HOW WE SOLVE IT ─────────────────────────────

Webz does not put images at the top level of each article object.
Instead, the image is buried inside a nested 'thread' object like this:

    {
        "title": "Article Title",
        "url": "https://...",
        "thread": {
            "site_full":   "techcrunch.com",   ← source name is here too
            "main_image":  "https://..."        ← image is here
        },
        "text": "Full article body (thousands of words)..."
    }

Our fix: We safely "drill down" using chained .get() calls.
    thread = item.get("thread") or {}
    image_url = thread.get("main_image") or ""

    If 'thread' is missing → {} (empty dict, no crash)
    If 'main_image' is missing → "" (empty string, no crash)
    Either way, the pipeline gets a clean empty string for the fallback image.

── THE FULL TEXT BODY PROBLEM AND HOW WE SOLVE IT ──────────────────────────

Webz provides the COMPLETE article body in the 'text' field — this can be
thousands of words. Storing that in our database is too large and risks
reproducing copyright-protected content.

Our fix: Truncate to the first 200 characters (same approach as Phase 8).
200 characters is enough for a preview. Our newsletter system uses the
description field but also has its own 160-char cap, so anything beyond
200 already has no use downstream.
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
from app.config import settings
# Phase 16: Import the Redis counter utility for dual-layer budget protection.
# Webz has the strictest budget of all three paid providers — 1,000 calls per
# MONTH. Without restart-proof counters, a restart-heavy day can exhaust the
# entire monthly budget in a few hours. Two Redis keys protect us:
#   1. Daily key ("webz", today_str) — caps us at 30/day
#   2. Monthly key ("webz_month", month_str) — caps us at 900/month total
from app.services.utils.provider_state import (
    get_provider_counter,
    increment_provider_counter,
)

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# Webz.io News API Lite endpoint
WEBZ_API_URL = "https://api.webz.io/newsApiLite"

# Request timeout in seconds. Enterprise APIs are usually fast.
HTTP_TIMEOUT_SECONDS = 10.0

# Articles to request per call. Keeping this modest saves the budget
# because Webz deducts from quota based on results returned, not just calls.
ARTICLES_PER_REQUEST = 10

# Maximum characters to keep from the article body for the description field.
# Matches Phase 8's WorldNewsAI approach for consistency.
DESCRIPTION_MAX_CHARS = 200

# ── REFERENCE BACKUP (no longer used at runtime — Phase 22) ─────────────────
# The old, hardcoded keyword phrases for Webz's free-text search.
# The live query is now built dynamically by build_dynamic_query() below,
# applying the full Phase 19 taxonomy with UTC-clock round-robin rotation.
# To revert, replace the dynamic call in fetch_news() with:
#     search_query = CATEGORY_QUERY_MAP.get(category, f"technology {category}")
# Category → search query translation.
CATEGORY_QUERY_MAP = {
    'ai':                      'artificial intelligence machine learning',
    'data-security':           'data security cybersecurity breach hacking',
    'data-governance':         'data governance compliance policy',
    'data-privacy':            'data privacy GDPR regulation',
    'data-engineering':        'data engineering pipeline ETL spark',
    'data-management':         'data management master data catalog',
    'business-intelligence':   'business intelligence analytics BI tools',
    'business-analytics':      'business analytics data-driven decisions',
    'customer-data-platform':  'customer data platform CDP personalization',
    'data-centers':            'data center infrastructure hyperscaler',
    'cloud-computing':         'cloud computing technology platform',
    'magazines':               'technology news innovation',
    'data-laws':               'AI regulation data law privacy act',
    'cloud-aws':               'Amazon AWS cloud services',
    'cloud-azure':             'Microsoft Azure cloud platform',
    'cloud-gcp':               'Google Cloud Platform GCP services',
    'cloud-oracle':            'Oracle Cloud OCI database',
    'cloud-ibm':               'IBM Cloud Red Hat OpenShift',
    'cloud-alibaba':           'Alibaba Cloud Aliyun technology',
    'cloud-digitalocean':      'DigitalOcean cloud developer platform',
    'cloud-huawei':            'Huawei Cloud services technology',
    'cloud-cloudflare':        'Cloudflare CDN security network',
}


class WebzProvider(NewsProvider):
    """
    Fetches enterprise-grade news articles from Webz.io News API Lite.

    Paid provider — 1,000 calls/month free tier, paced to 30/day.
    Position 6 in the PAID_CHAIN (deepest paid failover).
    Only fires when all 5 providers above it have failed or hit limits.
    Requires WEBZ_API_KEY in the .env file.

    Usage (wired in Phase 10):
        provider = WebzProvider(api_key="your_key_here")
        articles = await provider.fetch_news(category="ai", limit=10)
    """

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key=api_key)

        # 30 calls/day × 30 days = 900/month — safely under the 1,000 cap.
        # The quota tracker enforces this limit before each call.
        # 10% safety margin included for server restart edge cases.
        self.daily_limit = 30

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN ENTRY POINT — called by the aggregator's PAID WATERFALL
    # ─────────────────────────────────────────────────────────────────────────

    async def fetch_news(self, category: str, limit: int = 10) -> List[Article]:
        """
        Fetch news articles from Webz.io for the given category.

        Args:
            category (str): Our internal category slug (e.g., "ai").
                            Translated to a keyword query via CATEGORY_QUERY_MAP.
            limit (int):    Max articles to return. Kept at 10 to conserve
                            the monthly call budget (Webz charges per result).

        Returns:
            List[Article]: Mapped Article objects. Returns [] on any failure.
        """
        if not self.api_key:
            logger.debug("[Webz] No API key configured — skipping.")
            return []

        # ── PHASE 16: Dual-layer Redis budget guard ────────────────────────
        #
        # Webz is the most budget-constrained provider we have: 1,000 calls/MONTH.
        # We protect it with TWO independent Redis counters running in parallel.
        #
        # Gate 1 — DAILY: Stops at 30 calls/day to pace spending evenly.
        #   Redis key: "provider:state:webz:calls:2026-03-03"  (TTL: 24h)
        #
        # Gate 2 — MONTHLY: Stops at 900 calls/month (10% safety margin on 1,000).
        #   Redis key: "provider:state:webz_month:calls:2026-03" (TTL: 30 days)
        #   Note: The key name includes the month string ("2026-03").
        #   When April starts, the key name changes to "2026-04" automatically
        #   — no manual cleanup needed. The old March key expires via TTL.
        #
        # Either gate being exhausted blocks the call completely.
        # Fail-safe design: if Redis is down, both return 999999 — call is skipped.
        today_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        month_str  = datetime.now(timezone.utc).strftime("%Y-%m")

        daily_calls   = await get_provider_counter("webz",       today_str)
        monthly_calls = await get_provider_counter("webz_month", month_str)

        # Hard monthly ceiling: 900 (leaving 100 as safety buffer on the 1,000 limit)
        MONTHLY_HARD_LIMIT = 900

        if daily_calls >= self.daily_limit:
            logger.warning(
                "[Webz] Daily Redis budget exhausted — %d/%d calls used today. "
                "Skipping to protect the monthly quota.",
                daily_calls, self.daily_limit
            )
            self.mark_rate_limited()
            return []

        if monthly_calls >= MONTHLY_HARD_LIMIT:
            logger.warning(
                "[Webz] Monthly Redis budget exhausted — %d/%d calls used this month. "
                "No more Webz calls until next month to protect the 1,000-call limit.",
                monthly_calls, MONTHLY_HARD_LIMIT
            )
            self.mark_rate_limited()
            return []

        # ── Phase 22: Dynamic query builder (Gate 1 alignment) ───────────────
        # build_dynamic_query uses the full Phase 19 taxonomy with the
        # Anchor + Round-Robin strategy: 3 anchor terms always included +
        # 4 rotating niche terms, changed by the UTC hour.
        #
        # api_type="gnews" → space-separated (e.g. 'openai anthropic llm datbricks')
        # Webz uses free-text search (like Google), which naturally understands
        # space-separated terms — matching how CATEGORY_QUERY_MAP was formatted.
        from app.utils.query_builder import build_dynamic_query
        search_query = build_dynamic_query(category, api_type="gnews")

        params = {
            "token":    self.api_key,
            "q":        search_query,
            "language": "english",
            "size":     min(limit, ARTICLES_PER_REQUEST),
            # NOTE: No date filters applied here intentionally.
            # Our freshness gate in data_validation.is_valid_article()
            # handles date boundaries accurately using IST windows.
            # Adding date filters here would add timezone conversion risk.
        }

        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
                print(
                    f"[Webz] Fetching '{category}' "
                    f"(query='{search_query[:40]}...')..."
                )
                response = await client.get(WEBZ_API_URL, params=params)

                # ── HTTP 402: Monthly budget exhausted ────────────────────
                # Webz uses 402 to mean "you have no more credits this month".
                # We mark as rate-limited so the circuit breaker respects it.
                if response.status_code == 402:
                    logger.warning(
                        "[Webz] HTTP 402 — monthly call budget exhausted. "
                        "No more calls until quota resets at month end."
                    )
                    self.mark_rate_limited()
                    return []

                # ── HTTP 401: Bad API key ─────────────────────────────────
                if response.status_code == 401:
                    logger.error(
                        "[Webz] HTTP 401 — API key is invalid or expired. "
                        "Check WEBZ_API_KEY in your .env file."
                    )
                    self.status = ProviderStatus.ERROR
                    return []

                # ── HTTP 429: Too many requests (short-term rate limit) ───
                if response.status_code == 429:
                    self.handle_429()
                    return []

                # ── Any other non-200 ─────────────────────────────────────
                if response.status_code != 200:
                    logger.warning(f"[Webz] Unexpected HTTP {response.status_code}.")
                    return []

                # ── Parse the response ────────────────────────────────────
                self.request_count += 1   # Keep RAM shadow in sync for debugging
                data = response.json()

                # Webz wraps the article list in a 'posts' key at the top level.
                raw_posts = data.get("posts", [])

                if not raw_posts:
                    logger.info(f"[Webz] No articles returned for '{category}'.")
                    return []

                articles = self._map_articles(raw_posts, category)

                # ── PHASE 16: Increment BOTH Redis counters after a successful call ──
                # The monthly counter uses a 30-day TTL (2592000 seconds).
                # This is long enough to outlive any calendar month.
                # The key name ("webz_month:calls:2026-03") changes with each month
                # so old keys just fade away on their own without our help.
                await increment_provider_counter("webz",       today_str, expire_seconds=86400)
                await increment_provider_counter("webz_month", month_str, expire_seconds=2592000)

                logger.info("[Webz] Got %d articles for '%s'.", len(articles), category)
                return articles

        except httpx.TimeoutException:
            logger.warning("[Webz] Request timed out.")
            return []
        except Exception as e:
            logger.error(f"[Webz] Unexpected error: {e}", exc_info=True)
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE HELPER — maps raw JSON posts to Article objects
    # ─────────────────────────────────────────────────────────────────────────

    def _map_articles(self, raw_posts: list, category: str) -> List[Article]:
        """
        Convert Webz.io JSON 'posts' items into Segmento Pulse Article objects.

        Key challenges handled here:
            1. Nested image — lives inside posts[].thread.main_image
            2. Nested source — lives inside posts[].thread.site_full
            3. Full text body — truncated to 200 characters
            4. Published date — Webz uses ISO 8601, our model accepts it directly

        Webz field              →  Article field
        ─────────────────────────────────────────
        title                   →  title
        url                     →  url
        thread.site_full        →  source       (nested — safe .get() chain)
        thread.main_image       →  image_url    (nested — safe .get() chain)
        published               →  published_at
        text (truncated 200)    →  description

        Args:
            raw_posts (list): The 'posts' array from the API response.
            category (str):   The aggregator's category for routing.

        Returns:
            List[Article]: Clean Article objects ready for the pipeline.
        """
        articles: List[Article] = []

        for item in raw_posts:
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

            # ── Published Date ────────────────────────────────────────────
            # Webz returns ISO 8601 format (e.g., "2026-03-03T06:00:00.000+0000").
            # Our Article model's published_at validator handles this directly.
            published_at = item.get("published") or ""

            # ── Nested: Source and Image ──────────────────────────────────
            # The 'thread' field is a nested dictionary containing both.
            # We extract it once, then pull from it safely.
            # If 'thread' is missing for any reason, we fall back to an empty
            # dict {} so the chained .get() calls below don't crash.
            thread = item.get("thread") or {}

            # Source: the full domain name of the publishing site.
            # Example: "techcrunch.com" or "thenextweb.com"
            source = (thread.get("site_full") or "Webz").strip()
            if not source:
                source = "Webz"

            # Image: the main article image from the thread context.
            # Buried one level deep — safe because of the `or {}` fallback above.
            image_url = (thread.get("main_image") or "").strip()

            # ── Description (TRUNCATED full article body) ─────────────────
            # 'text' contains the complete article body — potentially thousands
            # of words. We keep only the first 200 characters as a preview.
            # This protects us from database bloat and copyright issues.
            raw_text = (item.get("text") or "").strip()
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
                    # Unknown/empty categories route to 'News Articles'.
                    category=category,
                )
                articles.append(article)

            except Exception as e:
                logger.debug(f"[Webz] Skipped post '{title[:50]}': {e}")
                continue

        return articles
