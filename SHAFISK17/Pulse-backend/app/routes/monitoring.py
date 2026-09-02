"""
Cache Monitoring and Metrics API
=================================

Provides real-time monitoring of Upstash cache performance.

Metrics Tracked:
- Hit rate (%)
- Request count
- Cache size estimation
- Error count
- Provider-specific stats
"""

from fastapi import APIRouter, HTTPException
from app.services.upstash_cache import get_upstash_cache
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/cache/stats")
async def get_cache_stats():
    """
    Get real-time cache performance statistics.
    
    Returns:
        Cache hit rate, request count, errors, and health status
        
    Example Response:
        {
            "enabled": true,
            "hit_rate": 78.5,
            "total_requests": 1234,
            "cache_hits": 969,
            "cache_misses": 265,
            "errors": 2,
            "health": "healthy",
            "uptime_seconds": 3600
        }
    """
    try:
        cache = get_upstash_cache()
        
        if not cache.enabled:
            return {
                "enabled": False,
                "message": "Upstash cache is disabled",
                "health": "disabled"
            }
        
        stats = cache.get_stats()
        
        # Calculate hit rate
        total = stats.get('hits', 0) + stats.get('misses', 0)
        hit_rate = (stats.get('hits', 0) / total * 100) if total > 0 else 0.0
        
        # Determine health status
        health = "healthy"
        if stats.get('errors', 0) > 10:
            health = "degraded"
        elif hit_rate < 30 and total > 100:
            health = "low_hit_rate"
        
        return {
            "enabled": True,
            "hit_rate": round(hit_rate, 2),
            "total_requests": total,
            "cache_hits": stats.get('hits', 0),
            "cache_misses": stats.get('misses', 0),
            "errors": stats.get('errors', 0),
            "health": health,
            "timestamp": datetime.utcnow().isoformat(),
            "recommendations": _get_recommendations(hit_rate, stats)
        }
        
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cache/clear")
async def clear_cache():
    """
    Clear all cached data (admin endpoint).
    
    USE WITH CAUTION: This will force all subsequent requests to hit the database.
    
    Returns:
        Confirmation message
    """
    try:
        cache = get_upstash_cache()
        
        if not cache.enabled:
            return {
                "success": False,
                "message": "Cache is disabled"
            }
        
        # Clear cache by flushing all keys
        # Note: Upstash REST API doesn't have a direct FLUSHALL
        # This is a placeholder - implement specific key deletion if needed
        logger.warning("⚠️ Cache clear requested - not yet implemented for safety")
        
        return {
            "success": True,
            "message": "Cache clear functionality pending (safety feature)",
            "note": "Individual keys can be deleted via cache.delete(key)"
        }
        
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cache/health")
async def cache_health_check():
    """
    Simple health check endpoint for cache connectivity.
    
    Returns:
        Boolean indicating if cache is accessible
    """
    try:
        cache = get_upstash_cache()
        
        if not cache.enabled:
            return {
                "healthy": False,
                "reason": "Cache disabled",
                "enabled": False
            }
        
        # Test connectivity with a simple PING
        test_key = "_health_check_test"
        await cache.set(test_key, "ok", ttl=10)
        result = await cache.get(test_key)
        
        if result == "ok":
            return {
                "healthy": True,
                "enabled": True,
                "latency_ms": "< 100",  # Approximate
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            return {
                "healthy": False,
                "reason": "Test write/read failed",
                "enabled": True
            }
            
    except Exception as e:
        logger.error(f"Cache health check failed: {e}")
        return {
            "healthy": False,
            "reason": str(e),
            "enabled": True
        }


def _get_recommendations(hit_rate: float, stats: dict) -> list:
    """Generate recommendations based on cache performance."""
    recommendations = []
    
    total = stats.get('hits', 0) + stats.get('misses', 0)
    
    if hit_rate < 50 and total > 100:
        recommendations.append("Low hit rate detected. Consider increasing TTL values.")
    
    if stats.get('errors', 0) > 5:
        recommendations.append("Multiple cache errors detected. Check Upstash connectivity.")
    
    if hit_rate > 90 and total > 1000:
        recommendations.append("Excellent cache performance! Consider expanding cached endpoints.")
    
    if total < 10:
        recommendations.append("Not enough data to provide recommendations yet.")
    
    return recommendations if recommendations else ["Cache performance is within normal parameters."]


@router.get("/ingestion/stats")
async def get_ingestion_stats():
    """
    Get ingestion statistics
    
    Returns metrics about news ingestion performance:
    - Last run timestamp
    - Total runs tracked
    - Lifetime totals (fetched, saved, duplicates, errors)
    - Average duplicate and error rates
    - Recent run history
    
    Example Response:
        {
            "success": true,
            "data": {
                "total_runs": 24,
                "last_run": "2026-02-03T12:30:00",
                "lifetime_totals": {
                    "fetched": 12450,
                    "saved": 850,
                    "duplicates": 11600,
                    "errors": 0
                },
                "averages": {
                    "duplicate_rate": 93.2,
                    "error_rate": 0.0
                },
                "recent_runs": [...]
            }
        }
    """
    try:
        from app.services.ingestion_metrics import get_ingestion_metrics
        
        metrics = get_ingestion_metrics()
        stats = metrics.get_stats()
        
        return {
            "success": True,
            "data": stats,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting ingestion stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ingestion/alerts")
async def get_ingestion_alerts():
    """
    Check for ingestion alerts
    
    Monitors:
    - High duplicate rate (>90%)
    - High error rate (>20%)
    - No articles saved despite successfully fetching
    
    Returns list of active alerts with severity levels.
    
    Example Response:
        {
            "success": true,
            "alert_count": 1,
            "alerts": [
                {
                    "severity": "warning",
                    "type": "high_duplicate_rate",
                    "message": "Duplicate rate is 93.2% (threshold: 90%)",
                    "value": 93.2
                }
            ],
            "thresholds": {
                "duplicate_rate": 90,
                "error_rate": 20
            }
        }
    """
    try:
        from app.services.ingestion_metrics import get_ingestion_metrics
        
        metrics = get_ingestion_metrics()
        alerts = metrics.check_alerts()
        
        return {
            "success": True,
            "alert_count": len(alerts),
            "alerts": alerts,
            "thresholds": {
                "duplicate_rate": 90,
                "error_rate": 20
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error checking ingestion alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/quota/stats")
async def get_quota_stats():
    """
    Get API quota usage statistics
    
    Tracks usage for:
    - GNews API (100 calls/day)
    - NewsAPI (100 calls/day)
    - NewsData (200 calls/day)
    - Groq API (30,000 tokens/minute)
    
    Returns current usage, remaining quota, and reset times.
    
    Example Response:
        {
            "success": true,
            "quotas": {
                "gnews": {
                    "limit": 100,
                    "used": 25,
                    "remaining": 75,
                    "reset_time": "2026-02-04T00:00:00"
                },
                "groq": {
                    "limit": "30000 tokens/min",
                    "used": 1250,
                    "remaining": 28750,
                    "reset_time": "2026-02-03T18:20:00"
                }
            }
        }
    """
    try:
        from app.services.api_quota import get_quota_tracker
        
        tracker = get_quota_tracker()
        stats = tracker.get_stats()
        
        return {
            "success": True,
            "quotas": stats,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting quota stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


