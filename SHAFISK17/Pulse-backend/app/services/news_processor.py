"""
News Processor Service
Handles the heavy lifting of fetching, validating, and saving news articles.
This logic is shared between the legacy scheduler and the new worker manager.
"""
import asyncio
import logging
from datetime import datetime

from app.models import Article
from app.services.news_aggregator import NewsAggregator
from app.services.appwrite_db import get_appwrite_db
from app.services.cache_service import CacheService
from app.services.upstash_cache import get_upstash_cache
from app.services.adaptive_scheduler import get_adaptive_scheduler
from app.services.ingestion_metrics import get_ingestion_metrics
from app.config import settings, CATEGORIES
from app.utils.custom_logger import get_logger, TAG_START, TAG_GATE, TAG_ENRICH, TAG_DB, TAG_ERROR

logger = get_logger(__name__)

async def process_category(category: str, aggregator: NewsAggregator):
    """
    Core logic: Fetch -> Validate -> Save -> Update Adaptive Interval
    """
    from app.services.scheduler import fetch_and_validate_category
    
    adaptive = get_adaptive_scheduler(CATEGORIES)
    
    logger.info("[WORKER] 🚀 Starting processing for: %s", category.upper())
    
    try:
        # Step 1: Fetch + validate
        result = await fetch_and_validate_category(category, aggregator)
        
        if isinstance(result, Exception):
            raise result
            
        cat, articles, invalid_count, irrelevant_count, relevant_count = result
        
        if not articles:
            logger.info("[WORKER] %s: No valid articles this run.", category.upper())
            saved_count = 0
            duplicate_count = 0
            error_count = 0
        else:
            # Step 2: Save to Appwrite
            appwrite_db = get_appwrite_db()
            cache_service = CacheService()
            
            logger.info("[WORKER] %s: Saving %d articles...", category.upper(), len(articles))
            saved_count, duplicate_count, error_count, _ = await appwrite_db.save_articles(articles)
            
            # Step 3: Cache Busting
            if saved_count > 0:
                try:
                    upstash = get_upstash_cache()
                    stale_key = f"news_v3:{category}:page:1:l20"
                    await upstash.delete(stale_key)
                    logger.info("[WORKER] [CACHE BUST] Deleted stale key '%s'", stale_key)
                except Exception as bust_err:
                    logger.debug("[WORKER] [CACHE BUST] Error: %s", bust_err)
            
            # Step 4: Legacy Cache update
            try:
                await cache_service.set(f"news:{category}", articles, ttl=settings.CACHE_TTL)
            except Exception:
                pass

        # Step 4.5: Record Ingestion Metrics
        # NOTE: fetched_approx excludes Redis-dedup volume (not returned by
        # fetch_and_validate_category); rate is directionally correct for before/after comparison, not an absolute count.
        fetched_approx = len(articles) + invalid_count + irrelevant_count
        get_ingestion_metrics().record_run(
            fetched=fetched_approx,
            saved=saved_count,
            duplicates=duplicate_count,
            errors=error_count,
            categories_processed=1,
            irrelevant=irrelevant_count,
        )

        # Step 5: Update adaptive velocity in Redis
        if adaptive:
            adaptive.update_category_velocity(category, relevant_count)
            await adaptive.async_persist()
            logger.info("[WORKER] [ADAPTIVE] Velocity updated for %s", category)

        return True

    except Exception as e:
        logger.error("[WORKER] ❌ Execution failed for %s: %s", category, e)
        raise e
