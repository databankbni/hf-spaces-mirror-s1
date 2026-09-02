"""
Background Scheduler Service - Phase 3
Automates news fetching and database cleanup using APScheduler
"""
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta
import logging
import pytz

from app.services.news_aggregator import NewsAggregator
from app.services.appwrite_db import get_appwrite_db, _safe_get
from app.services.cache_service import CacheService
from app.services.upstash_cache import get_upstash_cache   # Needed to bust stale news_v3 keys
from app.services.adaptive_scheduler import get_adaptive_scheduler, AdaptiveScheduler
from app.services.research_aggregator import ResearchAggregator
from app.config import settings
# Phase 13: Global image enrichment — fills missing og:image across ALL providers
from app.services.utils.image_enricher import extract_top_image

# Phase 23: Upgraded to the custom ANSI-aligned logger.
# get_logger() wraps the standard logging.getLogger() with our AlignedColorFormatter.
# The output format is: timestamp | LEVEL | module-name | message
# This makes async logs from 22 concurrent categories scannable by human eyes.
from app.utils.custom_logger import get_logger, TAG_START, TAG_GATE, TAG_ENRICH, TAG_DB, TAG_ERROR
logger = get_logger(__name__)

# Initialize scheduler
scheduler = AsyncIOScheduler()

# Import the single source of truth for categories.
# The full list now lives in app/config.py — edit it there, not here.
from app.config import CATEGORIES

# ── I2: SLOT SCHEDULER OFFSETS (Staggered Queue Pushes) ──────────────────────
# Each category is assigned a fixed offset within a 90-minute ingestion window.
# When fetch_single_category_job() fires for a given category, it sleeps for
# this offset before pushing to the Redis queue. This staggers queue entries
# across 5400 seconds so the worker never receives all 22 categories at once.
# Adaptive intervals are FULLY PRESERVED — only the intra-cycle timing changes.
#
# Slot math: 5400s / 22 categories ≈ 245 seconds per slot.
#   Category 0 → T+0s    (fires immediately)
#   Category 1 → T+245s  (waits ~4 min)
#   Category 2 → T+490s  (waits ~8 min)
#   ... and so on across the 90-minute window.
SLOT_DURATION_SECS: float = 5400.0 / len(CATEGORIES)  # 5400s = 90-min window
CATEGORY_SLOT_OFFSETS: dict = {
    cat: idx * SLOT_DURATION_SECS
    for idx, cat in enumerate(CATEGORIES)
}

# --------------------------------------------------------------------------
# MODULE-LEVEL SINGLETONS (Phase 6)
# --------------------------------------------------------------------------
# These two objects are created ONCE when the server starts and are shared
# by all 22 per-category jobs for the entire lifetime of the process.
#
# _shared_aggregator  — one NewsAggregator for all categories (Phase 1 fix).
#   It holds provider state (quota counts, circuit-breaker) that must
#   survive across job runs. Creating a new one for every job would reset
#   all that carefully maintained state.
#
# _adaptive  — the AdaptiveScheduler that tracks how many articles each
#   category produces and adjusts its fetch interval accordingly.
#   Also persists to disk (data/velocity_tracking.json) so intervals
#   survive server restarts.
# --------------------------------------------------------------------------
_shared_aggregator = None
_adaptive          = None


def _get_shared_aggregator():
    """Return (creating if needed) the one shared NewsAggregator instance."""
    global _shared_aggregator
    if _shared_aggregator is None:
        _shared_aggregator = NewsAggregator()
        logger.info("[AGGREGATOR] Shared NewsAggregator created (singleton).")
    return _shared_aggregator


def _get_adaptive():
    """Return (creating if needed) the one shared AdaptiveScheduler instance."""
    global _adaptive
    if _adaptive is None:
        _adaptive = get_adaptive_scheduler(CATEGORIES)
        logger.info("[ADAPTIVE] AdaptiveScheduler created for %d categories.", len(CATEGORIES))
    return _adaptive


async def fetch_all_news():
    """
    Background Job: Bulk enqueue all categories to the worker queue.

    This job is the PRODUCER. It does NOT fetch news directly — it pushes all
    22 category names into the Redis queue. The worker consumer then processes
    them one by one with proper pacing.

    BUG-003 fixed: removed zero-initialized tracking variables (total_fetched,
    total_saved, etc.) and the ingestion_metrics.record_run() call that was
    reporting 0-0-0 to monitoring on every single run. Metrics are now the
    worker's responsibility (it is the one doing the actual work).
    """
    start_time = datetime.now()

    logger.info("═" * 80)
    logger.info("💰 [NEWS FETCHER] Starting bulk category enqueue...")
    logger.info("🕐 Start Time: %s", start_time.strftime('%Y-%m-%d %H:%M:%S'))
    logger.info("═" * 80)

    # Ensure shared aggregator singleton exists (circuit breaker, quota state).
    _get_shared_aggregator()

    # Producer Pattern: push categories to Redis. Worker consumes one by one.
    upstash = get_upstash_cache()

    # Guard: check queue depth to prevent flooding
    queue_len = await upstash.llen("segmento:pending_news_queue")
    if queue_len > 50:
        logger.warning("🚨 [PRODUCER] Queue is flooded (%d items). Skipping bulk enqueue.", queue_len)
        return

    logger.info("⚡ Enqueueing %d categories to 'segmento:pending_news_queue'...", len(CATEGORIES))

    for category in CATEGORIES:
        await upstash.lpush("segmento:pending_news_queue", category)

    duration = (datetime.now() - start_time).total_seconds()
    logger.info("═" * 80)
    logger.info("✅ [NEWS FETCHER] Bulk enqueue completed in %.2fs.", duration)
    logger.info("   %d categories queued. Worker will process them with 8-18s pacing.", len(CATEGORIES))
    logger.info("═" * 80)


