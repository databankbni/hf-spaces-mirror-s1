"""FastAPI middleware: per-IP rate limiting and request logging."""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

_EXEMPT_PATHS = {"/", "/health", "/metrics", "/docs", "/openapi.json", "/redoc"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window per-IP rate limit to protect the free Groq API quota."""

    def __init__(self, app, requests_per_minute: int = 20) -> None:
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.window_seconds = 60.0
        self._lock = Lock()
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        with self._lock:
            window = self._requests[client_ip]
            while window and now - window[0] > self.window_seconds:
                window.popleft()

            if len(window) >= self.requests_per_minute:
                retry_after = int(self.window_seconds - (now - window[0])) + 1
                logger.warning("Rate limit hit for %s on %s.", client_ip, request.url.path)
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": (
                            "You are sending messages too quickly. "
                            f"Please wait about {retry_after} seconds and try again."
                        )
                    },
                    headers={"Retry-After": str(retry_after)},
                )

            window.append(now)

            # Keep the map bounded: drop IPs whose windows are empty.
            if len(self._requests) > 10_000:
                for ip in [ip for ip, q in self._requests.items() if not q]:
                    del self._requests[ip]

        started_at = time.perf_counter()
        response = await call_next(request)
        logger.info(
            "%s %s -> %d (%.3fs)",
            request.method,
            request.url.path,
            response.status_code,
            time.perf_counter() - started_at,
        )
        return response
