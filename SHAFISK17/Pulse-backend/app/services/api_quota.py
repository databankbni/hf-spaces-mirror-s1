"""
API Quota Tracking Service
Monitors API usage and prevents hitting rate limits
"""

from typing import Dict, Optional
from datetime import datetime, timedelta, date
import logging

logger = logging.getLogger(__name__)


class APIQuotaTracker:
    """Track API usage and enforce rate limits"""
    
    def __init__(self):
        self.quotas = {
            "gnews": {
                "calls_per_day": 100,
                "calls_made": 0,
                "reset_time": None,
                "last_call": None
            },
            "newsapi": {
                "calls_per_day": 100,
                "calls_made": 0,
                "reset_time": None,
                "last_call": None
            },
            "newsdata": {
                "calls_per_day": 200,
                "calls_made": 0,
                "reset_time": None,
                "last_call": None
            },
            "groq": {
                "tokens_per_minute": 30000,
                "tokens_used": 0,
                "reset_time": None,
                "last_call": None
            }
        }
    
    def record_call(self, provider: str, tokens_or_calls: int = 1):
        """Record an API call"""
        if provider not in self.quotas:
            logger.warning(f"Unknown provider: {provider}")
            return
        
        now = datetime.now()
        quota = self.quotas[provider]
        
        # Reset daily counters if needed
        if quota["reset_time"] and now > quota["reset_time"]:
            if "calls_per_day" in quota:
                quota["calls_made"] = 0
            else:
                quota["tokens_used"] = 0
        
        # Set reset time if not set
        if not quota["reset_time"]:
            if "calls_per_day" in quota:
                quota["reset_time"] = now + timedelta(days=1)
            else:
                quota["reset_time"] = now + timedelta(minutes=1)
        
        # Record the call
        if "calls_per_day" in quota:
            quota["calls_made"] += tokens_or_calls
        else:
            quota["tokens_used"] += tokens_or_calls
        
        quota["last_call"] = now.isoformat()
        
        # Log warning if approaching limit
        self._check_limits(provider)
    
    def _check_limits(self, provider: str):
        """Check if approaching rate limits"""
        quota = self.quotas[provider]
        
        if "calls_per_day" in quota:
            limit = quota["calls_per_day"]
            used = quota["calls_made"]
            if used >= limit * 0.9:
                logger.warning(f"⚠️ {provider} approaching daily limit: {used}/{limit}")
            if used >= limit:
                logger.error(f"❌ {provider} daily limit exceeded: {used}/{limit}")
        else:
            limit = quota["tokens_per_minute"]
            used = quota["tokens_used"]
            if used >= limit * 0.9:
                logger.warning(f"⚠️ {provider} approaching token limit: {used}/{limit} per minute")
            if used >= limit:
                logger.error(f"❌ {provider} token limit exceeded: {used}/{limit} per minute")
    
    def can_make_call(self, provider: str, tokens_or_calls: int = 1) -> bool:
        """Check if an API call can be made without exceeding quotas"""
        if provider not in self.quotas:
            return True
        
        quota = self.quotas[provider]
        now = datetime.now()
        
        # Reset if needed
        if quota["reset_time"] and now > quota["reset_time"]:
            if "calls_per_day" in quota:
                quota["calls_made"] = 0
            else:
                quota["tokens_used"] = 0
            quota["reset_time"] = None
        
        # Check limits
        if "calls_per_day" in quota:
            return quota["calls_made"] + tokens_or_calls <= quota["calls_per_day"]
        else:
            return quota["tokens_used"] + tokens_or_calls <= quota["tokens_per_minute"]
    
    def get_stats(self) -> Dict:
        """Get current quota usage statistics"""
        stats = {}
        
        for provider, quota in self.quotas.items():
            if "calls_per_day" in quota:
                stats[provider] = {
                    "limit": quota["calls_per_day"],
                    "used": quota["calls_made"],
                    "remaining": quota["calls_per_day"] - quota["calls_made"],
                    "reset_time": quota["reset_time"].isoformat() if quota["reset_time"] else None,
                    "last_call": quota["last_call"]
                }
            else:
                stats[provider] = {
                    "limit": f"{quota['tokens_per_minute']} tokens/min",
                    "used": quota["tokens_used"],
                    "remaining": quota["tokens_per_minute"] - quota["tokens_used"],
                    "reset_time": quota["reset_time"].isoformat() if quota["reset_time"] else None,
                    "last_call": quota["last_call"]
                }
        
        return stats

    # --------------------------------------------------------------------------
    # REDIS-BACKED ASYNC METHODS  (Phase 3 additions)
    # --------------------------------------------------------------------------
    # These two methods do the same job as can_make_call() and record_call(),
    # but they also read and write from Upstash Redis.
    #
    # Why two sets of methods?  Because the old sync methods are called from
    # places we do not want to change right now.  The new async ones are called
    # only from news_aggregator.py, which is already async.
    #
    # Redis key format: quota:{provider}:{YYYY-MM-DD}
    #   e.g.  quota:gnews:2026-02-26
    # TTL: 86400 seconds (24 hours) — the key naturally disappears at the end
    # of the day, which is the same as resetting the counter to zero at midnight.
    # --------------------------------------------------------------------------

    async def async_can_make_call(self, provider: str, calls: int = 1) -> bool:
        """
        Check if we can still call this paid provider today.

        Reads the current call count from Redis first (so the answer survives
        server restarts). Falls back to the in-memory count if Redis is down.
        """
        if provider not in self.quotas or "calls_per_day" not in self.quotas[provider]:
            # Unknown or non-daily provider — allow the call.
            return True

        limit = self.quotas[provider]["calls_per_day"]

        try:
            from app.services.upstash_cache import get_upstash_cache
            cache = get_upstash_cache()
            redis_key = f"quota:{provider}:{date.today().isoformat()}"

            # Ask Redis: how many calls have been made today so far?
            raw = await cache._execute_command(["GET", redis_key])
            used_today = int(raw) if raw is not None else 0

            # Also sync in-memory so the sync path stays accurate.
            self.quotas[provider]["calls_made"] = used_today

            can_call = (used_today + calls) <= limit
            if not can_call:
                logger.warning(
                    "[QUOTA] %s daily limit reached: %d/%d (Redis source)",
                    provider.upper(), used_today, limit
                )
            return can_call

        except Exception as e:
            # Redis unavailable — fall back to the in-memory counter.
            logger.debug("[QUOTA] Redis unavailable (%s) — using in-memory fallback.", e)
            return self.can_make_call(provider, calls)

    async def async_record_call(self, provider: str, calls: int = 1):
        """
        Record that we just used one API credit for this provider.

        Writes to BOTH in-memory AND Redis so the count is correct
        whether the server restarts or not.
        """
        if provider not in self.quotas or "calls_per_day" not in self.quotas[provider]:
            return

        # Always update in-memory immediately (zero latency fast path).
        self.record_call(provider, calls)

        # Then persist to Redis in the background so a restart does not lose the count.
        try:
            from app.services.upstash_cache import get_upstash_cache
            cache = get_upstash_cache()
            redis_key = f"quota:{provider}:{date.today().isoformat()}"

            # INCR atomically adds 1 to the counter.
            # If the key does not exist yet, Redis creates it and starts at 0.
            await cache._execute_command(["INCR", redis_key])

            # Make sure the key expires at the end of today (24-hour TTL).
            # EXPIRE only sets it if not already set, so we do not keep
            # resetting the TTL on every call.
            await cache._execute_command(["EXPIRE", redis_key, 86400])

            logger.debug(
                "[QUOTA] Recorded call for %s in Redis (key: %s).",
                provider.upper(), redis_key
            )

        except Exception as e:
            # Redis write failed — in-memory was already updated, so we are still
            # protected within this session. Log and move on.
            logger.debug(
                "[QUOTA] Redis write failed for %s (%s) — in-memory count still correct.",
                provider.upper(), e
            )


# Global singleton
_quota_tracker: Optional[APIQuotaTracker] = None


def get_quota_tracker() -> APIQuotaTracker:
    """Get or create global quota tracker instance"""
    global _quota_tracker
    
    if _quota_tracker is None:
        _quota_tracker = APIQuotaTracker()
        logger.info("📊 API Quota Tracker initialized")
    
    return _quota_tracker
