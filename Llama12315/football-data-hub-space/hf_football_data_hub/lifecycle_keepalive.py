"""hf_football_data_hub — lifecycle keepalive module.

Lightweight in-memory heartbeat. Runs only while Space is awake.
Cannot wake a sleeping Space — that is the Hermes-side Wakeup Gate's job.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any


KEEPALIVE_STATE: dict[str, Any] = {
    "started_at": None,
    "last_heartbeat_at": None,
    "last_warmup_at": None,
    "heartbeat_count": 0,
    "last_status": "init",
    "last_error": "",
}

_START_TIME: float | None = None


async def lightweight_heartbeat_loop(interval: int = 600):
    """In-memory heartbeat — no external calls, no model calls, no analysis.

    Runs every `interval` seconds (default 600 = 10 min).
    Only functions while this Space process is alive.
    """
    global _START_TIME
    _START_TIME = time.time()
    KEEPALIVE_STATE["started_at"] = time.time()

    while True:
        try:
            KEEPALIVE_STATE["last_heartbeat_at"] = time.time()
            KEEPALIVE_STATE["heartbeat_count"] += 1
            KEEPALIVE_STATE["last_status"] = "ok"
        except Exception as exc:
            KEEPALIVE_STATE["last_status"] = "error"
            KEEPALIVE_STATE["last_error"] = str(exc)[:200]

        await asyncio.sleep(interval)


def mark_warmup():
    KEEPALIVE_STATE["last_warmup_at"] = time.time()


def get_keepalive_state(packet_version: str, active_phase: str) -> dict:
    now = time.time()
    return {
        "ok": True,
        "started_at": KEEPALIVE_STATE.get("started_at"),
        "last_heartbeat_at": KEEPALIVE_STATE.get("last_heartbeat_at"),
        "last_warmup_at": KEEPALIVE_STATE.get("last_warmup_at"),
        "uptime_seconds": round(now - _START_TIME, 1) if _START_TIME else 0,
        "heartbeat_count": KEEPALIVE_STATE["heartbeat_count"],
        "last_status": KEEPALIVE_STATE["last_status"],
        "last_error": KEEPALIVE_STATE["last_error"],
        "active_phase": active_phase,
        "packet_version": packet_version,
        "note": "internal_keepalive_cannot_wake_space_after_sleep",
    }