async def fetch_single_category_job(category: str):
    """
    Per-category background job (Phase 6).

    This is what each of the 22 adaptive jobs calls every N minutes.
    It is a self-contained unit: fetch → validate → save → report → reschedule.

    In plain English:
      Think of this like a delivery driver who has a single route (one category).
      After every delivery run, the dispatcher (adaptive scheduler) checks how
      many packages were delivered. If the route is always busy (lots of news),
      the driver gets sent out more often. If the route is quiet, the driver
      waits longer before going out again.
    """
    # ── I2: SLOT OFFSET (Staggered Queue Push) ───────────────────────────────
    # Each category sleeps for its pre-assigned slot offset before pushing to
    # the Redis queue. This spreads 22 concurrent job firings across 90 minutes
    # so the worker receives categories one-by-one instead of all at once.
    # Adaptive intervals are untouched — only intra-cycle timing is staggered.
    offset = CATEGORY_SLOT_OFFSETS.get(category, 0)
    if offset > 0:
        logger.debug("[SLOT] %s: waiting %.0fs before queue push (slot stagger)", category.upper(), offset)
        await asyncio.sleep(offset)
    # ─────────────────────────────────────────────────────────────────────────

    try:
        upstash = get_upstash_cache()
        
        # Guard: Check queue depth to prevent flooding (The 50-Item Threshold)
        queue_len = await upstash.llen("segmento:pending_news_queue")
        if queue_len > 50:
            logger.warning("🚨 [PRODUCER] Queue is flooded (%d items). Skipping push for %s.", queue_len, category)
            return

        await upstash.lpush("segmento:pending_news_queue", category)
        logger.info("[PRODUCER] Queued category [%s] for worker.", category.upper())
        
    except Exception as e:
        logger.error("[PRODUCER] Failed to enqueue %s: %s", category, e)

async def update_adaptive_intervals_from_redis():
    """
    Background Job: Sync internal triggers with Redis-stored velocity data.

    Why?
    The Worker process calculates new intervals and saves them to Redis.
    The Scheduler process (this one) needs to read those values and update
    its IntervalTriggers so the next "Push to Queue" happens at the right time.

    WARN-001: The rescheduling logic body is currently a no-op (pass).
    The job fires every 5 minutes and reads Redis velocity data but does NOT
    yet call scheduler.reschedule_job() to update the actual APScheduler
    IntervalTriggers. Adaptive intervals are therefore fixed at their boot-time
    values. TODO: implement trigger rescheduling here in the next sprint.
    """
    adaptive = _get_adaptive()
    if not adaptive:
        return

    logger.debug("🔄 [SYNC] Reading adaptive intervals from Redis (rescheduling not yet implemented)...")

    # Load fresh data from Redis
    new_data = await asyncio.to_thread(adaptive._load_velocity_data)
    if not new_data:
        return

    adaptive.velocity_data = new_data

    # TODO (WARN-001): Call scheduler.reschedule_job(job_id, trigger=IntervalTrigger(minutes=new_interval))
    # for each category when its velocity-based interval differs from the current trigger.
    # Until this is implemented, all 22 category jobs run at their boot-time intervals.


async def keepalive_job():
    """
    Background Job: Ping Appwrite every 23 hours to prevent free-tier sleep.

    Appwrite's free tier suspends projects after 7 days of inactivity.
    This job issues a single read-only list_rows(limit=1) call to keep the
    project awake. It NEVER writes, modifies, or deletes any data.

    [I1 — Appwrite Keepalive]
    """
    try:
        from appwrite.query import Query
        db = get_appwrite_db()
        if not db.initialized:
            logger.warning("[KEEPALIVE] Appwrite not initialized — skipping ping.")
            return
        await db.list_rows(
            table_id=settings.APPWRITE_COLLECTION_ID,
            queries=[Query.limit(1)]
        )
        logger.info("[KEEPALIVE] Appwrite ping successful — project is alive.")
    except Exception as e:
        logger.warning("[KEEPALIVE] Appwrite ping failed: %s", e)


