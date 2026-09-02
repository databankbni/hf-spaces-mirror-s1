from fastapi import APIRouter, HTTPException, Query
from app.models import SearchResponse
from app.services.news_aggregator import NewsAggregator
from app.services.cache_service import CacheService
import logging

logger = logging.getLogger(__name__)

router = APIRouter()
news_aggregator = NewsAggregator()
cache_service = CacheService()

@router.get("/", response_model=SearchResponse)
async def search_news(q: str = Query(..., min_length=2, description="Search query")):
    """
    Search news articles by keyword (Direct Aggregation)
    """
    try:
        # Check cache
        cache_key = f"search:{q.lower()}"
        cached_data = await cache_service.get(cache_key)
        if cached_data:
            return SearchResponse(
                success=True,
                query=q,
                count=len(cached_data),
                articles=cached_data
            )
        
        # Strategy: Keyword Search only (Vector Search Removed)
        # We fetch keyword results from external providers
        keyword_articles = await news_aggregator.search(q)
        
        # Deduplicate results
        merged_map = {}
        for art in keyword_articles:
            if art.get('url') and art['url'] not in merged_map:
                merged_map[art['url']] = art
        
        final_articles = list(merged_map.values())
        
        # Observability: Log Search Performance
        logger.info("🔎 [Search] Query: '%s' | Results: %d", q, len(final_articles))
        
        # Cache results
        await cache_service.set(cache_key, final_articles, ttl=300)
        
        return SearchResponse(
            success=True,
            query=q,
            count=len(final_articles),
            articles=final_articles
        )
    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
