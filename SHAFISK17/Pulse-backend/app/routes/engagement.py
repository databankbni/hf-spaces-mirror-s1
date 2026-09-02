"""
Engagement API Endpoints
Handles article likes, views tracking, and trending articles
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from pydantic import BaseModel
import asyncio
from app.services.appwrite_db import get_appwrite_db, _safe_get
from app.config import settings
from app.utils.id_generator import generate_article_id
from datetime import datetime, timedelta
import logging


logger = logging.getLogger(__name__)

router = APIRouter()


class EngagementRequest(BaseModel):
    url: Optional[str] = None
    title: Optional[str] = None
    image: Optional[str] = None
    category: Optional[str] = None  # NEW: For strict routing


def resolve_article_id(article_id_or_url: str) -> tuple[str, str]:
    """
    Resolve article ID from either:
    1. Direct Appwrite document ID (32 chars)
    2. Base64-encoded URL (for backwards compatibility)
    3. Plain URL
    
    Returns:
        Tuple of (appwrite_doc_id, original_url_or_id)
    """
    # If it looks like a valid Appwrite ID (32 alphanumeric chars), use it directly
    if len(article_id_or_url) == 32 and article_id_or_url.isalnum():
        return (article_id_or_url, article_id_or_url)
    
    # 3. Default fallback (legacy 20-char IDs)
    return (article_id_or_url, None)
    
    # Assume it's a plain URL, generate ID
    doc_id = generate_article_id(article_id_or_url)
    return (doc_id, article_id_or_url)


@router.get("/articles/{article_id}/stats")
@router.get("/articles/{article_id}/stats")
async def get_article_stats(article_id: str, category: Optional[str] = None):
    """
    Get engagement stats for an article.
    """
    try:
        appwrite_db = get_appwrite_db()
        doc_id, _ = resolve_article_id(article_id)
        
        # Determine strict collection if category provided
        target_collection_ids = []
        if category:
            target_collection_ids.append(appwrite_db.get_collection_id(category))
        
        # Always fallback to checking ALL known collections if not found (Safety Net)
        # Order: Targeted -> Default -> Cloud -> AI -> Data -> Magazine -> Medium
        fallback_collections = [
            settings.APPWRITE_COLLECTION_ID,
            settings.APPWRITE_CLOUD_COLLECTION_ID,
            settings.APPWRITE_AI_COLLECTION_ID,
            settings.APPWRITE_DATA_COLLECTION_ID,
            settings.APPWRITE_MAGAZINE_COLLECTION_ID,
            settings.APPWRITE_MEDIUM_COLLECTION_ID,
            settings.APPWRITE_RESEARCH_COLLECTION_ID
        ]
        
        for cid in fallback_collections:
            if cid and cid not in target_collection_ids:
                target_collection_ids.append(cid)
        
        doc = None
        found_collection = None
        
        for collection_id in target_collection_ids:
            try:
                doc = await asyncio.to_thread(
                    appwrite_db.tablesDB.get_row,
                    database_id=settings.APPWRITE_DATABASE_ID,
                    table_id=collection_id,
                    row_id=doc_id
                )
                if doc:
                    found_collection = collection_id
                    break
            except:
                continue
        
        if not doc:
             # Return zeros (not found is common for new articles)
            return {
                "article_id": doc_id,
                "likes": 0,
                "dislikes": 0,
                "views": 0,
                "success": True # Technically success, just no data yet
            }
        
        return {
            "article_id": doc_id,
            "likes": _safe_get(doc, 'likes', 0),
            "dislikes": _safe_get(doc, 'dislikes') or _safe_get(doc, 'dislike', 0),
            "views": _safe_get(doc, 'views', 0),
            "success": True
        }

    except Exception as e:
        logger.error(f"Error getting stats for {article_id}: {e}")
        return {
            "article_id": article_id,
            "likes": 0,
            "dislikes": 0,
            "views": 0,
            "success": False
        }


@router.post("/articles/{article_id}/like")
async def like_article(article_id: str, request: EngagementRequest = None):
    """
    Increment like count for an article.
    """
    try:
        appwrite_db = get_appwrite_db()
        doc_id, _ = resolve_article_id(article_id)
        
        # ---------------------------------------------------------
        # STRICT ROUTING LOGIC
        # ---------------------------------------------------------
        # If frontend sends category, we use it to find the EXACT collection.
        # If not, we fallback to default (legacy behavior).
        target_collection_id = settings.APPWRITE_COLLECTION_ID
        
        if request and request.category:
            target_collection_id = appwrite_db.get_collection_id(request.category)
            logger.info(f"📍 Routing 'like' for {doc_id} to collection: {target_collection_id} (Category: {request.category})")
        
        # 1. Try to get document from the TARGETED collection
        try:
            doc = await asyncio.to_thread(
                appwrite_db.tablesDB.get_row,
                database_id=settings.APPWRITE_DATABASE_ID,
                table_id=target_collection_id,
                row_id=doc_id
            )
        except Exception:
            # Document NOT FOUND -> Fail with 404 (do not create — articles are seeded by ingestion)
            raise HTTPException(status_code=404, detail=f"Article {doc_id} not found in collection {target_collection_id}")

        # 3. Increment
        current_likes = _safe_get(doc, 'likes', 0)
        if current_likes is None: current_likes = 0
            
        new_likes = current_likes + 1
        
        updated_doc = await asyncio.to_thread(
            appwrite_db.tablesDB.update_row,
            database_id=settings.APPWRITE_DATABASE_ID,
            table_id=target_collection_id,
            row_id=doc_id,
            data={"likes": new_likes}
        )
        
        logger.info(f"❤️  Article {doc_id[:8]}... liked (total: {new_likes})")
        
        return {
            "article_id": doc_id,
            "likes": _safe_get(updated_doc, 'likes', new_likes),
            "success": True
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error liking article {article_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/articles/{article_id}/dislike")
async def dislike_article(article_id: str, request: EngagementRequest = None):
    """
    Increment dislike count with Upsert logic.
    """
    try:
        appwrite_db = get_appwrite_db()
        doc_id, _ = resolve_article_id(article_id)
        
        # ---------------------------------------------------------
        # STRICT ROUTING LOGIC
        # ---------------------------------------------------------
        target_collection_id = settings.APPWRITE_COLLECTION_ID
        
        if request and request.category:
            target_collection_id = appwrite_db.get_collection_id(request.category)
        
        try:
            doc = await asyncio.to_thread(
                appwrite_db.tablesDB.get_row,
                database_id=settings.APPWRITE_DATABASE_ID,
                table_id=target_collection_id,
                row_id=doc_id
            )
        except Exception:
            raise HTTPException(status_code=404, detail=f"Article {doc_id} not found in collection {target_collection_id}")
        
        current_dislikes = _safe_get(doc, 'dislikes') or _safe_get(doc, 'dislike', 0)
        if current_dislikes is None: current_dislikes = 0
            
        new_dislikes = current_dislikes + 1
        
        update_data = {"dislike": new_dislikes}

        updated_doc = await asyncio.to_thread(
            appwrite_db.tablesDB.update_row,
            database_id=settings.APPWRITE_DATABASE_ID,
            table_id=target_collection_id,
            row_id=doc_id,
            data=update_data
        )
        
        final_dislikes = _safe_get(updated_doc, 'dislike', new_dislikes)
        
        logger.info(f"👎 Article {doc_id[:8]}... disliked (total: {final_dislikes})")
        
        return {
            "article_id": doc_id,
            "dislikes": final_dislikes,
            "success": True
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error disliking article {article_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/articles/{article_id}/view")
async def track_view(article_id: str, request: EngagementRequest = None):
    """
    Increment view count with Upsert logic.
    """
    try:
        appwrite_db = get_appwrite_db()
        doc_id, _ = resolve_article_id(article_id)
        
        # ---------------------------------------------------------
        # STRICT ROUTING LOGIC
        # ---------------------------------------------------------
        target_collection_id = settings.APPWRITE_COLLECTION_ID
        
        if request and request.category:
            target_collection_id = appwrite_db.get_collection_id(request.category)
        
        try:
            doc = await asyncio.to_thread(
                appwrite_db.tablesDB.get_row,
                database_id=settings.APPWRITE_DATABASE_ID,
                table_id=target_collection_id,
                row_id=doc_id
            )
        except Exception:
            raise HTTPException(status_code=404, detail=f"Article {doc_id} not found in collection {target_collection_id}")
        
        current_views = _safe_get(doc, 'views', 0)
        if current_views is None: current_views = 0
            
        new_views = current_views + 1
        
        updated_doc = await asyncio.to_thread(
            appwrite_db.tablesDB.update_row,
            database_id=settings.APPWRITE_DATABASE_ID,
            table_id=target_collection_id,
            row_id=doc_id,
            data={"views": new_views}
        )
        
        if new_views % 10 == 0:
            logger.info(f"👁️  Article {doc_id[:8]}... reached {new_views} views")
        
        return {
            "article_id": doc_id,
            "views": new_views,
            "success": True
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error tracking view for {article_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/articles/trending")
async def get_trending_articles(
    hours: int = 24,
    limit: int = 10,
    cloud_only: bool = False
):
    """
    Get trending articles based on views and likes.
    
    Phase 3: Discover popular content.
    
    Args:
        hours: Time window for trending (default: 24 hours)
        limit: Number of articles to return (default: 10)
        cloud_only: Only return cloud articles (default: False)
        
    Returns:
        List of trending articles sorted by engagement
    """
    try:
        from appwrite.query import Query
        
        appwrite_db = get_appwrite_db()
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        
        # Determine collection
        if cloud_only and settings.APPWRITE_CLOUD_COLLECTION_ID:
            collection_id = settings.APPWRITE_CLOUD_COLLECTION_ID
        else:
            collection_id = settings.APPWRITE_COLLECTION_ID
        
        # Query articles, sorted by views (descending)
        response = await appwrite_db.tablesDB.list_rows(
            database_id=settings.APPWRITE_DATABASE_ID,
            collection_id=collection_id,
            queries=[
                Query.greater_than('published_at', cutoff),
                Query.order_desc('views'),
                Query.limit(limit)
            ]
        )
        
        articles = _safe_get(response, 'documents', [])
        
        # Calculate engagement score (views + likes * 5 - dislikes * 3)
        # Likes are weighted higher, dislikes have negative impact
        for article in articles:
            views = _safe_get(article, 'views', 0)
            likes = _safe_get(article, 'likes', 0)
            dislikes = _safe_get(article, 'dislikes') or _safe_get(article, 'dislike', 0)
            article['engagement_score'] = views + (likes * 5) - (dislikes * 3)
        
        # Sort by engagement score
        articles.sort(key=lambda x: x.get('engagement_score', 0), reverse=True)
        
        logger.info(f"🔥 Trending: {len(articles)} articles in last {hours}h")
        
        return {
            "articles": articles[:limit],
            "timeframe_hours": hours,
            "cloud_only": cloud_only,
            "total_count": len(articles)
        }
        
    except Exception as e:
        logger.error(f"Error getting trending articles: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/articles/popular-cloud")
async def get_popular_cloud_articles(provider: Optional[str] = None, limit: int = 10):
    """
    Get popular cloud articles, optionally filtered by provider.
    
    Phase 3: Cloud-specific trending.
    
    Args:
        provider: Cloud provider (aws, azure, gcp, etc.) or None for all
        limit: Number of articles (default: 10)
        
    Returns:
        Popular cloud articles
    """
    try:
        from appwrite.query import Query
        
        if not settings.APPWRITE_CLOUD_COLLECTION_ID:
            raise HTTPException(status_code=404, detail="Cloud collection not configured")
        
        appwrite_db = get_appwrite_db()
        
        queries = [
            Query.order_desc('views'),
            Query.limit(limit)
        ]
        
        # Filter by provider if specified
        if provider:
            queries.insert(0, Query.equal('provider', provider))
        
        response = await appwrite_db.tablesDB.list_rows(
            database_id=settings.APPWRITE_DATABASE_ID,
            collection_id=settings.APPWRITE_CLOUD_COLLECTION_ID,
            queries=queries
        )
        
        articles = _safe_get(response, 'documents', [])
        
        logger.info(f"☁️  Popular cloud articles: {len(articles)} (provider={provider or 'all'})")
        
        return {
            "articles": articles,
            "provider": provider,
            "total_count": len(articles)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting popular cloud articles: {e}")
        raise HTTPException(status_code=500, detail=str(e))