async def fetch_daily_research():
    """
    Background Job: Fetch Research Papers from ArXiv
    Runs daily at 02:00 IST
    """
    logger.info("═" * 80)
    logger.info("🔬 [RESEARCH FETCHER] Starting daily research fetch...")
    logger.info("🕐 Start Time: %s", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    logger.info("═" * 80)
    
    try:
        aggregator = ResearchAggregator()
        saved_count = await aggregator.fetch_and_process_daily_papers()
        logger.info(f"✅ [RESEARCH FETCHER] Completed. Saved {saved_count} new papers.")
        
    except Exception as e:
        logger.error(f"❌ [RESEARCH FETCHER] Failed: {e}", exc_info=True)
    
    logger.info("═" * 80)


async def fetch_top_repos_job():
    """
    Background Job: Fetch Top Git Repositories
    Runs daily at 03:00 IST
    """
    logger.info("═" * 80)
    logger.info("🚀 [TOP REPOS FETCHER] Starting daily top repos fetch...")
    logger.info("🕐 Start Time: %s", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    logger.info("═" * 80)
    
    try:
        from app.services.github_repos_aggregator import GithubReposAggregator
        aggregator = GithubReposAggregator()
        await aggregator.run()
        logger.info("✅ [TOP REPOS FETCHER] Completed successfully.")
    except Exception as e:
        logger.error(f"❌ [TOP REPOS FETCHER] Failed: {e}", exc_info=True)
    
    logger.info("═" * 80)


# ──────────────────────────────────────────────────────────────────────────────
# PHASE 13: GLOBAL IMAGE ENRICHMENT SAFETY NET
# ──────────────────────────────────────────────────────────────────────────────
#
# What this does:
#   After all validation and deduplication gates have passed, some articles
#   still arrive with an empty or missing image_url. This happens most often
#   with providers like OpenRSS (blog feeds without media tags), Webz.io
#   (small sites without a thread.main_image), and SauravKanchan (NewsAPI
#   null urlToImage). This function visits the article's URL and tries to
#   extract the og:image meta tag — the standard way websites declare their
#   main thumbnail image.
#
# Why AFTER deduplication?
#   We only enrich articles that actually passed every gate and are about to
#   be saved. We never spend HTTP calls on articles that will be thrown away.
#
# Safety guards:
#   1. MAX_ENRICH_PER_RUN = 20  — Hard cap. If 50 no-image articles arrive,
#      we only enrich the first 20, leave the rest as "", and the Pulse banner
#      shows on the frontend. This stops a rogue provider from bottlenecking
#      the cron job.
#   2. asyncio.Semaphore(10)    — At most 10 web-page fetches happen at the
#      same time. This prevents memory spikes and avoids hammering websites.
#   3. Individual 4-second timeout (inside extract_top_image) — A broken URL
#      is cancelled in 4 seconds. With Semaphore(10) and MAX 20 articles:
#      worst-case total overhead = (20 / 10) × 4 = 8 seconds per category run.
#   4. Zero side-effects — A failed enrichment returns the article unchanged.
#      The enricher NEVER removes an article from the pipeline.
#
async def enrich_missing_images_in_batch(articles: list, delay_seconds: float = 0.0) -> list:
    """
    Scan a list of fully-vetted articles and fill in any missing images.

    Only enriches up to MAX_ENRICH_PER_RUN articles that have no valid
    image_url. Articles that already have an image are passed through
    instantly with zero network cost.

    Args:
        articles (list): Final, deduplicated, validated Article objects.
        delay_seconds (float): Optional delay between concurrent requests to avoid IP bans.

    Returns:
        list: Same articles, with image_url filled where possible.
              Never raises. Never removes an article.
    """
    if not articles:
        return articles

    # ── Constants ─────────────────────────────────────────────────────────────
    # Cap: only attempt image enrichment on the first 20 articles that need it.
    # The rest go to the database as-is (empty image = Pulse banner fallback).
    MAX_ENRICH_PER_RUN = 20

    # Semaphore: at most 10 website fetches run simultaneously.
    # Think of it like a queue of 10 checkout lanes at a supermarket.
    # If 20 people arrive at once, 10 go straight through and 10 wait
    # in line. Nobody gets turned away, but the store doesn't explode.
    sem = asyncio.Semaphore(10)

    # ── Count how many articles actually need enrichment ───────────────────────
    articles_needing_images = [
        a for a in articles
        if not a.image_url or not a.image_url.startswith("http")
    ]
    enrich_count = min(len(articles_needing_images), MAX_ENRICH_PER_RUN)

    if enrich_count == 0:
        # Every article already has a valid image. Nothing to do.
        return articles

    logger.info(
        "🖼️  [IMAGE ENRICHER] %d article(s) missing images — enriching up to %d...",
        len(articles_needing_images), enrich_count
    )

    # Build a lookup set of URLs to enrich (only the capped subset).
    urls_to_enrich = {
        str(a.url) for a in articles_needing_images[:MAX_ENRICH_PER_RUN]
    }

    # ── Internal worker: enrich one article ───────────────────────────────────
    async def _enrich_one(article) -> object:
        """
        If this article needs an image, fetch it under the semaphore guard.
        Returns the article (updated or unchanged).
        """
        url_str = str(article.url) if article.url else ""

        # Article already has a valid image, or it's outside the cap — skip.
        if url_str not in urls_to_enrich:
            return article

        async with sem:
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
            # Semaphore acquired: one of our 10 lanes is now occupied.
            # extract_top_image has its own 4-second internal timeout,
            # so this will release the lane quickly regardless of outcome.
            image_url = await extract_top_image(url_str)

        if image_url and image_url.startswith("http"):
            # Got a valid image — update the article cleanly.
            # model_copy() is the correct Pydantic v2 pattern for immutable models.
            return article.model_copy(update={"image_url": image_url})

        # No image found or fetch failed — return article unchanged.
        return article

    # ── Run all workers concurrently ───────────────────────────────────────────
    # All articles go into gather() at once. The semaphore controls how many
    # actually hit the network at the same time (max 10). The rest wait
    # in asyncio's queue without blocking the event loop.
    try:
        enriched_articles = await asyncio.gather(
            *[_enrich_one(a) for a in articles],
            return_exceptions=True
        )

        # Replace any Exception results with the original article (safe fallback).
        final = []
        for original, result in zip(articles, enriched_articles):
            if isinstance(result, Exception):
                logger.debug(
                    "[IMAGE ENRICHER] Worker exception for %s: %s",
                    str(original.url)[:60], result
                )
                final.append(original)           # Keep original if worker crashed
            else:
                final.append(result)

        enriched_total = sum(
            1 for a in final if a.image_url and a.image_url.startswith("http")
        )
        logger.info(
            "✅ [IMAGE ENRICHER] Done — %d/%d articles now have images.",
            enriched_total, len(final)
        )
        return final

    except Exception as e:
        # If the entire gather somehow fails, return the original list untouched.
        logger.error("[IMAGE ENRICHER] Gather failed: %s — returning articles unchanged.", e)
        return articles


async def fetch_and_validate_category(category: str, aggregator) -> tuple:
    """
    Fetch and validate articles for a single category.

    Args:
        category:   The news category (e.g. 'ai', 'cloud-aws').
        aggregator: The shared NewsAggregator instance for this run.
                    Using a shared instance means all 22 parallel tasks
                    share the same quota counters and circuit-breaker state.

    Returns: (category, valid_articles, invalid_count, irrelevant_count, relevant_count)
    """
    from app.utils.data_validation import is_valid_article, sanitize_article, is_relevant_to_category
    from app.utils.date_parser import normalize_article_date
    from app.utils.url_canonicalization import canonicalize_url
    from app.utils.redis_dedup import is_url_seen_or_mark
    from app.models import Article   # Needed to reconstruct Pydantic model after date normalization
    
    try:
        logger.info("%s Fetching category [%s]...", TAG_START, category.upper())
        
        # Ask the aggregator for all articles from all sources for this category.
        # fetch_by_category (Phase 5) internally runs:
        #   1. Paid waterfall  — GNews → NewsAPI → NewsData (stops on first success)
        #   2. Free parallel   — Google RSS + Medium + Official Cloud, all at once
        #   3. Returns the merged list
        # We no longer need to call fetch_from_provider for medium/official_cloud
        # separately here. That would duplicate the work Phase 5 already does.
        raw_articles = await aggregator.fetch_by_category(category)
        
        if not raw_articles:
            return (category, [], 0, 0, 0)

        # ------------------------------------------------------------------
        # IN-BATCH DEDUPLICATION
        # ------------------------------------------------------------------
        # When 3 providers run at the same time for the same category, they
        # sometimes return the exact same article (e.g. a TechCrunch AI story
        # can come from both GNews AND Google RSS in the same fetch cycle).
        # We catch and remove these same-batch duplicates RIGHT HERE, before
        # the expensive validation loop even starts.
        # This is like a quick ID-card check at the entrance before people
        # join the full security screening queue.
        _seen_in_batch: set = set()
        _deduplicated_raw = []
        for _art in raw_articles:
            _raw_url = str(_art.url) if _art.url else ''
            _canonical = canonicalize_url(_raw_url) if _raw_url else ''
            # If we have a valid canonical URL and we've already seen it → skip
            if _canonical and _canonical in _seen_in_batch:
                continue
            if _canonical:
                _seen_in_batch.add(_canonical)
            _deduplicated_raw.append(_art)

        _batch_dupes_removed = len(raw_articles) - len(_deduplicated_raw)
        if _batch_dupes_removed > 0:
            logger.info(
                "   🔄 [BATCH DEDUP] %s: Removed %d within-batch duplicates before validation",
                category.upper(), _batch_dupes_removed
            )
        raw_articles = _deduplicated_raw
        # ------------------------------------------------------------------
        
        # Validate, filter, and sanitize
        valid_articles = []
        invalid_count = 0
        irrelevant_count = 0
        relevant_count = 0   # articles that are valid + relevant, before Redis dedup
        
        for article in raw_articles:
            # Step 1: Basic validation — must have a title, URL, and publication date.
            if not is_valid_article(article):
                invalid_count += 1
                continue

            # Step 2: Category relevance check — title+description must match category keywords.
            if not is_relevant_to_category(article, category):
                irrelevant_count += 1
                continue

            # Checkpoint: count articles that are valid AND relevant, but before
            # the Redis 48-hour check strips out the ones we have already stored.
            # This is the true "how much real news is in this category?" signal.
            # The adaptive scheduler uses this number to decide fetch frequency.
            # (Fix #2 - Phase 7: was using saved_count, which confused "quiet feed"
            # with "feed we already have fully stored" — two very different things.)
            relevant_count += 1

            # Step 3: Redis 48-hour dedup check — THE MAIN BOUNCER.
            # Check if we have already stored this exact article URL in the last 48 hours.
            # If yes, skip silently — it's a repeat. If no, mark it as seen and continue.
            # This stops the same article being saved every hour from a slow-updating RSS feed.
            if await is_url_seen_or_mark(str(article.url) if article.url else ''):
                logger.debug(
                    "   [REDIS DEDUP] Skipped article already seen in last 48 hours: %s",
                    str(article.url)[:80]
                )
                continue

            # Step 4: Normalize date to UTC ISO-8601.
            # IMPORTANT: normalize_article_date() always returns a plain dict
            # (it calls model_dump() internally). We reconstruct the Pydantic
            # Article right after so that enrich_missing_images_in_batch()
            # (Phase 13, below) gets the .image_url attribute it needs.
            normalized_dict = normalize_article_date(article)
            try:
                article = Article(**normalized_dict)
            except Exception:
                # If reconstruction fails for any reason, skip this article.
                # The dict is malformed — better to drop it than crash.
                invalid_count += 1
                continue

            # Step 5: Article is now a clean Pydantic object with a normalized date.
            # We intentionally do NOT call sanitize_article() yet — that step
            # runs AFTER image enrichment below.
            valid_articles.append(article)

        # ── PHASE 13: GLOBAL IMAGE ENRICHMENT ─────────────────────────────────
        # This is the bottom of the funnel. Every article here has already:
        #   ✓ Passed basic validation (title, URL, date exist)
        #   ✓ Passed category relevance check
        #   ✓ Passed Redis 48-hour deduplication (it is a NEW article)
        #   ✓ Been date-normalized
        # Articles are still Pydantic objects here — enrichment needs .image_url.
        if valid_articles:
            valid_articles = await enrich_missing_images_in_batch(valid_articles)

        # ── SANITIZE (after enrichment) ────────────────────────────────────────
        # Now that images are filled, convert each Pydantic Article to a clean
        # dict for Appwrite storage. sanitize_article() strips unsafe chars,
        # trims lengths, and returns the final dict payload.
        valid_articles = [sanitize_article(a) for a in valid_articles]
        # ──────────────────────────────────────────────────────────────────────

        logger.info("%s [%s] Valid: %d | Invalid: %d | Irrelevant: %d | Time: see APScheduler",
                    TAG_GATE, category.upper(), len(valid_articles), invalid_count, irrelevant_count)
        return (category, valid_articles, invalid_count, irrelevant_count, relevant_count)
        
    except asyncio.TimeoutError:
        logger.error("%s Timeout fetching [%s] (>30s)", TAG_ERROR, category)
        return (category, [], 0, 0, 0)
    except Exception as e:
        logger.exception("%s Error fetching [%s]", TAG_ERROR, category)
        return (category, [], 0, 0, 0)


async def cleanup_old_news():
    """
    Background Job: Delete articles older than 48 hours from ALL collections
    
    Runs every 30 minutes to keep Appwrite database within free tier limits.
    Only keeps the last 2 days of articles.
    """
    logger.info("")
    logger.info("═" * 80)
    logger.info("🧹 [CLEANUP JANITOR] Starting cleanup of old articles...")
    logger.info("🕐 Cleanup Time: %s", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    logger.info("═" * 80)
    
    appwrite_db = get_appwrite_db()
    
    if not appwrite_db.initialized:
        logger.error("❌ CRITICAL: Appwrite database not initialized!")
        return
    
    try:
        # Calculate cutoff date (48 hours ago)
        retention_hours = 48
        cutoff_date = datetime.now() - timedelta(hours=retention_hours)
        cutoff_iso = cutoff_date.isoformat()
        
        logger.info("📋 Retention Policy: %d hours", retention_hours)
        logger.info("📅 Cutoff Date: %s", cutoff_date.strftime('%Y-%m-%d %H:%M:%S'))
        
        # Define all collections to clean
        target_collections = [
            ("Regular News", settings.APPWRITE_COLLECTION_ID),
            ("Cloud News", settings.APPWRITE_CLOUD_COLLECTION_ID),
            ("AI News", settings.APPWRITE_AI_COLLECTION_ID),
            ("Data News", settings.APPWRITE_DATA_COLLECTION_ID),
            ("Magazines", settings.APPWRITE_MAGAZINE_COLLECTION_ID),
            ("Medium Blogs", settings.APPWRITE_MEDIUM_COLLECTION_ID)
        ]
        
        total_deleted = 0
        from appwrite.query import Query
        
        for name, collection_id in target_collections:
            if not collection_id:
                logger.debug(f"⏭️  Skipping {name} (Not configured)")
                continue
                
            logger.info("")
            logger.info(f"📂 [{name}] Cleaning collection: {collection_id}...")
            
            try:
                # -------------------------------------------------------------
                # 1. SMART CHECK: "Hey collection, do you have old data?"
                # -------------------------------------------------------------
                check_response = await appwrite_db.list_rows(
                    table_id=collection_id,
                    queries=[
                        Query.less_than('published_at', cutoff_iso),
                        Query.limit(1)  # Minimal query to check existence
                    ]
                )
                
                if len(_safe_get(check_response, 'rows', [])) == 0:
                    logger.info(f"✨ [{name}] Collection is clean (Smart Check Passed)")
                    continue
                    
                logger.info(f"🔍 [{name}] Found legacy data. Initiating cleanup sequence...")
                
                # -------------------------------------------------------------
                # 2. DEEP CLEAN: Delete full rows (attributes, engagement, etc.)
                # -------------------------------------------------------------
                total_collection_deleted = 0
                
                while True:
                    # Query old articles (Batch of 500)
                    response = await appwrite_db.list_rows(
                        table_id=collection_id,
                        queries=[
                            Query.less_than('published_at', cutoff_iso),
                            Query.limit(500)
                        ]
                    )
                    
                    batch_count = len(_safe_get(response, 'rows', []))
                    
                    if batch_count == 0:
                        logger.info(f"✅ [{name}] Cleanup complete. Total rows deleted: {total_collection_deleted}")
                        break
                        
                    logger.info(f"   [{name}] processing batch of {batch_count} rows...")
                    
                    batch_deleted = 0
                    for doc in _safe_get(response, 'rows', []):
                        try:
                            # This deletes the FULL DOCUMENT (Row) including all attributes
                            # (published_at, url, image, likes, views, dislikes, etc.)
                            await appwrite_db.delete_row(
                                table_id=collection_id,
                                row_id=_safe_get(doc, '$id')
                            )
                            batch_deleted += 1
                        except Exception as e:
                            logger.error(f"❌ Error deleting row {_safe_get(doc, '$id')}: {e}")
                            
                    total_collection_deleted += batch_deleted
                    total_deleted += batch_deleted
                    
                    # Safety break (User Request: 5,000 limit)
                    if total_collection_deleted >= 5000:
                         logger.warning(f"⚠️  [{name}] Hit safety limit (5,000). Pausing cleanup for next run.")
                         break

            except Exception as e:
                logger.warning(f"⚠️  Error accessing {name} collection: {e}")
        
        # =========================================================================
        # Clear Redis Cache
        # =========================================================================
        logger.info("")
        logger.info("🔄 Clearing Redis cache...")
        cache_service = CacheService()
        cache_cleared = 0
        for category in CATEGORIES:
            try:
                await cache_service.delete(f"news:{category}")
                cache_cleared += 1
            except Exception as e:
                logger.debug("⚠️  Cache clear skipped for %s: %s", category, e)
        
        if cache_cleared > 0:
            logger.info("✅ Cache cleared for %d categories", cache_cleared)
        
        # =========================================================================
        # Final Summary
        # =========================================================================
        logger.info("")
        logger.info("═" * 80)
        logger.info("🎉 [CLEANUP JANITOR] COMPLETED!")
        logger.info("🗑️  Total Deleted: %d articles across all collections", total_deleted)
        logger.info("⏰ Retention: Articles older than %d hours removed", retention_hours)
        logger.info("═" * 80)
        
    except Exception as e:
        logger.error("")
        logger.error("═" * 80)
        logger.error("❌ [CLEANUP JANITOR] FAILED!")
        logger.error("Error: %s", str(e))
        logger.error("═" * 80)
        logger.exception("Full traceback:")


async def background_image_enricher_job():
    """
    Background Job: Fetch articles across collections missing images and enrich them.
    Runs every 1 hour. Applies delays to avoid IP bans.
    """
    logger.info("")
    logger.info("═" * 80)
    logger.info("🖼️  [BACKGROUND ENRICHER] Starting missing image scan...")
    logger.info("═" * 80)
    
    appwrite_db = get_appwrite_db()
    if not appwrite_db.initialized:
        return
        
    try:
        from appwrite.query import Query
        from app.models import Article
        
        target_collections = [
            ("Regular News", settings.APPWRITE_COLLECTION_ID),
            ("Cloud News", settings.APPWRITE_CLOUD_COLLECTION_ID),
            ("AI News", settings.APPWRITE_AI_COLLECTION_ID),
            ("Data News", settings.APPWRITE_DATA_COLLECTION_ID),
        ]
        
        total_enriched = 0
        
        for name, collection_id in target_collections:
            if not collection_id:
                continue
                
            # Fetch 50 recent articles and locally filter for empty images
            response = await appwrite_db.list_rows(
                table_id=collection_id,
                queries=[
                    Query.order_desc('published_at'),
                    Query.limit(50)
                ]
            )
            
            docs = _safe_get(response, 'rows', [])
            # Pick max 10 to avoid scraping too intensely in background
            empty_docs = [d for d in docs if not _safe_get(d, 'image_url') and not _safe_get(d, 'image')][:10]
            
            if not empty_docs:
                continue
                
            logger.info(f"   [{name}] Found {len(empty_docs)} recent articles missing images. Enriching...")
            
            articles_to_enrich = []
            for doc in empty_docs:
                try:
                    # Robust doc attributes extraction
                    doc_copy = dict(doc) if isinstance(doc, dict) else {k: getattr(doc, k) for k in dir(doc) if not k.startswith('_')}

                    # Ensure ID mapping fits Article model
                    doc_id = _safe_get(doc, '$id')
                    if doc_id:
                        doc_copy['id'] = doc_id

                    art = Article(**doc_copy)
                    articles_to_enrich.append(art)
                except Exception as e:
                    # WARN-006 fixed: was a silent `pass`. Now logs at debug level so
                    # failed Article() construction is visible without flooding INFO logs.
                    logger.debug(
                        "[ENRICHER] Could not parse doc '%s' into Article: %s",
                        _safe_get(doc, '$id', 'unknown'), e
                    )
                    
            if not articles_to_enrich:
                continue
                
            # Add 2.0s delay between concurrent requests to be polite to news servers
            enriched = await enrich_missing_images_in_batch(articles_to_enrich, delay_seconds=2.0)
            
            for original, new_art in zip(articles_to_enrich, enriched):
                if new_art.image_url and new_art.image_url.startswith("http"):
                    try:
                        await appwrite_db.update_row(
                            table_id=collection_id,
                            row_id=new_art.id,
                            data={'image_url': new_art.image_url, 'image': new_art.image_url}
                        )
                        total_enriched += 1
                    except Exception as e:
                        logger.error(f"Error saving enriched image for {new_art.id}: {e}")
                        
        logger.info(f"✅ [BACKGROUND ENRICHER] Done. {total_enriched} missing images successfully scraped and saved.")
        
    except Exception as e:
        logger.error(f"❌ [BACKGROUND ENRICHER] Failed: {e}", exc_info=True)


def start_scheduler():
    """
    Initialize and start the background scheduler with all jobs
    """
    logger.info("")
    logger.info("═" * 80)
    logger.info("⏰ [SCHEDULER] Initializing background scheduler...")
    logger.info("═" * 80)
    
    # ── Job #1: PER-CATEGORY ADAPTIVE NEWS FETCHERS (Phase 6) ───────────
    # Instead of one giant job that fetches all 22 categories every hour,
    # we register 22 individual jobs, each on its own timer.
    #
    # The timer for each category is read from the adaptive scheduler,
    # which remembers how "active" each category was in past runs:
    #   - 'ai' category gets lots of articles → runs every 5 minutes
    #   - 'cloud-alibaba' is quiet → runs every 60 minutes
    #   - Most categories start at 15 minutes (the default)
    #
    # After every run, the job updates its own timer if the velocity changed.
    # No server restart needed.
    # -------------------------------------------------------------------------
    adaptive = _get_adaptive()   # initializes singleton + loads saved intervals

    for idx, category in enumerate(CATEGORIES, start=1):
        initial_interval = adaptive.get_interval(category)  # minutes
        job_id = f"fetch_{category}"

        scheduler.add_job(
            fetch_single_category_job,
            trigger=IntervalTrigger(minutes=initial_interval),
            args=[category],
            id=job_id,
            name=f"News Fetcher: {category} (Producer)",
            replace_existing=True
        )
        logger.info(
            "   ✓ [%02d/%02d] %-30s → every %d min",
            idx, len(CATEGORIES), category, initial_interval
        )

    logger.info("")
    logger.info("✅ Job #1 Group Registered: 📰 %d Adaptive News Producers", len(CATEGORIES))
    logger.info("   Intervals range from 5 min (high-velocity) to 60 min (quiet)")

    # ── I2: Log slot map at startup ───────────────────────────────────────────
    logger.info("")
    logger.info(
        "🗓️  [SLOT MAP] Staggered queue pushes — 90-min window, %d categories, %.0fs/slot:",
        len(CATEGORIES), SLOT_DURATION_SECS
    )
    for _cat, _offset in CATEGORY_SLOT_OFFSETS.items():
        logger.info("   %-35s → T+%.0fs", _cat, _offset)
    logger.info("")
    # ─────────────────────────────────────────────────────────────────────────

    # Sync Job (Frequency: Every 5 minutes)
    # Listens to Redis the Worker process updated and adjusts scheduler triggers.
    scheduler.add_job(
        update_adaptive_intervals_from_redis,
        trigger=IntervalTrigger(minutes=5),
        id='sync_adaptive_intervals',
        name='Interval Synchronizer (every 5 mins)',
        replace_existing=True
    )
    logger.info("")
    logger.info("✅ Job #2 Registered: 🔄 Interval Synchronizer")
    logger.info("   ⏱️  Schedule: Every 5 minutes")
    
    # Cleanup Job (Frequency: Every 30 minutes)
    scheduler.add_job(
        cleanup_old_news,
        trigger=IntervalTrigger(minutes=30),
        id='cleanup_old_news',
        name='Database Janitor (every 30 mins)',
        replace_existing=True
    )
    logger.info("")
    logger.info("✅ Job #2 Registered: 🧹 Database Janitor")
    logger.info("   ⏱️  Schedule: Every 30 minutes")
    logger.info("   📋 Task: Delete articles older than 48 hours")
    
    # Import newsletter service (lazy import)
    from app.services.newsletter_service import send_scheduled_newsletter
    
    # IST timezone for newsletter scheduling
    IST = pytz.timezone('Asia/Kolkata')
    
    # Newsletter Jobs
    newsletter_jobs = [
        ("Morning", 7, 0, 'mon-sat'),
        ("Afternoon", 14, 0, 'mon-fri'),
        ("Evening", 19, 0, None),
        ("Weekly", 9, 0, 'sun')
    ]
    
    job_counter = 3
    for name, hour, minute, days in newsletter_jobs:
        trigger_args = {'hour': hour, 'minute': minute, 'timezone': IST}
        if days:
            trigger_args['day_of_week'] = days
            
        scheduler.add_job(
            send_scheduled_newsletter,
            trigger=CronTrigger(**trigger_args),
            args=[name],
            id=f'newsletter_{name.lower()}',
            name=f'{name} Newsletter',
            replace_existing=True
        )
        logger.info("")
        logger.info(f"✅ Job #{job_counter} Registered: 📧 {name} Newsletter")
        job_counter += 1
        
    # Monthly Newsletter
    scheduler.add_job(
        send_scheduled_newsletter,
        trigger=CronTrigger(hour=9, minute=0, day=1, timezone=IST),
        args=["Monthly"],
        id='newsletter_monthly',
        name='Monthly Newsletter',
        replace_existing=True
    )
    logger.info("")
    logger.info(f"✅ Job #{job_counter} Registered: 📊 Monthly Newsletter")
    
    # Research Papers Job (Daily at 02:00 IST)
    scheduler.add_job(
        fetch_daily_research,
        trigger=CronTrigger(hour=2, minute=0, timezone=IST),
        id='fetch_research_papers',
        name='Research Fetcher (Daily 02:00 IST)',
        replace_existing=True
    )
    logger.info("")
    logger.info(f"✅ Job #{job_counter + 1} Registered: 🔬 Research Fetcher")

    # Top Git Repositories Job (Daily at 03:00 IST)
    scheduler.add_job(
        fetch_top_repos_job,
        trigger=CronTrigger(hour=3, minute=0, timezone=IST),
        id='fetch_top_repos_job',
        name='Top Repos Fetcher (Daily 03:00 IST)',
        replace_existing=True
    )
    logger.info("")
    logger.info(f"✅ Job #{job_counter + 2} Registered: 🚀 Top Repos Fetcher")

    # Background Image Enricher Job (Every 1 hour)
    scheduler.add_job(
        background_image_enricher_job,
        trigger=IntervalTrigger(hours=1),
        id='background_image_enricher',
        name='Image Enricher (every 1 hour)',
        replace_existing=True
    )
    logger.info("")
    logger.info(f"✅ Job #{job_counter + 3} Registered: 🖼️ Background Image Enricher")

    # ── I1: Appwrite Keepalive Job (every 23 hours) ───────────────────────────
    scheduler.add_job(
        keepalive_job,
        trigger=IntervalTrigger(hours=23),
        id='appwrite_keepalive',
        name='Appwrite Keepalive Ping (every 23 hours)',
        replace_existing=True
    )
    logger.info("")
    logger.info(f"✅ Job #{job_counter + 4} Registered: 💓 Appwrite Keepalive")
    logger.info("   ⏱️  Schedule: Every 23 hours")
    logger.info("   📋 Task: Read-only ping to prevent Appwrite free-tier sleep")
    # ─────────────────────────────────────────────────────────────────────────

    # Start the scheduler
    logger.info("")
    logger.info("🚀 Starting scheduler engine...")
    scheduler.start()
    logger.info("")
    logger.info("═" * 80)
    logger.info("✅ [SCHEDULER] Background scheduler started successfully!")
    logger.info("═" * 80)
    logger.info("")


def shutdown_scheduler():
    """
    Gracefully shutdown the scheduler
    """
    logger.info("")
    logger.info("═" * 80)
    logger.info("⏹️  [SCHEDULER] Shutting down background scheduler...")
    scheduler.shutdown(wait=True)
    logger.info("✅ [SCHEDULER] Background scheduler shut down successfully")
    logger.info("═" * 80)
    logger.info("")


# Manual job triggers for testing
async def trigger_fetch_now():
    """Manually trigger news fetch"""
    logger.info("🔧 [MANUAL TRIGGER] Running fetch job NOW...")
    await fetch_all_news()

async def trigger_cleanup_now():
    """Manually trigger cleanup"""
    logger.info("🔧 [MANUAL TRIGGER] Running cleanup job NOW...")
    await cleanup_old_news()

async def trigger_newsletter_now(preference: str):
    """Manually trigger newsletter"""
    from app.services.newsletter_service import send_scheduled_newsletter
    logger.info(f"🔧 [MANUAL TRIGGER] Running {preference} newsletter job NOW...")
    result = await send_scheduled_newsletter(preference)
    return result



