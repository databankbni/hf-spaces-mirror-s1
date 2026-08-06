"""
Analytics Service
Track and report sync performance metrics.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


class AnalyticsService:
    """
    Service for tracking sync performance metrics.
    Stores metrics in-memory (can be extended to use database).
    """
    
    def __init__(self):
        self._sync_events: List[Dict[str, Any]] = []
        self._max_events = 1000
        self._daily_stats: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"success": 0, "failed": 0, "retried": 0}
        )
    
    def record_sync_attempt(
        self,
        item_id: str,
        entity_type: str,
        operation: str,
        success: bool,
        duration_ms: Optional[float] = None,
        retry_count: int = 0,
        error: Optional[str] = None
    ) -> None:
        """Record a sync attempt"""
        event = {
            "item_id": item_id,
            "entity_type": entity_type,
            "operation": operation,
            "success": success,
            "duration_ms": duration_ms,
            "retry_count": retry_count,
            "error": error,
            "timestamp": datetime.now().isoformat()
        }
        
        self._sync_events.insert(0, event)
        
        # Trim old events
        if len(self._sync_events) > self._max_events:
            self._sync_events = self._sync_events[:self._max_events]
        
        # Update daily stats
        today = datetime.now().strftime("%Y-%m-%d")
        if success:
            self._daily_stats[today]["success"] += 1
        else:
            self._daily_stats[today]["failed"] += 1
        
        if retry_count > 0:
            self._daily_stats[today]["retried"] += 1
        
        logger.debug(f"Recorded sync event: {item_id} - {'success' if success else 'failed'}")
    
    def get_sync_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get sync statistics for the last N hours"""
        cutoff = datetime.now() - timedelta(hours=hours)
        recent_events = [
            e for e in self._sync_events
            if datetime.fromisoformat(e["timestamp"]) > cutoff
        ]
        
        if not recent_events:
            return {
                "period_hours": hours,
                "total_syncs": 0,
                "success_count": 0,
                "failed_count": 0,
                "success_rate": 0.0,
                "avg_duration_ms": 0,
                "retry_count": 0
            }
        
        success_count = len([e for e in recent_events if e["success"]])
        failed_count = len([e for e in recent_events if not e["success"]])
        total = len(recent_events)
        
        durations = [e["duration_ms"] for e in recent_events if e["duration_ms"] is not None]
        avg_duration = sum(durations) / len(durations) if durations else 0
        
        retry_count = sum(e["retry_count"] for e in recent_events)
        
        return {
            "period_hours": hours,
            "total_syncs": total,
            "success_count": success_count,
            "failed_count": failed_count,
            "success_rate": round(success_count / total * 100, 2) if total > 0 else 0,
            "avg_duration_ms": round(avg_duration, 2),
            "retry_count": retry_count
        }
    
    def get_daily_report(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get daily sync report for the last N days"""
        report = []
        today = datetime.now().date()
        
        for i in range(days):
            date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            stats = self._daily_stats.get(date, {"success": 0, "failed": 0, "retried": 0})
            total = stats["success"] + stats["failed"]
            
            report.append({
                "date": date,
                "total": total,
                "success": stats["success"],
                "failed": stats["failed"],
                "retried": stats["retried"],
                "success_rate": round(stats["success"] / total * 100, 2) if total > 0 else 0
            })
        
        return report
    
    def get_error_breakdown(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get breakdown of most common errors"""
        error_counts: Dict[str, int] = defaultdict(int)
        
        for event in self._sync_events:
            if not event["success"] and event["error"]:
                error_counts[event["error"]] += 1
        
        sorted_errors = sorted(
            error_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )[:limit]
        
        return [
            {"error": error, "count": count}
            for error, count in sorted_errors
        ]
    
    def get_entity_breakdown(self) -> Dict[str, Dict[str, int]]:
        """Get sync stats broken down by entity type"""
        breakdown: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"success": 0, "failed": 0}
        )
        
        for event in self._sync_events:
            entity = event["entity_type"]
            if event["success"]:
                breakdown[entity]["success"] += 1
            else:
                breakdown[entity]["failed"] += 1
        
        return dict(breakdown)
    
    def get_recent_events(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent sync events"""
        return self._sync_events[:limit]


# Singleton instance
analytics_service = AnalyticsService()
