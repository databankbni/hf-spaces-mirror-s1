"""
providers/hackernews/client.py
─────────────────────────────────────────────────────────────────────────────
The Hacker News Provider for Segmento Pulse.

What this does:
    Fetches the top stories from Hacker News — a community-voted list of the
    best tech articles on the internet. It is completely free to use and has
    no rate limits or API key requirement.

How the Hacker News API works (Two-Step Process):
    Step 1: Ask HN for a list of top story IDs (one big list)
    Step 2: For each ID, ask HN for that story's actual details

    We only take the top 30 IDs. If we tried 500 IDs (the full list),
    it would take too long and put unnecessary load on their server.
    30 is a safe, polite number that still gives us great content.

What we do about missing data:
    - No URL?       → Skip this story entirely (it's an "Ask HN" self-post).
                      Our database cannot link to a story without a URL.
    - No image?     → Set image_url = "". The frontend will use the
                      Segmento Pulse banner image as the default.
    - No summary?   → Set description = "". HN only provides the title
                      for external links, not a description.
    - Unix time?    → Convert to ISO 8601 string (our standard date format).

Client-side constraint note (from our architecture plan):
    Hacker News does NOT support any filtering. We cannot ask it for
    "only today's articles" or "only AI news". It gives us what it gives us.
    That is completely fine. Our data_validation pipeline (is_valid_article,
    is_relevant_to_category) will filter out old or off-topic articles
    automatically AFTER we fetch them. We just fetch and map here.
"""

# ── Standard Library ──────────────────────────────────────────────────────────
import asyncio                          # Lets us run multiple HTTP calls at the same time
import logging
from datetime import datetime, timezone
from typing import List, Optional

# ── Third-party (already in requirements.txt) ─────────────────────────────────
import httpx                            # Async HTTP client

# ── Internal ──────────────────────────────────────────────────────────────────
# We import only from our new base — no dependency on legacy news_providers.py
from app.services.providers.base import NewsProvider, ProviderStatus
from app.models import Article
# Phase 12: Shared image enricher (extracts og:image from article pages)
from app.services.utils.image_enricher import extract_top_image

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# The top of this list = the most upvoted stories on Hacker News right now
HN_TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"

# Template for fetching one story's full details by its ID
HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"

# How many top stories to fetch. Kept small to be polite to HN's servers.
# The full list has 500 stories — we only want the best 30.
TOP_STORIES_LIMIT = 30

# HTTP timeout in seconds. HN is fast, but we cap it to avoid hanging jobs.
HTTP_TIMEOUT_SECONDS = 10.0


