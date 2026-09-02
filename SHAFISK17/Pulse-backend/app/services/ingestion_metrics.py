"""
Ingestion Statistics Tracking
Monitors ingestion performance, duplicate rates, and error rates over time
"""

from datetime import datetime
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class IngestionMetrics:
    """Track ingestion metrics over time"""
    
    def __init__(self):
        self.runs: List[Dict] = []
        self.total_fetched = 0
        self.total_saved = 0
        self.total_duplicates = 0
        self.total_errors = 0
        self.total_irrelevant = 0
        self.last_run_timestamp: Optional[datetime] = None
    
    def record_run(
        self,
        fetched: int,
        saved: int,
        duplicates: int,
        errors: int,
        categories_processed: int,
        irrelevant: int = 0
    ):
        """Record metrics from an ingestion run"""
        duplicate_rate = (duplicates / fetched * 100) if fetched > 0 else 0
        error_rate = (errors / fetched * 100) if fetched > 0 else 0
        irrelevant_rate_approx = (irrelevant / fetched * 100) if fetched > 0 else 0
        
        run_data = {
            "timestamp": datetime.now().isoformat(),
            "fetched": fetched,
            "saved": saved,
            "duplicates": duplicates,
            "errors": errors,
            "duplicate_rate": round(duplicate_rate, 2),
            "error_rate": round(error_rate, 2),
            "categories_processed": categories_processed,
            "irrelevant_count": irrelevant,
            "irrelevant_rate_approx": round(irrelevant_rate_approx, 2)
        }
        
        self.runs.append(run_data)
        
        # Keep only last 100 runs
        if len(self.runs) > 100:
            self.runs = self.runs[-100:]
        
        # Update totals
        self.total_fetched += fetched
        self.total_saved += saved
        self.total_duplicates += duplicates
        self.total_errors += errors
        self.total_irrelevant += irrelevant
        self.last_run_timestamp = datetime.now()
        
        logger.info(f"📊 Ingestion run recorded: {saved}/{fetched} saved ({duplicate_rate:.1f}% duplicates)")
    
    def get_stats(self) -> Dict:
        """Get current ingestion statistics"""
        avg_duplicate_rate = 0.0
        avg_error_rate = 0.0
        avg_irrelevant_rate_approx = 0.0
        
        if len(self.runs) > 0:
            avg_duplicate_rate = sum(r["duplicate_rate"] for r in self.runs) / len(self.runs)
            avg_error_rate = sum(r["error_rate"] for r in self.runs) / len(self.runs)
            avg_irrelevant_rate_approx = sum(r.get("irrelevant_rate_approx", 0) for r in self.runs) / len(self.runs)
        
        return {
            "total_runs": len(self.runs),
            "last_run": self.last_run_timestamp.isoformat() if self.last_run_timestamp else None,
            "lifetime_totals": {
                "fetched": self.total_fetched,
                "saved": self.total_saved,
                "duplicates": self.total_duplicates,
                "errors": self.total_errors,
                "irrelevant_count": self.total_irrelevant
            },
            "averages": {
                "duplicate_rate": round(avg_duplicate_rate, 2),
                "error_rate": round(avg_error_rate, 2),
                "avg_irrelevant_rate_approx": round(avg_irrelevant_rate_approx, 2)
            },
            "recent_runs": self.runs[-10:]  # Last 10 runs
        }
    
    def check_alerts(self) -> List[Dict]:
        """Check if any metrics exceed thresholds"""
        alerts = []
        
        if len(self.runs) == 0:
            return alerts
        
        latest_run = self.runs[-1]
        
        # Alert on high duplicate rate (>90%)
        if latest_run["duplicate_rate"] > 90:
            alerts.append({
                "severity": "warning",
                "type": "high_duplicate_rate",
                "message": f"Duplicate rate is {latest_run['duplicate_rate']}% (threshold: 90%)",
                "value": latest_run["duplicate_rate"]
            })
        
        # Alert on high error rate (>20%)
        if latest_run["error_rate"] > 20:
            alerts.append({
                "severity": "error",
                "type": "high_error_rate",
                "message": f"Error rate is {latest_run['error_rate']}% (threshold: 20%)",
                "value": latest_run["error_rate"]
            })
        
        # Alert on no articles saved
        if latest_run["saved"] == 0 and latest_run["fetched"] > 0:
            alerts.append({
                "severity": "critical",
                "type": "no_articles_saved",
                "message": f"No articles saved despite {latest_run['fetched']} fetched",
                "value": 0
            })
        
        return alerts


# Global singleton
_ingestion_metrics: Optional[IngestionMetrics] = None


def get_ingestion_metrics() -> IngestionMetrics:
    """Get or create global ingestion metrics instance"""
    global _ingestion_metrics
    
    if _ingestion_metrics is None:
        _ingestion_metrics = IngestionMetrics()
    
    return _ingestion_metrics
