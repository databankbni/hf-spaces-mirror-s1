"""Reusable security middleware for the HELITEB agent FastAPI app.

All middleware is stdlib-only (no external dependencies) and designed for
async FastAPI / Starlette (BaseHTTPMiddleware). Thread/loop safety is
provided by ``asyncio.Lock`` because each request runs in its own task
sharing the same event loop.

Classes:
    SecurityHeadersMiddleware  - Injects defensive HTTP response headers.
    RateLimitMiddleware        - In-memory IP-based sliding-window limiter.
    register_exception_handlers(app) - Wires user-friendly error responses.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from time import time
from typing import Deque, Dict, Iterable, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger("heliteb.middleware")


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach defensive HTTP headers to every response.

    Headers:
        X-Content-Type-Options: nosniff
        X-Frame-Options: DENY
        X-XSS-Protection: 1; mode=block
        Strict-Transport-Security: max-age=31536000; includeSubDomains
        Referrer-Policy: no-referrer
        Cache-Control: no-store (only for /agent/query)
    """

    DEFAULT_HEADERS: Dict[str, str] = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "Referrer-Policy": "no-referrer",
    }

    def __init__(
        self,
        app,
        *,
        no_store_paths: Optional[Iterable[str]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(app)
        self._no_store_paths = tuple(no_store_paths or ())
        self._extra_headers = dict(extra_headers or {})

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for name, value in self.DEFAULT_HEADERS.items():
            response.headers.setdefault(name, value)
        for name, value in self._extra_headers.items():
            response.headers.setdefault(name, value)
        if request.url.path in self._no_store_paths:
            # Sensitive endpoint: never cache, anywhere.
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        return response


# ---------------------------------------------------------------------------
# Rate limiting (sliding window, in-memory, per IP)
# ---------------------------------------------------------------------------
class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory sliding-window rate limiter keyed by client IP.

    Args:
        max_requests: Maximum requests allowed inside ``window_seconds``.
        window_seconds: Sliding window length in seconds.
        exempt_paths: Paths that bypass the limiter (e.g. ``/health``).

    Notes:
        Suitable for a single-instance deployment. For multi-instance
        deployments, swap for a Redis-backed limiter.
    """

    def __init__(
        self,
        app,
        *,
        max_requests: int = 30,
        window_seconds: int = 60,
        exempt_paths: Optional[Iterable[str]] = None,
    ) -> None:
        super().__init__(app)
        self._max = max_requests
        self._window = float(window_seconds)
        self._exempt = tuple(exempt_paths or ("/health",))
        # IP -> deque[float] of request timestamps.
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    def _client_ip(self, request: Request) -> str:
        # Honour X-Forwarded-For from Fly.io's TLS terminator; fall back to
        # the direct client. We take the leftmost address, which is the
        # original client.
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
        if request.client is not None:
            return request.client.host
        return "unknown"

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in self._exempt:
            return await call_next(request)
        # CORS preflights are not billable traffic — every browser POST
        # triggers one, so counting them would halve the effective limit.
        if request.method == "OPTIONS":
            return await call_next(request)

        ip = self._client_ip(request)
        now = time()
        cutoff = now - self._window

        async with self._lock:
            bucket = self._hits[ip]
            # Drop expired timestamps from the left.
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self._max:
                # Rate limit exceeded. Compute Retry-After.
                oldest = bucket[0]
                retry_after = max(1, int(self._window - (now - oldest)) + 1)
                logger.warning(
                    "rate_limit_exceeded ip=%s path=%s retry_after=%s",
                    ip, request.url.path, retry_after,
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Too many requests. Please try again later.",
                    },
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.append(now)

        return await call_next(request)


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------
def _client_message(exc: Exception) -> str:
    """Return a safe, user-facing message for a given exception."""
    return "An internal error occurred. Please try again shortly."


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle ``HTTPException`` without leaking server internals.

    - 4xx (client errors, including FastAPI's 422 validation errors):
      pass ``detail`` through unchanged — these are user-safe.
    - 5xx (server errors): log the original detail server-side and
      return a generic message to the client.
    """
    from fastapi import HTTPException

    if isinstance(exc, HTTPException):
        status = exc.status_code
        if status >= 500:
            logger.error(
                "http_exception_5xx path=%s status=%s detail=%r",
                request.url.path, status, exc.detail,
            )
            return JSONResponse(
                status_code=status,
                content={"detail": _client_message(exc)},
            )
        # Client errors: pass detail through (dict/list/str all allowed).
        return JSONResponse(status_code=status, content={"detail": exc.detail})

    logger.exception("unhandled_http_exception path=%s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": _client_message(exc)},
    )


async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Catch-all for any exception not converted to ``HTTPException``."""
    logger.exception(
        "unhandled_exception path=%s method=%s",
        request.url.path, request.method,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": _client_message(exc)},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register the package's exception handlers on ``app``."""
    from fastapi.exceptions import HTTPException as _HTTPException

    # Overrides FastAPI's default HTTPException handler so that any
    # raised HTTPException with detail=str(internal_error) does not
    # leak server internals to clients.
    app.add_exception_handler(_HTTPException, http_exception_handler)
    # Catch-all for any unhandled exception.
    app.add_exception_handler(Exception, unhandled_exception_handler)
