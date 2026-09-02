"""
Optimized Retrieval Service - UI Performance Enhancement
==========================================================
Implements SWR (Stale-While-Revalidate) and projected field fetching.

Performance Improvements:
- L0: In-memory cache (30s TTL) - instant
- L1: Redis cache (5min TTL) - fast  
- L2: Appwrite (source of truth) - slower
- Projected fields: Only fetch necessary metadata for list views (50-70% smaller payload)
"""

import asyncio
from typing import List, Optional, Dict
from datetime import datetime, timedelta
import logging

from app.services.appwrite_db import get_appwrite_db, _safe_get
from app.services.cache_service import CacheService
from app.config import settings

logger = logging.getLogger(__name__)

# In-memory cache for ultra-fast reads (L0)
_memory_cache: Dict[str, tuple[List[Dict], datetime]] = {}
MEMORY_CACHE_TTL = 30  # 30 seconds

class OptimizedRetrieval:
    """
    Optimized article retrieval with multi-tier caching and field projection.
    """
    
    def __init__(self):
        self.appwrite_db = get_appwrite_db()
        self.cache = CacheService()
        
    async def get_articles_for_list_view(
        self,
        category: str,
        limit: int = 20,
        offset: int = 0,
        force_refresh: bool = False
    ) -> List[Dict]:
        """
        Get articles optimized for list view (projected fields only).
        
        Returns ONLY: title, url, image, published_at, category, likes, views, source, $id
        Skips heavy 'description' and 'content' fields.
        
        This reduces payload size by ~60-70%.
        """
        cache_key = f"list:{category}:{limit}:{offset}"
        
        # L0: Memory cache check
        if not force_refresh and cache_key in _memory_cache:
            cached_data, cached_time = _memory_cache[cache_key]
            age = (datetime.now() - cached_time).total_seconds()
            
            if age < MEMORY_CACHE_TTL:
                logger.debug(f"💨 [L0 HIT] {cache_key} (age: {age:.1f}s)")
                
                # Stale-While-Revalidate: Return stale, refresh in background
                if age > MEMORY_CACHE_TTL * 0.7:  # 70% of TTL
                    asyncio.create_task(self._refresh_cache_background(category, limit, offset))
                
                return cached_data
        
        # L1: Redis cache check
        try:
            cached = await self.cache.get(cache_key)
            if cached and not force_refresh:
                logger.debug(f"⚡ [L1 HIT] {cache_key}")
                _memory_cache[cache_key] = (cached, datetime.now())
                return cached
        except Exception as e:
            logger.debug(f"L1 cache miss: {e}")
        
        # L2: Fetch from Appwrite with projected fields
        logger.debug(f"💾 [L2 FETCH] {cache_key}")
        articles = await self._fetch_projected_articles(category, limit, offset)
        
        # Update all cache layers
        _memory_cache[cache_key] = (articles, datetime.now())
        
        # Only cache in Redis if we actually got results (prevent poisoning with empty lists on error)
        if articles:
            try:
                await self.cache.set(cache_key, articles, ttl=300)  # 5 min Redis TTL
            except Exception as e:
                logger.debug(f"L1 cache write failed: {e}")
        
        return articles
    
    async def _fetch_projected_articles(
        self,
        category: str,
        limit: int,
        offset: int
    ) -> List[Dict]:
        """
        Fetch articles from Appwrite with ONLY the fields needed for list view.
        """
        from appwrite.query import Query
        from app.utils.cursor_pagination import CursorPagination
        
        collection_id = self._get_collection_for_category(category)
        
        try:
            response = await self.appwrite_db.tablesDB.list_rows(
                database_id=settings.APPWRITE_DATABASE_ID,
                collection_id=collection_id,
                queries=[
                    Query.equal('category', category),
                    Query.order_desc('published_at'),
                    Query.limit(limit),
                    Query.offset(offset),
                ]
            )
            
            # Manual projection to reduce payload size
            projected = []
            for doc in _safe_get(response, 'documents', []):
                projected.append({
                    '$id': _safe_get(doc, '$id'),
                    'title': _safe_get(doc, 'title', ''),
                    'url': _safe_get(doc, 'url', ''),
                    'image': _safe_get(doc, 'image', _safe_get(doc, 'image_url', '')),
                    'published_at': _safe_get(doc, 'published_at', ''),
                    'category': _safe_get(doc, 'category', category),
                    'likes': _safe_get(doc, 'likes', 0),
                    'views': _safe_get(doc, 'views', 0),
                    'source': _safe_get(doc, 'source', ''),
                    # Exclude: description (heavy), content (very heavy), tags
                })
            
            logger.info(f"📊 Projected {len(projected)} articles for {category}")
            return projected
            
        except Exception as e:
            logger.error(f"❌ Error fetching projected articles: {e}")
            return []
    
    async def get_article_full_details(self, article_id: str) -> Optional[Dict]:
        """
        Get full article details for article view page.
        Includes ALL fields (description, content, tags, etc.)
        """
        cache_key = f"full:{article_id}"
        
        # Check cache first
        try:
            cached = await self.cache.get(cache_key)
            if cached:
                logger.debug(f"⚡ [Cache HIT] Full article: {article_id}")
                return cached
        except Exception:
            pass
        
        # Fetch from Appwrite
        try:
            doc = await self.appwrite_db.tablesDB.get_row(
                database_id=settings.APPWRITE_DATABASE_ID,
                collection_id=settings.APPWRITE_COLLECTION_ID,
                document_id=article_id
            )
            
            article_dict = dict(doc)
            
            # Cache for 10 minutes
            await self.cache.set(cache_key, article_dict, ttl=600)
            logger.debug(f"💾 [Cache MISS] Fetched full article: {article_id}")
            
            return article_dict
            
        except Exception as e:
            logger.error(f"❌ Error fetching article {article_id}: {e}")
            # Try cloud collection as fallback
            try:
                doc = await self.appwrite_db.tablesDB.get_row(
                    database_id=settings.APPWRITE_DATABASE_ID,
                    collection_id=settings.APPWRITE_CLOUD_COLLECTION_ID,
                    document_id=article_id
                )
                return dict(doc)
            except Exception:
                return None
    
    async def _refresh_cache_background(self, category: str, limit: int, offset: int):
        """Background task to refresh cache (SWR pattern)."""
        logger.debug(f"🔄 Background refresh for {category}")
        try:
            articles = await self._fetch_projected_articles(category, limit, offset)
            
            # Update cache layers
            cache_key = f"list:{category}:{limit}:{offset}"
            _memory_cache[cache_key] = (articles, datetime.now())
            await self.cache.set(cache_key, articles, ttl=300)
        except Exception as e:
            logger.debug(f"Background refresh failed: {e}")
    
    def _get_collection_for_category(self, category: str) -> str:
        """
        Determine which Appwrite collection to query.
        
        CRITICAL: Must mirror AppwriteDatabase.get_collection_id() exactly
        so that the data routed at write-time is found at read-time.
        """
        if not category or not category.strip():
            return settings.APPWRITE_COLLECTION_ID

        cat = category.lower().strip()

        # 1. AI Vertical
        if cat == 'ai':
            return settings.APPWRITE_AI_COLLECTION_ID

        # 2. Cloud Vertical (all sub-verticals prefixed with 'cloud-')
        if cat.startswith('cloud-'):
            return settings.APPWRITE_CLOUD_COLLECTION_ID

        # 3. Research Vertical
        if cat == 'research' or cat.startswith('research-'):
            return settings.APPWRITE_RESEARCH_COLLECTION_ID

        # 4. Data Vertical (data-*, business-*, customer-data-platform)
        if cat.startswith('data-') or cat.startswith('business-') or cat == 'customer-data-platform':
            return settings.APPWRITE_DATA_COLLECTION_ID

        # 5. Magazines
        if cat == 'magazines':
            return settings.APPWRITE_MAGAZINE_COLLECTION_ID

        # 6. Medium Articles
        if cat == 'medium-article':
            return settings.APPWRITE_MEDIUM_COLLECTION_ID

        # Default / Fallback
        return settings.APPWRITE_COLLECTION_ID
    
    def invalidate_category_cache(self, category: str):
        """
        Invalidate cache for a specific category (call after new articles added).
        """
        # Clear memory cache
        keys_to_remove = [k for k in _memory_cache.keys() if k.startswith(f" list:{category}:")]
        for key in keys_to_remove:
            del _memory_cache[key]
        
        logger.debug(f"🗑️  Invalidated cache for category: {category}")


# Singleton instance
optimized_retrieval = OptimizedRetrieval()
