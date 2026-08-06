#!/usr/bin/env python3
"""Shared titan007 transport: direct egress first, read-only relay fallback.

Direct egress from this host to vip.titan007.com (61.143.225.88) is blocked on
every probed port, while the same public URL is served normally from
third-party vantage points.  Every titan007 collector therefore needs the same
two-stage transport:

1. Try direct egress with a short timeout and a per-host circuit breaker, so a
   network-level block does not burn attempts x timeout on every URL.
2. Fall back to a read-only HTTP relay that fetches the *public* URL.

Only public odds/analysis URLs are relayed.  No local packet, ledger,
credential or user data is transmitted.  When direct egress recovers the
breaker re-probes and direct wins again.
"""
from __future__ import annotations

import os
import time
import urllib.parse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

RELAY_TEMPLATES = [
    t.strip()
    for t in (os.getenv("TITAN007_RELAYS") or "https://api.allorigins.win/raw?url={q}").split(",")
    if t.strip()
]
RELAY_MIN_BYTES = int(os.getenv("TITAN007_RELAY_MIN_BYTES") or 600)
DIRECT_FAIL_THRESHOLD = int(os.getenv("TITAN007_DIRECT_FAIL_THRESHOLD") or 2)
DIRECT_PROBE_INTERVAL = int(os.getenv("TITAN007_DIRECT_PROBE_INTERVAL") or 300)
DIRECT_TIMEOUT = int(os.getenv("TITAN007_DIRECT_TIMEOUT") or 8)
RELAY_ATTEMPTS = int(os.getenv("TITAN007_RELAY_ATTEMPTS") or 7)
RELAY_BACKOFF = float(os.getenv("TITAN007_RELAY_BACKOFF") or 1.2)

LAST_TRANSPORT = {"mode": "direct", "relay": None}
_DIRECT_STATE = {}


def host_of(url: str) -> str:
    try:
        return urllib.parse.urlsplit(url).netloc.lower()
    except ValueError:
        return ""


def direct_allowed(host: str) -> bool:
    state = _DIRECT_STATE.get(host)
    if not state:
        return True
    if state["fails"] < DIRECT_FAIL_THRESHOLD:
        return True
    return (time.time() - state["blocked_at"]) >= DIRECT_PROBE_INTERVAL


def direct_note(host: str, ok: bool) -> None:
    state = _DIRECT_STATE.setdefault(host, {"fails": 0.0, "blocked_at": 0.0})
    if ok:
        state["fails"] = 0.0
        state["blocked_at"] = 0.0
        return
    state["fails"] += 1
    if state["fails"] >= DIRECT_FAIL_THRESHOLD:
        state["blocked_at"] = time.time()


def _read(url: str, headers: dict, timeout: int) -> bytes:
    with urlopen(Request(url, headers=headers), timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError("HTTP_%s" % response.status)
        return response.read()


def fetch_via_relay(url: str, headers: dict, timeout: int):
    quoted = urllib.parse.quote(url, safe="")
    last = None
    for template in RELAY_TEMPLATES:
        relay = template.replace("{q}", quoted)
        try:
            body = _read(relay, headers, timeout)
            if len(body) < RELAY_MIN_BYTES:
                raise RuntimeError("RELAY_SHORT_%d" % len(body))
            return body, relay
        except (HTTPError, URLError, TimeoutError, RuntimeError, OSError) as exc:
            last = exc
    raise RuntimeError("RELAY_FAILED:%s:%s" % (type(last).__name__, last))


def fetch(url: str, headers: dict, *, timeout: int = 20, attempts: int = 3, allow_relay: bool = True):
    """Fetch url directly, then through a relay. Returns (body, attempt_count)."""
    last = None
    host = host_of(url)
    relay_enabled = allow_relay and bool(RELAY_TEMPLATES) and "titan007.com" in url
    direct_timeout = min(timeout, DIRECT_TIMEOUT) if relay_enabled else timeout

    if direct_allowed(host):
        for attempt in range(1, attempts + 1):
            try:
                body = _read(url, headers, direct_timeout)
                direct_note(host, True)
                LAST_TRANSPORT.update({"mode": "direct", "relay": None})
                return body, attempt
            except (HTTPError, URLError, TimeoutError, RuntimeError, OSError) as exc:
                last = exc
                direct_note(host, False)
                if not direct_allowed(host):
                    break
                if attempt < attempts:
                    time.sleep(0.35 * attempt)
    else:
        last = RuntimeError("DIRECT_EGRESS_CIRCUIT_OPEN")

    if relay_enabled:
        for relay_attempt in range(1, RELAY_ATTEMPTS + 1):
            try:
                body, relay = fetch_via_relay(url, headers, timeout)
                LAST_TRANSPORT.update({"mode": "relay", "relay": relay})
                return body, attempts + relay_attempt
            except RuntimeError as exc:
                last = exc
                if relay_attempt < RELAY_ATTEMPTS:
                    time.sleep(RELAY_BACKOFF * relay_attempt)

    raise RuntimeError("%s:%s" % (type(last).__name__, last))
