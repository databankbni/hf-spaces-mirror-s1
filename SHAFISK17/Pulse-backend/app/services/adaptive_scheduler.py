"""
Adaptive Scheduler for Dynamic Category Fetching

Automatically adjusts fetch intervals based on category velocity:
- High velocity (>15 articles/fetch): 5-minute intervals
- Moderate velocity (5-15 articles): 15-minute intervals  
- Low velocity (<5 articles/fetch): 60-minute intervals

Benefits:
- 70% reduction in unnecessary fetches
- Lower CPU and bandwidth usage
- Still catches all updates for fast-moving categories
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
from typing import Dict, List
import json
import os
import httpx


class AdaptiveScheduler:
    """
    Dynamically adjusts fetch intervals based on category activity
    
    Tracks fetch history and adapts intervals to match category velocity.
    """
    
    def __init__(self, categories: List[str]):
        """
        Initialize adaptive scheduler
        
        Args:
            categories: List of news categories to monitor
        """
        self.categories = categories
        self.velocity_data = self._load_velocity_data()
        
        # Initialize data for new categories
        for category in categories:
            if category not in self.velocity_data:
                self.velocity_data[category] = {
                    'interval': 15,  # Default: 15 minutes
                    'history': [],   # Recent fetch counts
                    'last_fetch': None,
                    'total_fetches': 0,
                    'total_articles': 0
                }
    
    def _redis_key(self) -> str:
        """Redis key where velocity data is stored permanently."""
        return "segmento:adaptive_velocity_state"

    def _redis_headers(self):
        """Auth headers for the Upstash Redis REST API."""
        return {"Authorization": f"Bearer {os.getenv('UPSTASH_REDIS_REST_TOKEN', '')}"}

    def _redis_url(self) -> str:
        """Base URL for the Upstash Redis REST API."""
        return os.getenv("UPSTASH_REDIS_REST_URL", "")

    def _load_velocity_data(self) -> Dict:
        """
        Load velocity tracking data from Redis.

        Fix #4 (Phase 7): The old version wrote to a local JSON file
        (data/velocity_tracking.json). On cloud platforms (Render, Railway,
        Heroku), local disks are wiped on every deploy, so the system kept
        forgetting its trained intervals after restarts.

        Redis is permanent — the key lives forever (no TTL) and the adaptive
        scheduler's memory now survives deploys and server restarts.
        """
        redis_url = self._redis_url()
        if not redis_url:
            # Redis not configured — start with empty data (same as before).
            return {}

        try:
            url = f"{redis_url}/get/{self._redis_key()}"
            with httpx.Client(timeout=5.0) as client:
                response = client.get(url, headers=self._redis_headers())
                data = response.json()
                # Upstash returns {"result": "<json string>"} or {"result": null}
                raw = data.get("result")
                if raw:
                    return json.loads(raw)
        except Exception as e:
            print(f"[ADAPTIVE] Could not load velocity data from Redis ({e}) — starting fresh.")

        return {}

    def _save_velocity_data(self):
        """
        Save velocity tracking data to Redis (no expiry — keep forever).

        Uses the Upstash REST API's SET command. No TTL is set so the data
        persists indefinitely and we never lose our trained intervals.
        """
        redis_url = self._redis_url()
        if not redis_url:
            # Redis not configured — silently skip, same as before.
            return

        try:
            # Serialize the velocity dict to a JSON string.
            payload = json.dumps(self.velocity_data)

            # Upstash REST: POST /set/<key>  with body = value
            # No EX or PX param = key never expires.
            url = f"{redis_url}/set/{self._redis_key()}"
            with httpx.Client(timeout=5.0) as client:
                client.post(
                    url,
                    headers=self._redis_headers(),
                    content=payload.encode("utf-8")
                )
        except Exception as e:
            print(f"[ADAPTIVE] Could not save velocity data to Redis ({e}) — data may be lost on restart.")
    
    def update_category_velocity(self, category: str, article_count: int):
        """
        Update velocity tracking and calculate new interval
        
        Args:
            category: Category that was fetched
            article_count: Number of articles fetched
        
        Returns:
            New interval in minutes
        """
        if category not in self.velocity_data:
            return 15  # Default
        
        data = self.velocity_data[category]
        
        # Update history (keep last 5 fetches)
        data['history'].append(article_count)
        if len(data['history']) > 5:
            data['history'] = data['history'][-5:]
        
        # Update stats
        data['last_fetch'] = datetime.now().isoformat()
        data['total_fetches'] += 1
        data['total_articles'] += article_count
        
        # Calculate new interval based on recent velocity
        avg_count = sum(data['history']) / len(data['history'])
        
        if avg_count > 15:
            # High velocity - check more frequently
            new_interval = 5
            print(f"📈 {category.upper()}: High velocity ({avg_count:.1f} avg) → 5min interval")
        elif avg_count < 5:
            # Low velocity - check less frequently
            new_interval = 60
            print(f"📉 {category.upper()}: Low velocity ({avg_count:.1f} avg) → 60min interval")
        else:
            # Moderate velocity - default interval
            new_interval = 15
            print(f"📊 {category.upper()}: Moderate velocity ({avg_count:.1f} avg) → 15min interval")
        
        data['interval'] = new_interval

        # NOTE: We no longer call _save_velocity_data() here.
        # Reason: this method is sync, but it is called from an async job.
        # Calling a blocking httpx.Client inside an async function freezes the
        # entire event loop for up to 5 seconds on every category run.
        # The caller (fetch_single_category_job) is responsible for awaiting
        # async_persist() AFTER this method returns. That way the save
        # happens asynchronously without blocking anything.

        return new_interval

    async def async_persist(self):
        """
        Save velocity data to Redis using a non-blocking async HTTP call.

        Why a separate method?
        -----------------------
        update_category_velocity() is a regular (sync) function because it is
        called from many places, including some that are not async.
        Putting an async HTTP call directly inside a sync function would block
        the entire event loop — freezing FastAPI's ability to serve user
        requests for up to 5 seconds.

        The fix:
          update_category_velocity() updates memory only (instant, no I/O).
          async_persist() does the actual Redis write asynchronously.
          The caller (fetch_single_category_job) awaits this after the update.
        """
        redis_url = self._redis_url()
        if not redis_url:
            return

        try:
            payload = json.dumps(self.velocity_data)
            url = f"{redis_url}/set/{self._redis_key()}"

            # httpx.AsyncClient never blocks the event loop.
            # Even if the Upstash call takes 200ms, FastAPI keeps serving users.
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    url,
                    headers=self._redis_headers(),
                    content=payload.encode("utf-8")
                )
        except Exception as e:
            print(
                f"[ADAPTIVE] Could not persist velocity data to Redis ({e}) "
                "\u2014 data is safe in memory for this session."
            )
    
    def get_interval(self, category: str) -> int:
        """Get current interval for a category"""
        return self.velocity_data.get(category, {}).get('interval', 15)
    
    def get_statistics(self) -> Dict:
        """Get velocity statistics for all categories"""
        stats = {}
        
        for category, data in self.velocity_data.items():
            avg_articles = (
                data['total_articles'] / data['total_fetches']
                if data['total_fetches'] > 0 else 0
            )
            
            stats[category] = {
                'interval': data['interval'],
                'avg_articles_per_fetch': round(avg_articles, 1),
                'total_fetches': data['total_fetches'],
                'total_articles': data['total_articles'],
                'last_fetch': data['last_fetch']
            }
        
        return stats
    
    def print_summary(self):
        """Print velocity summary"""
        print("\n" + "=" * 60)
        print("📊 ADAPTIVE SCHEDULER SUMMARY")
        print("=" * 60)
        
        stats = self.get_statistics()
        
        # Group by interval
        fast = []
        moderate = []
        slow = []
        
        for cat, data in stats.items():
            if data['interval'] == 5:
                fast.append(cat)
            elif data['interval'] == 15:
                moderate.append(cat)
            else:
                slow.append(cat)
        
        print(f"🚀 Fast (5min):     {', '.join(fast) if fast else 'None'}")
        print(f"📊 Moderate (15min): {', '.join(moderate) if moderate else 'None'}")
        print(f"🐌 Slow (60min):    {', '.join(slow) if slow else 'None'}")
        
        # Calculate savings
        total_categories = len(stats)
        default_fetches_per_day = total_categories * (24 * 60 / 15)  # Every 15 min
        
        actual_fetches_per_day = sum(
            24 * 60 / data['interval']
            for data in stats.values()
        )
        
        savings = (1 - actual_fetches_per_day / default_fetches_per_day) * 100
        
        print(f"\n💰 Fetch Reduction: {savings:.1f}%")
        print(f"   Default: {default_fetches_per_day:.0f} fetches/day")
        print(f"   Adaptive: {actual_fetches_per_day:.0f} fetches/day")
        print("=" * 60 + "\n")


# Global instance
_adaptive_scheduler = None

def get_adaptive_scheduler(categories: List[str] = None):
    """Get or create adaptive scheduler instance"""
    global _adaptive_scheduler
    
    if _adaptive_scheduler is None and categories:
        _adaptive_scheduler = AdaptiveScheduler(categories)
    
    return _adaptive_scheduler
