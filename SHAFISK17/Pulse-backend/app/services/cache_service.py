"""
Cache Service using Redis
Provides caching layer to reduce external API calls with graceful bypass when disabled.
Supports both:
1. Upstash Redis (REST HTTP API) - Optimized for serverless/free tier
2. Local/Standard Redis (TCP) - Standard redis-py client
"""

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from typing import Optional, Any, List
import json
import logging
from app.config import settings
from app.models import Article
from app.services.upstash_cache import get_upstash_cache

logger = logging.getLogger(__name__)

class CacheService:
    """
    Unified Cache Service
    Delegates to Upstash (if enabled) or Local Redis (if enabled)
    """
    
    def __init__(self):
        # 1. Try Upstash First (Preferred for Production/Free Tier)
        self.upstash = None
        
        # Check explicit Upstash flag
        if settings.ENABLE_UPSTASH_CACHE:
            self.upstash = get_upstash_cache()
            if self.upstash.enabled:
                self.mode = "upstash"
                # Only log once to avoid noise
                # logger.info("⚡ CacheService: Using Upstash Redis")
            else:
                self.mode = "disabled" # Upstash enabled but failed init
                
        # 2. Try Local Redis (Fallback)
        elif settings.ENABLE_REDIS and REDIS_AVAILABLE:
            self.mode = "redis"
            self.redis_client = None
            logger.info("🔌 CacheService: Using Local Redis")
        
        # 3. Disabled
        else:
            self.mode = "disabled"
            if settings.ENABLE_REDIS and not REDIS_AVAILABLE:
                logger.warning("⚠️  ENABLE_REDIS=True but Redis package not installed")
            
            # Silent unless debug
            # logger.info("ℹ️  Cache disabled (Bypass Mode)")

    async def connect(self):
        """Connect to Redis (if using local redis)"""
        if self.mode == "redis" and not self.redis_client:
            try:
                self.redis_client = await redis.from_url(
                    settings.REDIS_URL,
                    password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None,
                    encoding="utf-8",
                    decode_responses=True
                )
                logger.info("✓ Local Redis connected")
            except Exception as e:
                logger.error(f"✗ Local Redis connection failed: {e}")
                self.mode = "disabled"
                self.redis_client = None
    
    async def get(self, key: str) -> Optional[List[Article]]:
        """Get cached articles by key"""
        if self.mode == "disabled":
            return None
            
        try:
            if self.mode == "upstash":
                # UpstashCache.get() is now async (httpx) — await directly.
                # The old asyncio.to_thread() path was correct when it used
                # blocking requests.post, but caused a RuntimeWarning after
                # the httpx migration because to_thread only accepts sync callables.
                data = await self.upstash.get(key)
                if data:
                    try:
                        return [Article(**item) for item in data]
                    except Exception as parse_error:
                        logger.warning("⚠️ Cache parse error for %s: %s", key, parse_error)
                        return None
                return None

            # Local Redis (Async/TCP)
            elif self.mode == "redis":
                if not self.redis_client:
                    await self.connect()
                
                if self.redis_client:
                    json_str = await self.redis_client.get(key)
                    if json_str:
                        return [Article(**item) for item in json.loads(json_str)]
                    
        except Exception as e:
            logger.error("❌ Cache get error (%s): %s", self.mode, e)
            return None
            
        return None
    
    async def set(self, key: str, value: List[Article], ttl: Optional[int] = None) -> bool:
        """Set cached articles with TTL"""
        if self.mode == "disabled":
            return True # Pretend success
            
        try:
            # Prepare data (list of dictionaries)
            # Use model_dump if Pydantic v2, else dict()
            serialized_data = []
            for item in value:
                if hasattr(item, 'model_dump'):
                    serialized_data.append(item.model_dump())
                elif hasattr(item, 'dict'):
                    serialized_data.append(item.dict())
                else:
                    serialized_data.append(item) # Already dict?

            cache_ttl = ttl if ttl is not None else settings.CACHE_TTL
            
            if self.mode == "upstash":
                # UpstashCache.set() is now async — await directly.
                return await self.upstash.set(key, serialized_data, ttl=cache_ttl)
                
            # Local Redis
            elif self.mode == "redis":
                if not self.redis_client:
                    await self.connect()
                
                if self.redis_client:
                    await self.redis_client.setex(
                        key, 
                        cache_ttl, 
                        json.dumps(serialized_data, default=str)
                    )
                    return True
                    
        except Exception as e:
            logger.error("❌ Cache set error (%s): %s", self.mode, e)
            return False
            
        return False
    
    async def delete(self, key: str) -> bool:
        """Delete cached data"""
        if self.mode == "disabled":
            return True
            
        try:
            if self.mode == "upstash":
                # UpstashCache.delete() is now async — await directly.
                return await self.upstash.delete(key)
            elif self.mode == "redis":
                if not self.redis_client:
                    await self.connect()
                if self.redis_client:
                    await self.redis_client.delete(key)
                    return True
        except Exception:
            return False
        return False

    async def clear_all(self) -> bool:
        """Clear all cache"""
        if self.mode == "disabled":
            return True
            
        try:
            if self.mode == "upstash":
                # Safe assumption for now
                return True 
            elif self.mode == "redis":
                if self.redis_client:
                    await self.redis_client.flushdb()
                    return True
        except Exception:
            return False
        return True
