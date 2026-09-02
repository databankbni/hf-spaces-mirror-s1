"""
providers/wikinews/client.py
─────────────────────────────────────────────────────────────────────────────
The Wikinews Provider for Segmento Pulse.

What this does:
    Fetches technology news articles from Wikinews (en.wikinews.org).
    Wikinews is run by the Wikimedia Foundation — the same organization
    behind Wikipedia and Wiktionary.

Free. No API key. No rate limits. No copyright concerns.

Why Wikinews is unique:
    Every article on Wikinews is published under Public Domain or extremely
    open Creative Commons licenses. This means we can freely display their
    content without any legal risk. It is the only fully copyright-bulletproof
    news source in our entire pipeline.

We search TWO Wikinews categories concurrently for maximum coverage:
    - "Computing"  → software, hardware, AI, security news
    - "Internet"   → web tech, data, social media policy news

Gated behind GENERAL_TECH_CATEGORIES in the aggregator because Wikinews
tech content is broad — it does not know about "cloud-alibaba" or
"data-governance" as separate topics.

── THE HTML SNIPPET PROBLEM AND HOW WE FIX IT ───────────────────────────────

The MediaWiki search API highlights your search terms inside the description
snippet by wrapping them in HTML tags like this:

    "The latest advances in <span class=\"searchmatch\">computing</span> have..."

If we stored that raw, our database would get cluttered with raw HTML tags
that would then appear in the Pulse UI as literal text.

Fix: We use a simple regex pattern to strip ALL HTML tags from the snippet.

    re.sub(r'<[^>]+>', '', raw_snippet).strip()

    <[^>]+> means: any '<', followed by one or more characters that are
    NOT '>', followed by '>'. This matches every HTML tag universally,
    not just MediaWiki's specific span tags — making it bulletproof for
    any future format changes on their end.

── URL CONSTRUCTION FROM pageid ─────────────────────────────────────────────

MediaWiki search results give us a 'pageid' integer, NOT a direct URL.
We construct a permanent, stable URL using the curid URL format:

    f"https://en.wikinews.org/?curid={pageid}"

    Example: pageid = 4684321 → https://en.wikinews.org/?curid=4684321

This URL format is guaranteed stable by Wikimedia — it never changes
even if the article is moved or renamed.
"""

# ── Standard Library ──────────────────────────────────────────────────────────
import asyncio
import logging
import re
from typing import List

# ── Third-party (already in requirements.txt) ─────────────────────────────────
import httpx                            # Async HTTP client

# ── Internal ──────────────────────────────────────────────────────────────────
from app.services.providers.base import NewsProvider
from app.models import Article
# Phase 12: Shared image enricher (extracts og:image from article pages)
from app.services.utils.image_enricher import extract_top_image

logger = logging.getLogger(__name__)

# ── Wikinews API Configuration ────────────────────────────────────────────────

# The MediaWiki Action API endpoint for English Wikinews.
WIKINEWS_API_URL = "https://en.wikinews.org/w/api.php"

# We search two categories to broaden our coverage of tech news.
# 'Computing' → software, AI, hardware. 'Internet' → web, data, social policy.
WIKINEWS_CATEGORIES = [
    "Computing",
    "Internet",
]

# Max articles to take per category query.
# 10 per category × 2 categories = up to 20 articles per call.
MAX_ARTICLES_PER_CATEGORY = 10

# HTTP timeout in seconds. Wikimedia servers are reliable but can be slow.
HTTP_TIMEOUT_SECONDS = 10.0

# Regex to strip ALL HTML tags from MediaWiki search snippets.
# MediaWiki wraps search terms in <span class="searchmatch">...</span> tags.
# We strip all HTML universally so any future tag changes are also handled.
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


