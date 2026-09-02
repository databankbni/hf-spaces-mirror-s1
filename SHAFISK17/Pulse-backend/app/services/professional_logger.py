"""
Professional Logging Module for Segmento Pulse
Provides structured logging with statistics tracking for:
- Schedulers & Background Jobs
- Space A ↔ B Interactions  
- Article Pipeline Statistics
- Rate Limiting & API Health
- Cleanup & Deduplication
"""

import logging
from datetime import datetime
from typing import Dict, Optional
from collections import defaultdict

# Statistics tracker
class IngestionStats:
    """Track ingestion pipeline statistics"""
    
    def __init__(self):
        self.reset()
    
    def reset(self):
        """Reset all counters"""
        self.articles_fetched = 0
        self.articles_saved = 0
        self.duplicates_found = 0
        self.articles_deleted = 0
        self.space_b_calls = 0
        self.space_b_successes = 0
        self.space_b_failures = 0
        self.space_b_timeouts = 0
        self.chromadb_upserts = 0
        self.rate_limits_hit = 0
        self.start_time = datetime.now()
    
    def get_summary(self) -> Dict:
        """Get formatted statistics summary"""
        duration = (datetime.now() - self.start_time).total_seconds()
        
        return {
            "duration_seconds": round(duration, 2),
            "articles_fetched": self.articles_fetched,
            "articles_saved": self.articles_saved,
            "duplicates_found": self.duplicates_found,
            "articles_deleted": self.articles_deleted,
            "deduplication_rate": f"{(self.duplicates_found / max(self.articles_fetched, 1)) * 100:.1f}%",
            "space_b": {
                "total_calls": self.space_b_calls,
                "successes": self.space_b_successes,
                "failures": self.space_b_failures,
                "timeouts": self.space_b_timeouts,
                "success_rate": f"{(self.space_b_successes / max(self.space_b_calls, 1)) * 100:.1f}%"
            },
            "chromadb_upserts": self.chromadb_upserts,
            "rate_limits_hit": self.rate_limits_hit,
            "throughput_per_second": round(self.articles_fetched / max(duration, 1), 2)
        }

# Global stats instance
ingestion_stats = IngestionStats()


class ProfessionalLogger:
    """Enhanced logger with formatted output"""
    
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
    
    def header(self, title: str, width: int = 80):
        """Log a section header"""
        self.logger.info("=" * width)
        self.logger.info(f"🎯 {title}")
        self.logger.info("=" * width)
    
    def section(self, title: str):
        """Log a subsection"""
        self.logger.info(f"\n📂 {title}")
        self.logger.info("-" * 60)
    
    def metric(self, label: str, value, icon: str = "📊"):
        """Log a metric"""
        self.logger.info(f"   {icon} {label}: {value}")
    
    def success(self, message: str):
        """Log a success"""
        self.logger.info(f"✅ {message}")
    
    def warning(self, message: str):
        """Log a warning"""
        self.logger.warning(f"⚠️  {message}")
    
    def error(self, message: str):
        """Log an error"""
        self.logger.error(f"❌ {message}")
    
    def space_b_call(self, url: str, status: str = "started"):
        """Log Space B interaction"""
        if status == "started":
            self.logger.info(f"🏭 [SPACE A→B] Calling: {url[:60]}...")
            ingestion_stats.space_b_calls += 1
        elif status == "success":
            self.logger.info(f"✅ [SPACE A←B] Response received")
            ingestion_stats.space_b_successes += 1
        elif status == "timeout":
            self.logger.warning(f"⏳ [SPACE A←B] Timeout (cold start?)")
            ingestion_stats.space_b_timeouts += 1
        elif status == "failure":
            self.logger.error(f"❌ [SPACE A←B] Request failed")
            ingestion_stats.space_b_failures += 1
    
    def scheduler_event(self, job_name: str, status: str):
        """Log scheduler activity"""
        if status == "started":
            self.logger.info(f"⏰ [SCHEDULER] Job '{job_name}' started")
        elif status == "completed":
            self.logger.info(f"✅ [SCHEDULER] Job '{job_name}' completed")
        elif status == "failed":
            self.logger.error(f"❌ [SCHEDULER] Job '{job_name}' failed")
    
    def cleaner_event(self, action: str, count: int):
        """Log cleanup actions"""
        self.logger.info(f"🧹 [CLEANER] {action}: {count} items")
        if "deleted" in action.lower():
            ingestion_stats.articles_deleted += count
    
    def print_stats(self):
        """Print comprehensive statistics summary"""
        stats = ingestion_stats.get_summary()
        
        self.header("INGESTION PIPELINE STATISTICS")
        
        self.section("Article Processing")
        self.metric("Total Fetched", stats["articles_fetched"], "📥")
        self.metric("Successfully Saved", stats["articles_saved"], "💾")
        self.metric("Duplicates Detected", stats["duplicates_found"], "🔍")
        self.metric("Articles Deleted", stats["articles_deleted"], "🗑️")
        self.metric("Deduplication Rate", stats["deduplication_rate"], "📊")
        
        self.section("Space A ↔ Space B Interaction")
        self.metric("Total API Calls", stats["space_b"]["total_calls"], "🏭")
        self.metric("Successes", stats["space_b"]["successes"], "✅")
        self.metric("Failures", stats["space_b"]["failures"], "❌")
        self.metric("Timeouts", stats["space_b"]["timeouts"], "⏳")
        self.metric("Success Rate", stats["space_b"]["success_rate"], "📈")
        
        self.section("Database & Storage")
        self.metric("ChromaDB Upserts", stats["chromadb_upserts"], "🧠")
        self.metric("Rate Limits Hit", stats["rate_limits_hit"], "🚦")
        
        self.section("Performance")
        self.metric("Duration", f"{stats['duration_seconds']}s", "⏱️")
        self.metric("Throughput", f"{stats['throughput_per_second']} articles/sec", "⚡")
        
        self.logger.info("=" * 80)


# Helper to get professional logger
def get_professional_logger(name: str) -> ProfessionalLogger:
    """Get a professional logger instance"""
    return ProfessionalLogger(name)
