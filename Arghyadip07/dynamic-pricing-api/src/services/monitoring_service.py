from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import threading


@dataclass
class RequestMetric:
    timestamp: datetime
    method: str
    path: str
    status_code: int
    latency_ms: float


class MonitoringService:
    """In-memory request/error monitoring for near real-time dashboards."""

    def __init__(self, max_events: int = 10000):
        self._events: deque[RequestMetric] = deque(maxlen=max_events)
        self._lock = threading.Lock()

    def record(self, method: str, path: str, status_code: int, latency_ms: float) -> None:
        event = RequestMetric(
            timestamp=datetime.now(timezone.utc),
            method=method,
            path=path,
            status_code=int(status_code),
            latency_ms=float(latency_ms),
        )
        with self._lock:
            self._events.append(event)

    def error_rate_report(self, window_seconds: int = 300, bucket_seconds: int = 60) -> dict:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=window_seconds)

        with self._lock:
            events = [event for event in self._events if event.timestamp >= cutoff]

        total_requests = len(events)
        total_errors = sum(1 for event in events if event.status_code >= 400)
        error_rate_percent = (total_errors / total_requests * 100.0) if total_requests else 0.0

        bucket_count = max(1, math.ceil(window_seconds / max(bucket_seconds, 1)))
        series = []
        for idx in range(bucket_count):
            start = cutoff + timedelta(seconds=idx * bucket_seconds)
            end = start + timedelta(seconds=bucket_seconds)
            bucket_events = [event for event in events if start <= event.timestamp < end]
            bucket_requests = len(bucket_events)
            bucket_errors = sum(1 for event in bucket_events if event.status_code >= 400)
            bucket_rate = (bucket_errors / bucket_requests * 100.0) if bucket_requests else 0.0
            series.append(
                {
                    "bucket_start": start.isoformat(),
                    "requests": bucket_requests,
                    "errors": bucket_errors,
                    "error_rate_percent": round(bucket_rate, 2),
                }
            )

        endpoint_stats: dict[str, dict[str, int]] = {}
        for event in events:
            endpoint_stats.setdefault(event.path, {"requests": 0, "errors": 0})
            endpoint_stats[event.path]["requests"] += 1
            if event.status_code >= 400:
                endpoint_stats[event.path]["errors"] += 1

        endpoints = []
        for path, stats in endpoint_stats.items():
            req = stats["requests"]
            err = stats["errors"]
            endpoints.append(
                {
                    "path": path,
                    "requests": req,
                    "errors": err,
                    "error_rate_percent": round((err / req * 100.0) if req else 0.0, 2),
                }
            )
        endpoints.sort(key=lambda item: item["requests"], reverse=True)

        avg_latency_ms = (
            sum(event.latency_ms for event in events) / total_requests
            if total_requests
            else 0.0
        )

        return {
            "window_seconds": int(window_seconds),
            "total_requests": total_requests,
            "total_errors": total_errors,
            "error_rate_percent": round(error_rate_percent, 2),
            "average_latency_ms": round(avg_latency_ms, 2),
            "series": series,
            "endpoints": endpoints[:10],
        }