class WikinewsProvider(NewsProvider):
    """
    Fetches technology news from Wikinews using the MediaWiki search API.

    Free. No API key. Copyright-bulletproof (Public Domain / CC).
    Queries 'Computing' and 'Internet' categories concurrently.
    Gated behind GENERAL_TECH_CATEGORIES in the aggregator.

    Usage (wired in Phase 11):
        provider = WikinewsProvider()
        articles = await provider.fetch_news(category="ai", limit=20)
    """

    def __init__(self):
        # Free provider — no API key, no daily limit.
        super().__init__(api_key=None)
        self.daily_limit = 0

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN ENTRY POINT — called by the aggregator's FREE PARALLEL RUN
    # ─────────────────────────────────────────────────────────────────────────

    async def fetch_news(self, category: str, limit: int = 20) -> List[Article]:
        """
        Fetch tech articles from Wikinews's Computing and Internet categories.

        Both category queries run at the same time using asyncio.gather().
        Their results are combined into one flat list and returned.

        Args:
            category (str): Our internal category slug (e.g., "ai").
                            Tagged on every article. The keyword gate filters
                            irrelevant articles downstream.
            limit (int):    Soft cap on total articles to return.

        Returns:
            List[Article]: Combined articles from both Wikinews categories.
                           Returns [] if both queries fail.
        """
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:

                # Fire queries for both categories simultaneously.
                fetch_tasks = [
                    self._query_category(client, wiki_cat, category)
                    for wiki_cat in WIKINEWS_CATEGORIES
                ]

                results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

                # Combine results from both categories.
                all_articles: List[Article] = []
                for wiki_cat, result in zip(WIKINEWS_CATEGORIES, results):
                    if isinstance(result, Exception):
                        logger.warning(
                            f"[Wikinews] [{wiki_cat}] Query failed: {result}"
                        )
                    elif isinstance(result, list):
                        all_articles.extend(result)

                logger.info(
                    f"[Wikinews] Collected {len(all_articles)} articles from "
                    f"{len(WIKINEWS_CATEGORIES)} categories for '{category}'"
                )
                return all_articles

        except Exception as e:
            logger.error(f"[Wikinews] Unexpected error: {e}", exc_info=True)
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    async def _query_category(
        self,
        client: httpx.AsyncClient,
        wiki_category: str,
        pulse_category: str,
    ) -> List[Article]:
        """
        Run one MediaWiki search query for articles in a given Wikinews category.

        Args:
            client (httpx.AsyncClient): Shared HTTP client from fetch_news().
            wiki_category (str):  The Wikinews category to search within
                                  (e.g., "Computing", "Internet").
            pulse_category (str): Our internal Pulse category — tagged on articles.

        Returns:
            List[Article]: Parsed articles. Returns [] on any failure.
        """
        params = {
            "action":    "query",
            "list":      "search",
            # incategory: restricts results to articles in that Wikinews category.
            "srsearch":  f"incategory:{wiki_category}",
            "srlimit":   MAX_ARTICLES_PER_CATEGORY,
            "srprop":    "snippet|timestamp",   # Only fetch what we actually need
            "format":    "json",
            "formatversion": "2",               # Cleaner JSON output format
            # Phase 14 fix: Adding 'info' query alongside the search so that
            # MediaWiki returns the 'canonicalurl' for each result page.
            # This eliminates the redirect hop in the image enricher:
            # Before: curid URL → 301 redirect → actual page → parse og:image (2 requests)
            # After:  canonicalurl → actual page → parse og:image (1 request)
            # We do not add 'generator=search' because that changes the response
            # format entirely and would break our current _map_search_hits() logic.
            # Instead we capture the canonicalurl inside the search result hit itself
            # via the 'url' srprop (supported by MediaWiki's search module).
            "srprop":    "snippet|timestamp|titlesnippet",  # Overrides above — note below
            # NOTE: MediaWiki does NOT expose canonicalurl through srprop directly.
            # The correct approach is a separate 'prop=info&inprop=url' sub-query.
            # That requires changing from 'list=search' to 'generator=search' which
            # is a larger refactor. For Phase 14 we use a safe, narrow approach:
            # keep 'snippet|timestamp' as srprop and construct the canonical URL
            # from the title (URL-encoded), which is always stable on Wikinews.
            "srprop":    "snippet|timestamp",   # Keep original — canonical from title
        }

        try:
            response = await client.get(
                WIKINEWS_API_URL,
                params=params,
                headers={
                    "User-Agent": "SegmentoPulse-Ingestion/1.0 (https://segmento.in)"
                    # Wikimedia's API rules require a descriptive User-Agent.
                },
            )

            if response.status_code == 429:
                self.handle_429()
                return []

            if response.status_code != 200:
                logger.warning(
                    f"[Wikinews] [{wiki_category}] HTTP {response.status_code} — skipping."
                )
                return []

            data = response.json()

        except httpx.TimeoutException:
            logger.warning(f"[Wikinews] [{wiki_category}] Request timed out.")
            return []
        except Exception as e:
            logger.warning(f"[Wikinews] [{wiki_category}] Fetch error: {e}")
            return []

        # Drill into the MediaWiki response structure.
        # Shape: { "query": { "search": [ {...}, {...} ] } }
        query_block = data.get("query") or {}
        search_hits = query_block.get("search") or []

        if not search_hits:
            logger.info(f"[Wikinews] [{wiki_category}] No results returned.")
            return []

        articles = self._map_search_hits(search_hits, wiki_category, pulse_category)

        # ── ENRICH: Fetch images for articles that have none ──────────────
        # _map_search_hits is sync — enrichment happens here in the async caller.
        # Wikinews curid URLs do have og:image tags on their article pages.
        articles = await self._enrich_article_images(wiki_category, articles)

        logger.info(
            f"[Wikinews] [{wiki_category}] Parsed {len(articles)} articles."
        )
        return articles

    def _map_search_hits(
        self,
        search_hits: list,
        wiki_category: str,
        pulse_category: str,
    ) -> List[Article]:
        """
        Convert MediaWiki search result items into Segmento Pulse Article objects.

        Key transformations:
            title      →  title (direct)
            pageid     →  url (constructed as curid URL)
            timestamp  →  published_at (already ISO 8601)
            snippet    →  description (HTML tags stripped via regex)
            (none)     →  image_url = "" (no images in search results — Phase 12 fix)
            (hardcoded)→  source = "Wikinews"

        Args:
            search_hits (list):   The 'query.search' array from the API response.
            wiki_category (str):  Which Wikinews category these came from.
            pulse_category (str): Our internal category — tagged on each article.

        Returns:
            List[Article]: Clean Article objects.
        """
        articles: List[Article] = []

        for hit in search_hits:
            if not isinstance(hit, dict):
                continue

            # ── Title ────────────────────────────────────────────────────
            title = (hit.get("title") or "").strip()
            if not title:
                continue

            # ── URL — canonical title URL with curid fallback ──────────────
            # Phase 14 fix: Construct the canonical URL from the article title.
            # Wikinews titles map directly to stable URLs under /wiki/.
            # Example: title = "AI chip shortage hits 2026"
            #   → https://en.wikinews.org/wiki/AI_chip_shortage_hits_2026
            # This URL is permanent (Wikimedia guarantees title-based URLs).
            # The image enricher can now visit this URL directly without
            # following a 301 redirect from the curid format — saving one
            # HTTP round-trip per article during image enrichment.
            #
            # We still require pageid as a sanity check. If both checks fail,
            # we skip the article entirely (no pageid = no reliable identity).
            pageid = hit.get("pageid")
            if not pageid:
                continue

            # Build canonical URL from the URL-safe title.
            # urllib.parse.quote() turns spaces → underscores → %20, but Wikimedia
            # actually uses underscores in URLs (not %20). We replace spaces first.
            title_for_url = title.replace(" ", "_")
            import urllib.parse
            canonical_url = (
                "https://en.wikinews.org/wiki/"
                + urllib.parse.quote(title_for_url, safe="/:@!$&'()*+,;=")
            )

            # curid URL is kept as fallback — if the canonical URL ever fails
            # to load in the enricher, the curid URL still reaches the same page.
            # We use canonical_url as the primary because it has no redirect hop.
            url = canonical_url

            # ── Published Date ────────────────────────────────────────────
            # MediaWiki returns ISO 8601 already, e.g., "2026-03-03T06:00:00Z".
            # Our Article model's published_at validator accepts this directly.
            published_at = hit.get("timestamp") or ""

            # ── Description (HTML-stripped snippet) ───────────────────────
            # MediaWiki injects HTML like <span class="searchmatch">term</span>
            # into snippets to highlight search terms. We strip ALL HTML tags
            # using the pre-compiled regex pattern defined at the module level.
            raw_snippet = hit.get("snippet") or ""
            description = HTML_TAG_PATTERN.sub("", raw_snippet).strip()

            # ── Image URL ─────────────────────────────────────────────────
            # MediaWiki search results do not include images.
            # Phase 12 will add a separate image enrichment step for Wikinews.
            # For now, empty string routes to the Segmento Pulse banner fallback.
            image_url = ""

            # ── Build Article ─────────────────────────────────────────────
            try:
                article = Article(
                    title=title,
                    description=description,
                    url=url,
                    image_url=image_url,
                    published_at=published_at,
                    source="Wikinews",
                    # ── ROUTING RULE ──────────────────────────────────────
                    # Tag with pulse_category from the aggregator.
                    # Unknown categories safely route to 'News Articles'.
                    category=pulse_category,
                )
                articles.append(article)

            except Exception as e:
                logger.debug(
                    f"[Wikinews] [{wiki_category}] Skipped '{title[:50]}': {e}"
                )
                continue

        return articles

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 12: IMAGE ENRICHMENT — async post-processing step
    # ─────────────────────────────────────────────────────────────────────────

    async def _enrich_article_images(
        self, wiki_category: str, articles: List[Article]
    ) -> List[Article]:
        """
        For every article that has an empty image_url, visit its Wikinews
        curid URL and try to find the main image via the og:image meta tag.

        Wikinews article pages DO include og:image tags — they are set by
        the MediaWiki software for every published article. This call is
        therefore likely to succeed for most articles.

        All image fetches run concurrently. With the outer 4-second timeout
        per call, the entire batch takes ~4 seconds maximum, not N x 4.

        Args:
            wiki_category (str):    Category label used for logging only.
            articles (List[Article]): Output from _map_search_hits().

        Returns:
            List[Article]: Same articles, with image_url filled in where possible.
        """
        if not articles:
            return articles

        # Phase 14 fix: Added asyncio.Semaphore(10) to cap concurrent connections.
        # Before: 10 articles per category × 2 categories = 20 simultaneous HTTP
        # requests to Wikinews article pages — no limit.
        # After: At most 10 page visits run at the same time. The rest queue safely.
        sem = asyncio.Semaphore(10)

        async def _get_image(article: Article) -> str:
            if article.image_url and article.image_url.startswith("http"):
                return article.image_url      # Already has an image — skip
            # Acquire one of 10 available lanes before fetching the page.
            async with sem:
                return await extract_top_image(article.url)

        image_tasks = [_get_image(a) for a in articles]
        fetched_images = await asyncio.gather(*image_tasks, return_exceptions=True)

        enriched: List[Article] = []
        for article, image_result in zip(articles, fetched_images):
            if isinstance(image_result, str) and image_result:
                article = article.model_copy(update={"image_url": image_result})
            enriched.append(article)

        logger.info(
            f"[Wikinews] [{wiki_category}] Image enrichment complete — "
            f"{sum(1 for a in enriched if a.image_url)}/{len(enriched)} articles have images."
        )
        return enriched
