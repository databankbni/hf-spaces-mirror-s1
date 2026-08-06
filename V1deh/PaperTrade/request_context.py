"""
request_context.py - Request-scoped tracking for predictions.

Tracks a single prediction request: timing, data sources, merges, validation.
Used to diagnose why predictions succeed or timeout.
"""

import uuid
import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class RequestContext:
    """Tracks a single prediction request: timing, data sources, merges."""

    def __init__(self, ticker: str = ""):
        self.request_id = str(uuid.uuid4())[:8]
        self.ticker = ticker
        self.start_time = time.time()
        self.merge_log = []
        self.validation_log = []

    def elapsed(self) -> float:
        """Seconds elapsed since request start."""
        return time.time() - self.start_time

    def log_data_merge(self, source: str, data_rows: int, live_price: float):
        """Log a data merge (cached OHLCV + live price)."""
        self.merge_log.append({
            "source": source,
            "rows": data_rows,
            "live_price": live_price,
            "timestamp": time.time()
        })
        logger.info(f"[{self.request_id}] Merged {data_rows} cached rows with live price ₹{live_price:.2f}")

    def log_validation(self, cached_ticker: str, expected_ticker: str, is_match: bool):
        """Log ticker validation before merge."""
        self.validation_log.append({
            "cached": cached_ticker,
            "expected": expected_ticker,
            "match": is_match
        })
        status = "✓" if is_match else "✗"
        logger.info(f"[{self.request_id}] {status} Data validation: {cached_ticker} vs {expected_ticker}")

    def get_merge_report(self) -> dict:
        """Return merge details for API response."""
        return {
            "request_id": self.request_id,
            "merges": len(self.merge_log),
            "validations": self.validation_log,
            "elapsed_ms": int(self.elapsed() * 1000),
        }
