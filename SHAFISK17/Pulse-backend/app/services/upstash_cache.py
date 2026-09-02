"""
Upstash Redis Cache Service (REST API)
======================================

Optimized for Upstash Free Tier:
- Data Size: 256 MB (we target max 200 MB)
- Bandwidth: 50 GB/month
- Commands: 10,000/sec
- Request Size: 10 MB
- Record Size: 100 MB

Uses HTTP REST API instead of redis-py for serverless compatibility.
"""

import httpx
import json
import logging
from typing import Any, Optional
from datetime import datetime, date

logger = logging.getLogger(__name__)


class _DatetimeEncoder(json.JSONEncoder):
    """
    JSON encoder that converts datetime/date objects to ISO-8601 strings.
    Prevents 'Object of type datetime is not JSON serializable' when caching
    article dicts that contain Appwrite-returned datetime fields.
    """
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)


class UpstashCache:
    """
    REST-based Redis caching service for Upstash
    
    Features:
    - HTTP REST client (no redis-py needed)
    - Automatic TTL management
    - Memory-efficient serialization
    - Graceful error handling
    """
    
    def __init__(
        self,
        rest_url: str,
        rest_token: str,
        enabled: bool = True,
        default_ttl: int = 300  # 5 minutes
    ):
        """
        Initialize Upstash cache
        
        Args:
            rest_url: Upstash REST API URL
            rest_token: Upstash REST API token
            enabled: Whether caching is enabled
            default_ttl: Default TTL in seconds
        """
        self.rest_url = rest_url.rstrip('/')
        if self.rest_url and not self.rest_url.startswith("http"):
             self.rest_url = f"https://{self.rest_url}"
             
        # Auto-disable if URL is missing
        if not self.rest_url:
            enabled = False
            logger.warning("⚠️  Upstash URL missing. Disabling cache.")
            
        self.rest_token = rest_token
        self.enabled = enabled
        self.default_ttl = default_ttl
        
        # Stats tracking
        self.stats = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'errors': 0
        }
        
        if not self.enabled:
            logger.info("ℹ️  Upstash cache disabled (ENABLE_UPSTASH_CACHE=False)")
        else:
            logger.info("=" * 70)
            logger.info("🚀 [UPSTASH] Redis cache initialized")
            logger.info(f"   URL: {rest_url}")
            logger.info(f"   Default TTL: {default_ttl}s")
            logger.info(f"   Free Tier: 256 MB data, 50 GB/month bandwidth")
            logger.info("=" * 70)
            
    def _get_client_kwargs(self) -> dict:
        """Return kwargs for creating a new httpx.AsyncClient"""
        return {
            "timeout": 5.0,  # 5 second timeout
            "headers": {
                "Authorization": f"Bearer {self.rest_token}",
                "Content-Type": "application/json"
            }
        }
    

    async def _execute_command(self, command: list) -> Optional[Any]:
        """
        Execute Redis command via REST API.

        WARN-002 fixed: was using blocking requests.post() inside
        loop.run_in_executor(), which consumed one of 10 ThreadPoolExecutor
        slots per Redis call. Under load (22 categories × multiple Redis calls
        each) all 10 threads could be saturated, stalling the event loop.

        Now uses httpx.AsyncClient directly — a true async HTTP request with
        zero thread overhead, correct for an asyncio-native codebase.

        Args:
            command: Redis command as list, e.g. ["GET", "key"]

        Returns:
            Command result or None on error
        """
        if not self.enabled:
            return None

        try:
            async with httpx.AsyncClient(**self._get_client_kwargs()) as client:
                response = await client.post(self.rest_url, json=command)

            if response.status_code == 200:
                result = response.json()
                return result.get("result")
            else:
                logger.warning("⚠️  Upstash error: %s - %s", response.status_code, response.text)
                self.stats['errors'] += 1
                return None

        except Exception as e:
            logger.error("❌ Upstash request failed: %s", e)
            self.stats['errors'] += 1
            return None
    
    async def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache
        
        Args:
            key: Cache key
            
        Returns:
            Cached value (deserialized) or None if not found
        """
        if not self.enabled:
            return None
        
        try:
            result = await self._execute_command(["GET", key])
            
            if result is None:
                self.stats['misses'] += 1
                logger.debug(f"❌ Cache MISS: {key}")
                return None
            
            # Deserialize JSON
            value = json.loads(result)
            self.stats['hits'] += 1
            logger.debug(f"✅ Cache HIT: {key}")
            return value
            
        except Exception as e:
            logger.error(f"❌ Cache get error for {key}: {e}")
            self.stats['errors'] += 1
            return None
    
    async def set(
        self, 
        key: str, 
        value: Any, 
        ttl: Optional[int] = None
    ) -> bool:
        """
        Set value in cache with TTL
        
        Args:
            key: Cache key
            value: Value to cache (will be JSON serialized)
            ttl: Time-to-live in seconds (uses default if not specified)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            return False
        
        try:
            # Serialize to JSON — use _DatetimeEncoder to handle datetime objects
            # that Appwrite returns in article dicts (e.g. published_at, created_at)
            serialized = json.dumps(value, cls=_DatetimeEncoder)
            
            # Check size (warn if >1MB)
            size_kb = len(serialized) / 1024
            if size_kb > 1024:  # >1MB
                logger.warning(f"⚠️  Large cache entry: {key} ({size_kb:.1f} KB)")
            
            # Use provided TTL or default
            ttl_seconds = ttl if ttl is not None else self.default_ttl
            
            # SETEX command (set with expiration)
            result = await self._execute_command(["SETEX", key, ttl_seconds, serialized])
            
            if result == "OK" or result is not None:
                self.stats['sets'] += 1
                logger.debug(f"💾 Cache SET: {key} (TTL: {ttl_seconds}s, Size: {size_kb:.1f} KB)")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ Cache set error for {key}: {e}")
            self.stats['errors'] += 1
            return False
    
    async def delete(self, key: str) -> bool:
        """
        Delete key from cache
        
        Args:
            key: Cache key to delete
            
        Returns:
            True if deleted, False otherwise
        """
        if not self.enabled:
            return False
        
        try:
            result = await self._execute_command(["DEL", key])
            deleted = result == 1
            
            if deleted:
                logger.debug(f"🗑️  Cache DELETE: {key}")
            
            return deleted
            
        except Exception as e:
            logger.error(f"❌ Cache delete error for {key}: {e}")
            return False

    async def lpush(self, queue_name: str, item: str) -> bool:
        """
        Push an item to the left of a Redis list (Producer action)
        
        Args:
            queue_name: Name of the list/queue
            item: String item to push
        """
        try:
            result = await self._execute_command(["LPUSH", queue_name, item])
            return result is not None
        except Exception as e:
            logger.error(f"❌ LPUSH error: {e}")
            return False

    async def rpop(self, queue_name: str) -> Optional[str]:
        """
        Remove and return the rightmost item of a Redis list (Consumer action)
        """
        try:
            return await self._execute_command(["RPOP", queue_name])
        except Exception as e:
            logger.error(f"❌ RPOP error: {e}")
            return None

    async def llen(self, queue_name: str) -> int:
        """
        Get the length of the queue to prevent flooding
        """
        try:
            result = await self._execute_command(["LLEN", queue_name])
            return int(result) if result is not None else 0
        except Exception:
            return 0

    async def rpoplpush(self, source_queue: str, destination_queue: str) -> Optional[str]:
        """
        Atomically move a task from pending to processing (Reliable Queue pattern)
        """
        try:
            return await self._execute_command(["RPOPLPUSH", source_queue, destination_queue])
        except Exception as e:
            logger.error(f"❌ RPOPLPUSH error: {e}")
            return None

    async def lrem(self, queue_name: str, count: int, item: str) -> bool:
        """
        Remove occurrences of an item from a list.
        """
        try:
            result = await self._execute_command(["LREM", queue_name, count, item])
            return result is not None
        except Exception:
            return False
    
    async def invalidate_pattern(self, pattern: str) -> int:
        """
        Invalidate all keys matching pattern
        
        Args:
            pattern: Redis pattern (e.g., "news:*")
            
        Returns:
            Number of keys deleted
        """
        if not self.enabled:
            return 0
        
        try:
            # Get all matching keys
            keys = await self._execute_command(["KEYS", pattern])
            
            if not keys:
                return 0
            
            # Delete all keys
            for key in keys:
                await self._execute_command(["DEL", key])
            
            logger.info(f"🗑️  Invalidated {len(keys)} keys matching '{pattern}'")
            return len(keys)
            
        except Exception as e:
            logger.error(f"❌ Cache invalidation error for {pattern}: {e}")
            return 0
    
    def get_stats(self) -> dict:
        """Get cache statistics"""
        total_requests = self.stats['hits'] + self.stats['misses']
        hit_rate = (
            self.stats['hits'] / total_requests * 100 
            if total_requests > 0 else 0
        )
        
        return {
            **self.stats,
            'total_requests': total_requests,
            'hit_rate_percent': round(hit_rate, 2),
            'enabled': self.enabled
        }
    
    def print_stats(self):
        """Print cache statistics"""
        stats = self.get_stats()
        
        logger.info("")
        logger.info("=" * 70)
        logger.info("📊 [UPSTASH] Cache Statistics")
        logger.info("=" * 70)
        logger.info(f"   🔹 Total Requests: {stats['total_requests']:,}")
        logger.info(f"   🔹 Cache Hits: {stats['hits']:,}")
        logger.info(f"   🔹 Cache Misses: {stats['misses']:,}")
        logger.info(f"   🔹 Hit Rate: {stats['hit_rate_percent']}%")
        logger.info(f"   🔹 Sets: {stats['sets']:,}")
        logger.info(f"   🔹 Errors: {stats['errors']:,}")
        logger.info("=" * 70)
        logger.info("")
    
    async def health_check(self) -> bool:
        """
        Check if Upstash is reachable
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            result = await self._execute_command(["PING"])
            healthy = result == "PONG"
            
            if healthy:
                logger.info("✅ Upstash health check: OK")
            else:
                logger.warning("⚠️  Upstash health check: FAILED")
            
            return healthy
            
        except Exception as e:
            logger.error(f"❌ Upstash health check error: {e}")
            return False
    
    async def close(self):
        """Close HTTP client - No-op since we use per-request clients now"""
        pass


# Global singleton instance
_upstash_cache: Optional[UpstashCache] = None


def get_upstash_cache() -> UpstashCache:
    """
    Get or create global Upstash cache instance
    
    Returns:
        UpstashCache: Singleton cache instance
    """
    global _upstash_cache
    
    if _upstash_cache is None:
        from app.config import settings
        
        _upstash_cache = UpstashCache(
            rest_url=settings.UPSTASH_REDIS_REST_URL,
            rest_token=settings.UPSTASH_REDIS_REST_TOKEN,
            enabled=settings.ENABLE_UPSTASH_CACHE,
            default_ttl=300  # 5 minutes default
        )
    
    return _upstash_cache
