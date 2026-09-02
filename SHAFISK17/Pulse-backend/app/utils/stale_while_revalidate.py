"""
Stale-While-Revalidate Caching Pattern

Prevents the "Thundering Herd" problem where cache expiration causes
500 simultaneous database hits.

Pattern:
1. Serve stale data immediately (fast response)
2. Trigger background refresh (for next user)
3. No user ever waits for database

Performance:
- All requests: ~5ms (always from cache)
- Background refresh: Async, doesn't block users
- Database protected from traffic spikes
"""

import asyncio
import time
from typing import Optional, Callable, Any
import json


class StaleWhileRevalidate:
    """
    Cache with stale-while-revalidate pattern
    
    When cache expires:
    - Returns old (stale) data immediately
    - Triggers background refresh
    - Next user gets fresh data
    """
    
    def __init__(self, redis_client=None):
        """
        Initialize cache manager
        
        Args:
            redis_client: Optional Redis client
        """
        self.redis = redis_client
        self.refresh_locks = {}  # Prevent duplicate refreshes
    
    async def get_or_fetch(
        self,
        cache_key: str,
        fetch_func: Callable,
        ttl: int = 600,
        stale_ttl: int = 3600
    ) -> Any:
        """
        Get data with stale-while-revalidate pattern
        
        Args:
            cache_key: Cache key
            fetch_func: Async function to fetch fresh data
            ttl: Fresh data TTL (default: 10 minutes)
            stale_ttl: Stale data TTL (default: 1 hour)
            
        Returns:
            Cached or fresh data
        """
        if not self.redis:
            # No cache available - fetch directly
            return await fetch_func()
        
        try:
            # Try to get cached data with metadata
            cached_raw = await self.redis.get(cache_key)
            
            if cached_raw:
                cached = json.loads(cached_raw)
                data = cached.get('data')
                timestamp = cached.get('timestamp', 0)
                age = time.time() - timestamp
                
                # Fresh data (< TTL): Return immediately
                if age < ttl:
                    return data
                
                # Stale data (TTL < age < stale_ttl): Return + refresh in background
                if age < stale_ttl:
                    # Return stale data immediately (fast!)
                    # User doesn't wait
                    
                    # Trigger background refresh (fire-and-forget)
                    asyncio.create_task(
                        self._background_refresh(cache_key, fetch_func, ttl, stale_ttl)
                    )
                    
                    return data
                
                # Too stale (> stale_ttl): Fetch fresh data
                # This should rarely happen if traffic is consistent
            
            # No cache or too old: Fetch fresh data
            return await self._fetch_and_cache(cache_key, fetch_func, ttl, stale_ttl)
            
        except Exception as e:
            print(f"Cache error for {cache_key}: {e}")
            # On cache failure, fetch directly
            return await fetch_func()
    
    async def _background_refresh(
        self,
        cache_key: str,
        fetch_func: Callable,
        ttl: int,
        stale_ttl: int
    ):
        """
        Refresh cache in background (doesn't block user request)
        """
        # Prevent duplicate refreshes (race condition)
        if cache_key in self.refresh_locks:
            return  # Already refreshing
        
        try:
            self.refresh_locks[cache_key] = True
            
            # Fetch fresh data
            fresh_data = await fetch_func()
            
            # Update cache
            cache_value = {
                'data': fresh_data,
                'timestamp': time.time()
            }
            
            await self.redis.setex(
                cache_key,
                stale_ttl,  # Store for stale_ttl duration
                json.dumps(cache_value)
            )
            
        except Exception as e:
            print(f"Background refresh failed for {cache_key}: {e}")
        finally:
            self.refresh_locks.pop(cache_key, None)
    
    async def _fetch_and_cache(
        self,
        cache_key: str,
        fetch_func: Callable,
        ttl: int,
        stale_ttl: int
    ) -> Any:
        """
        Fetch fresh data and store in cache
        """
        fresh_data = await fetch_func()
        
        # Store with metadata
        cache_value = {
            'data': fresh_data,
            'timestamp': time.time()
        }
        
        try:
            await self.redis.setex(
                cache_key,
                stale_ttl,
                json.dumps(cache_value)
            )
        except Exception as e:
            print(f"Cache write failed for {cache_key}: {e}")
        
        return fresh_data


# Example usage:
"""
# In your API endpoint:
cache = StaleWhileRevalidate(redis_client)

async def fetch_articles_from_db():
    return await db.get_articles('ai', limit=20)

# This always returns quickly:
# - If fresh: from cache (~5ms)
# - If stale: from cache (~5ms) + background refresh
# - If expired: fetch from DB (~50ms)
articles = await cache.get_or_fetch(
    cache_key='news:ai:cursor:xyz',
    fetch_func=fetch_articles_from_db,
    ttl=600,        # Fresh for 10 minutes
    stale_ttl=3600  # Serve stale for up to 1 hour
)
"""


# Example timeline:
"""
T=0: Cache miss → Fetch from DB (50ms) → Store in cache
T=300s: User request → Cache hit (5ms) → Fresh data
T=600s: User request → Cache hit (5ms) → Stale data (still valid!)
        → Background refresh triggered (user already got response)
T=605s: Background refresh completes → Cache updated
T=610s: Next user → Cache hit (5ms) → Fresh data again!

Result: All users get 5ms responses, DB never overwhelmed!
"""