class HackerNewsProvider(NewsProvider):
    """
    Fetches top stories from the Hacker News API.

    No API key needed. No rate limit. Completely free.

    Usage (once wired into the aggregator in Phase 3):
        provider = HackerNewsProvider()
        articles = await provider.fetch_news(category="magazines", limit=30)
    """

    def __init__(self):
        # Free provider — no API key needed, so we pass None to the base class.
        super().__init__(api_key=None)

        # daily_limit = 0 means "no limit". HN has no quota.
        self.daily_limit = 0

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 1 + 2 COMBINED: fetch_news() is the one method the aggregator calls
    # ─────────────────────────────────────────────────────────────────────────

    async def fetch_news(self, category: str, limit: int = 20) -> List[Article]:
        """
        Fetch the top stories from Hacker News.

        Args:
            category (str): The category passed in by the aggregator.
                            We store this on each article, but we cannot
                            actually filter HN results by it. The keyword
                            gate in data_validation.py will handle that.
            limit (int):    Maximum number of articles to return.
                            We cap this at TOP_STORIES_LIMIT (30) regardless.

        Returns:
            List[Article]: Validated Article objects from Hacker News.
                           Returns [] if the network is down or HN is unreachable.
        """
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:

                # ── STEP 1: Get the list of top story IDs ─────────────────
                top_ids = await self._fetch_top_ids(client)

                if not top_ids:
                    logger.warning("[HackerNews] Could not retrieve top story IDs.")
                    return []

                # Slice the list — we only want the top N IDs
                ids_to_fetch = top_ids[:min(limit, TOP_STORIES_LIMIT)]

                # ── STEP 2: Fetch all story details concurrently ───────────
                # Instead of fetching stories one-by-one (which would take ~30 seconds),
                # we launch all 30 HTTP requests at the same time using asyncio.gather().
                # All 30 requests fly out simultaneously and come back in ~1-2 seconds.
                fetch_tasks = [
                    self._fetch_single_item(client, story_id)
                    for story_id in ids_to_fetch
                ]
                raw_items = await asyncio.gather(*fetch_tasks, return_exceptions=True)

                # ── MAP: Convert raw HN items → Article objects ────────────
                articles = self._map_items_to_articles(raw_items, category)

                # ── ENRICH: Fetch images for articles that have none ───────
                # _map_items_to_articles is a sync function, so it cannot await.
                # We run image enrichment here in the async caller instead.
                # All image fetches run concurrently — the total extra wait
                # is ~4 seconds maximum (the outer timeout), not 30×4 seconds.
                articles = await self._enrich_article_images(articles)

                logger.info(
                    f"[HackerNews] Fetched {len(raw_items)} items → "
                    f"{len(articles)} valid articles for category='{category}'"
                )
                return articles

        except httpx.TimeoutException:
            logger.warning("[HackerNews] Request timed out. Will retry next cycle.")
            return []
        except Exception as e:
            # Catch-all: never let a HN failure crash the aggregator job
            logger.error(f"[HackerNews] Unexpected error: {e}", exc_info=True)
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE HELPERS — internal steps, not called by the aggregator
    # ─────────────────────────────────────────────────────────────────────────

    async def _fetch_top_ids(self, client: httpx.AsyncClient) -> List[int]:
        """
        Step 1: Ask Hacker News for the IDs of its top stories.

        Returns a list of integers like [39281947, 39281001, ...].
        Returns [] if HN is unreachable or returns an error.
        """
        try:
            response = await client.get(HN_TOP_STORIES_URL)

            if response.status_code == 429:
                self.handle_429()
                return []

            if response.status_code != 200:
                logger.warning(
                    f"[HackerNews] Top stories endpoint returned HTTP {response.status_code}"
                )
                return []

            ids = response.json()

            # Sanity check — make sure we got a list of numbers, not garbage
            if not isinstance(ids, list):
                logger.warning("[HackerNews] Unexpected response format for top IDs.")
                return []

            return ids

        except Exception as e:
            logger.error(f"[HackerNews] Failed to fetch top IDs: {e}")
            return []

    async def _fetch_single_item(
        self, client: httpx.AsyncClient, item_id: int
    ) -> Optional[dict]:
        """
        Step 2 (single unit): Fetch the details for one Hacker News story.

        Args:
            client (httpx.AsyncClient): Shared client passed from fetch_news().
            item_id (int): The numeric ID of the story to fetch.

        Returns:
            dict of story details, or None if the request failed.
        """
        url = HN_ITEM_URL.format(item_id=item_id)
        try:
            response = await client.get(url)

            if response.status_code == 429:
                self.handle_429()
                return None

            if response.status_code != 200:
                return None

            item = response.json()

            # HN can return null for deleted or dead items
            if not item:
                return None

            return item

        except Exception:
            # A single story failing should not cancel the other 29 stories
            return None

    def _map_items_to_articles(
        self, raw_items: list, category: str
    ) -> List[Article]:
        """
        Convert raw Hacker News JSON items into Segmento Pulse Article objects.

        This is where all the data transformation happens:
        - Unix timestamp → ISO 8601 string
        - Missing URL    → skip (self-posts cannot be stored)
        - Missing image  → "" (frontend uses Pulse banner)
        - Missing text   → "" (HN has no descriptions for external links)

        Args:
            raw_items (list): Results from asyncio.gather() — each is either
                              a dict (success) or None/Exception (failure).
            category (str):   The category string from the aggregator.
                              We pass it through as-is.

        Returns:
            List[Article]: Clean, valid Article objects ready for the pipeline.
        """
        articles: List[Article] = []

        for item in raw_items:

            # Skip anything that errored or returned null from HN
            if item is None or isinstance(item, Exception):
                continue

            # ── Check: Skip non-story types ───────────────────────────────
            # HN API also returns "job", "comment", "poll" types.
            # We only want "story" type — the actual articles.
            if item.get("type") != "story":
                continue

            # ── Check: Skip self-posts that have no external URL ──────────
            # "Ask HN", "Show HN", and other self-posts have no 'url' key.
            # Our database cannot store a meaningful link for these.
            url = item.get("url", "")
            if not url or not url.startswith("http"):
                continue

            # ── Check: Skip stories without a title ───────────────────────
            title = (item.get("title") or "").strip()
            if not title:
                continue

            # ── Convert: Unix timestamp → ISO 8601 string ─────────────────
            # HN stores time as seconds since 1970-01-01 (Unix epoch).
            # Example: 1709432800 → "2024-03-03T04:46:40+00:00"
            unix_time = item.get("time")
            if unix_time:
                published_at = datetime.fromtimestamp(
                    unix_time, tz=timezone.utc
                ).isoformat()
            else:
                # If HN somehow has no timestamp, use now as fallback.
                # The freshness gate in data_validation.py will still check it.
                published_at = datetime.now(tz=timezone.utc).isoformat()

            # ── Build the Article dict ─────────────────────────────────────
            # We use a plain dict here; the aggregator's validation layer
            # converts dicts → Article objects and runs all the checks.
            try:
                article = Article(
                    title=title,
                    description="",          # HN does not provide descriptions
                    url=url,
                    image_url="",            # HN does not provide images
                    published_at=published_at,
                    source="Hacker News",
                    # ── ROUTING RULE ──────────────────────────────────────
                    # We pass through whatever category the aggregator gave us.
                    # If the article doesn't match this category, the keyword
                    # gate in data_validation.is_relevant_to_category() will
                    # reject it safely — no routing damage to the database.
                    category=category,
                )
                articles.append(article)

            except Exception as e:
                # If one article fails Pydantic validation, log and skip it.
                # Never let one bad article break the whole batch.
                logger.debug(
                    f"[HackerNews] Skipped item id={item.get('id')}: {e}"
                )
                continue

        return articles

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 12: IMAGE ENRICHMENT — async post-processing step
    # ─────────────────────────────────────────────────────────────────────────

    async def _enrich_article_images(self, articles: List[Article]) -> List[Article]:
        """
        For every article that has an empty image_url, visit its URL and
        try to find the main image using the og:image HTML meta tag.

        Phase 14 fix: Added asyncio.Semaphore(10) to cap concurrent connections.

        Before this fix: 30 HN articles → 30 simultaneous HTTP connections to
        30 different websites. On a slow network day or from a Hugging Face
        shared container, this could exhaust available socket handles.

        After this fix: At most 10 website visits run at the same time.
        Think of it like 10 checkout lanes at a supermarket — if 30 people
        arrive, 10 go through immediately and 20 wait in line. Nobody gets
        turned away, and the store doesn't collapse.

        The total added time is still bounded by the 4-second timeout inside
        extract_top_image, not by the semaphore.

        Args:
            articles (List[Article]): Articles from _map_items_to_articles().

        Returns:
            List[Article]: Same articles, with image_url filled in where possible.
        """
        if not articles:
            return articles

        # Max 10 website visits at the same time.
        # The semaphore is created fresh per call so it doesn't leak state
        # between separate fetch_news() invocations.
        sem = asyncio.Semaphore(10)

        async def _get_image(article: Article) -> str:
            if article.image_url and article.image_url.startswith("http"):
                return article.image_url      # Already has an image — skip
            # Acquire one of 10 available slots before hitting the network.
            async with sem:
                return await extract_top_image(article.url)

        image_tasks = [_get_image(a) for a in articles]
        fetched_images = await asyncio.gather(*image_tasks, return_exceptions=True)

        # Apply the fetched images back to the articles.
        enriched: List[Article] = []
        for article, image_result in zip(articles, fetched_images):
            if isinstance(image_result, str) and image_result:
                # Pydantic v2: model_copy() changes one field without mutating.
                article = article.model_copy(update={"image_url": image_result})
            enriched.append(article)

        return enriched
