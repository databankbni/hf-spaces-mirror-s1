"""Telegram bot webhook endpoint.

Receives raw Telegram Update payloads, validates the request via the
secret token Telegram is configured to include, and processes them in
a background daemon thread. Always responds 200 in <50ms so Telegram
never times out and never retries.

Setup: see docs/telegram-bot-setup.md
"""
from __future__ import annotations
import asyncio
import collections
import logging
import threading
import time
from typing import Any, Optional
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])

# Ring buffer of (chat_id, username/title, timestamp) for the last
# webhook hits. Lets the admin self-discover their chat_id without
# disabling the webhook (Telegram forbids getUpdates+webhook together).
# Survives only until the next HF redeploy — but that's all you need.
_RECENT_CHATS: collections.deque = collections.deque(maxlen=50)

# Update_id dedup ring. Telegram retries the SAME update_id when our
# handler takes too long or returns a non-200. Tracking the last 500
# update_ids means a retry is silently dropped instead of duplicate-
# processing the same upload (which would create a 2nd incident row).
_SEEN_UPDATE_IDS: collections.deque = collections.deque(maxlen=500)
_SEEN_UPDATE_IDS_SET: set = set()


def _is_duplicate_update(update_id: Any) -> bool:
    if not update_id:
        return False
    if update_id in _SEEN_UPDATE_IDS_SET:
        return True
    _SEEN_UPDATE_IDS.append(update_id)
    _SEEN_UPDATE_IDS_SET.add(update_id)
    # Evict oldest if buffer wrapped
    while len(_SEEN_UPDATE_IDS_SET) > _SEEN_UPDATE_IDS.maxlen:
        old = _SEEN_UPDATE_IDS.popleft()
        _SEEN_UPDATE_IDS_SET.discard(old)
    return False


def _process_update_async(payload: dict) -> None:
    """Drive handle_update from a daemon thread. Owns its own event loop
    so we never collide with FastAPI's. Swallows all errors after logging
    — the user already got an ack; failures are debuggable via /recent-
    events."""
    try:
        from app.ingestion.telegram_bot import handle_update
        asyncio.run(handle_update(payload))
    except Exception as e:
        logger.error("Background handle_update failed: %s", e, exc_info=True)


@router.post("/telegram")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None),
):
    """Receives Telegram updates. Secured by the secret token Telegram
    is told to attach when setting the webhook (we reuse ADMIN_SECRET
    for this — Telegram only sends it back to us, never exposes it)."""
    if x_telegram_bot_api_secret_token != settings.admin_secret:
        # Don't leak which way it failed — just deny.
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Dedup: Telegram retries the same update_id when our handler is slow.
    # Without this, a slow-but-successful first attempt + a retry produces
    # TWO incident rows for one upload.
    update_id = payload.get("update_id")
    if _is_duplicate_update(update_id):
        return {"status": "duplicate", "update_id": update_id}

    # Record every chat that hits us — for the recent-chats diagnostic
    # endpoint. Useful so admin can self-discover their chat_id without
    # disabling the webhook (which would require Telegram getUpdates).
    msg = payload.get("message") or payload.get("channel_post") or {}
    chat = msg.get("chat") or {}
    cid = chat.get("id")
    if cid:
        _RECENT_CHATS.appendleft({
            "chat_id":    cid,
            "type":       chat.get("type"),
            "name":       chat.get("first_name") or chat.get("title"),
            "username":   chat.get("username"),
            "text_preview": (msg.get("text") or msg.get("caption") or "")[:60],
            "seen_at":    time.time(),
        })

    # Fire-and-forget: spawn a daemon thread to do the slow work (OCR,
    # vision LLM, Supabase writes — all blocking I/O) and return 200
    # IMMEDIATELY (<50ms). Telegram is satisfied → it won't retry, won't
    # consider us failed, won't double-process. The user sees the ack
    # message from inside handle_update, then the final result.
    #
    # daemon=True so threads don't block process shutdown on HF redeploys.
    # No queue/pool — Python's threading scales fine for our 1-30 msg/day
    # volume, and HF gives us ~2GB RAM so concurrent threads are cheap.
    t = threading.Thread(target=_process_update_async, args=(payload,), daemon=True)
    t.start()
    return {"status": "accepted", "update_id": update_id}


@router.get("/telegram/recent-events")
async def telegram_recent_events() -> dict[str, Any]:
    """Per-step diagnostic of the last ~50 Telegram processing attempts.
    Lets us debug 'no reply' failures remotely without HF log access."""
    from app.ingestion.telegram_bot import _RECENT_EVENTS
    now = time.time()
    out = []
    for entry in _RECENT_EVENTS:
        e = dict(entry)
        e["seconds_ago"] = round(now - e.pop("t"))
        out.append(e)
    return {"recent_events": out, "count": len(out)}


@router.get("/telegram/recent-chats")
async def telegram_recent_chats() -> dict[str, Any]:
    """List chat_ids that have hit the webhook recently. Used so the
    admin can self-discover the correct chat_id to put into the
    TELEGRAM_ALLOWED_CHAT_IDS env var.

    No auth — payload contains no secrets. Ring buffer survives only
    until next HF redeploy."""
    now = time.time()
    out = []
    for entry in _RECENT_CHATS:
        out.append({
            **entry,
            "seconds_ago": round(now - entry["seen_at"]),
        })
    return {"recent_chats": out, "count": len(out)}


@router.get("/telegram/health")
async def telegram_health() -> dict[str, Any]:
    """Quick health check — confirms the webhook router is reachable
    and the bot config is loaded."""
    return {
        "configured": bool(settings.telegram_bot_token),
        "allowed_chats_count": len(
            [c for c in (settings.telegram_allowed_chat_ids or "").split(",") if c.strip()]
        ),
        "ocr_configured": bool(settings.google_vision_api_key),
    }
