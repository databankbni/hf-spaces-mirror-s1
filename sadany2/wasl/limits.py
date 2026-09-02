"""
Abuse guards for a public, free-tier inference endpoint.

Three separate concerns, because they fail differently:

  rate       stops one client making thousands of calls
  concurrency stops any number of clients saturating 2 vCPUs at once
  size       stops a single 400MB upload exhausting memory before we even decode

Deliberately dependency-free and in-memory. That means limits reset when the
Space restarts and are per-container — fine for a pilot, wrong for real scale,
where this belongs in Redis or at the edge.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict, deque

PER_MIN = int(os.environ.get("RATE_PER_MIN", "20"))
PER_HOUR = int(os.environ.get("RATE_PER_HOUR", "200"))
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "2"))
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(8 * 1024 * 1024)))
QUEUE_TIMEOUT = float(os.environ.get("QUEUE_TIMEOUT", "25"))

EXEMPT_PATHS = {"/health", "/", "/favicon.ico"}

_minute: dict[str, deque] = defaultdict(deque)
_hour: dict[str, deque] = defaultdict(deque)
# Keyed by event loop, not created at import. A Semaphore built at import time
# binds to whichever loop exists then (or none), and on Python <3.10 that raises
# "attached to a different loop" the first time a real request touches it under
# uvicorn. Keying by the running loop also survives a loop being replaced.
_gates: "dict[object, asyncio.Semaphore]" = {}


def _gate_for_loop() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    gate = _gates.get(loop)
    if gate is None:
        gate = asyncio.Semaphore(MAX_CONCURRENT)
        _gates[loop] = gate
        if len(_gates) > 4:                       # never expected; guard anyway
            for dead in [k for k in _gates if getattr(k, "is_closed", lambda: False)()]:
                _gates.pop(dead, None)
    return gate


_stats = {"served": 0, "rate_limited": 0, "too_large": 0, "queue_timeout": 0}


def client_ip(request) -> str:
    """Spaces sits behind a proxy, so the socket address is always the proxy."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return getattr(request.client, "host", "unknown") or "unknown"


def _trim(dq: deque, window: float, now: float) -> None:
    while dq and now - dq[0] > window:
        dq.popleft()


def check_rate(ip: str) -> tuple[bool, int, str]:
    """(allowed, retry_after_seconds, reason)"""
    now = time.time()
    m, h = _minute[ip], _hour[ip]
    _trim(m, 60, now)
    _trim(h, 3600, now)

    if len(m) >= PER_MIN:
        return False, max(1, int(60 - (now - m[0]))), f"{PER_MIN}/minute"
    if len(h) >= PER_HOUR:
        return False, max(1, int(3600 - (now - h[0]))), f"{PER_HOUR}/hour"

    m.append(now)
    h.append(now)
    return True, 0, ""


def forget_stale(max_ips: int = 5000) -> None:
    """Keep the tables from growing without bound on a long-lived container."""
    if len(_minute) <= max_ips:
        return
    now = time.time()
    for table, window in ((_minute, 60), (_hour, 3600)):
        for ip in [k for k, v in table.items() if not v or now - v[-1] > window]:
            table.pop(ip, None)


class Gate:
    """Bound concurrent inference. Queue briefly, then shed rather than pile up."""

    async def __aenter__(self):
        gate = _gate_for_loop()
        try:
            await asyncio.wait_for(gate.acquire(), timeout=QUEUE_TIMEOUT)
        except asyncio.TimeoutError:
            _stats["queue_timeout"] += 1
            raise
        return self

    async def __aexit__(self, *exc):
        _gate_for_loop().release()
        return False


def stats() -> dict:
    return {
        **_stats,
        "tracked_ips": len(_minute),
        "in_flight": sum(MAX_CONCURRENT - g._value for g in _gates.values()),
        "limits": {
            "per_minute": PER_MIN,
            "per_hour": PER_HOUR,
            "max_concurrent": MAX_CONCURRENT,
            "max_upload_mb": round(MAX_UPLOAD_BYTES / 1048576, 1),
        },
    }


def note(key: str) -> None:
    _stats[key] = _stats.get(key, 0) + 1
