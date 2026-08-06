"""Tweet watch — review-queue poller for DMK-defense / fact-check handles.

@saysatheesh (and a few similar accounts) post a steady stream of credit-steal
call-outs and data rebuttals. X has no free API and Apify costs money, so we
poll the public Nitter RSS for these handles, dedup by tweet id, and FLAG the
tweets whose text matches credit-steal / fact-check signals.

This is a REVIEW QUEUE, never an auto-publisher. Flagged rows land in
`tweet_watch` at status='new'. A human / in-session agent then does proper
background verification (web-research the claim, confirm the DMK-era origin)
exactly like the manual credit-steal adds, and only then promotes it to an
incident. Nothing here is shown publicly.

Caveat: Nitter instances are flaky — we try a list and log loudly if all fail.
"""
from __future__ import annotations

import logging
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Optional

from app.database import get_db

logger = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Tried in order until one returns items. nitter.net first (works as of writing).
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.poast.org",
    "https://lightbrd.com",
]

# Handles to watch. Keep tight — these are high-signal DMK-defense / fact accounts.
WATCHLIST = ["saysatheesh", "dstock_insights", "ImPrinze", "rajeshk41"]

# Credit-steal / fact-check signals (Tamil + English). Substring match, case-
# insensitive. Over-flagging is fine — a human reviews; missing one is worse.
_SIGNALS = [
    # credit-steal framing
    "சாதனை", "கடந்த ஆட்சி", "முந்தைய அரசு", "புதிய ஆட்சி", "முடிந்து", "முடிஞ்ச",
    "sticker", "ஸ்டிக்கர்", "திருட்", "credit", "கிரெடிட்", "முதல்முதலா", "முதன்முதலா",
    # DMK-scheme credit-steal / debunk signals (old scheme falsely claimed as new)
    "கலைஞர்", "தொடங்கப்பட்ட", "தொடங்கிய", "பொய்", "ஏற்கனவே", "கலைஞரின்",
    # fact-check framing
    "உண்மை", "வதந்தி", "தவறான", "தவறாக", "fake", "false", "fact", "debunk", "actually",
    # investment / MoU / infra
    "mou", "எம்.ஓ.யு", "கையெழுத்து", "முதலீ", "investment", "metro", "மெட்ரோ",
    "shipyard", "hyundai", "adani", "tender", "டெண்டர்",
    # fiscal rebuttals
    "கடன்", "debt", "gsdp", "வருவாய்", "deficit",
]


def _extract_id(link: str) -> Optional[str]:
    m = re.search(r"/status/(\d+)", link or "")
    return m.group(1) if m else None


def _fetch_rss(handle: str, timeout: int = 25) -> Optional[str]:
    for base in NITTER_INSTANCES:
        url = f"{base}/{handle}/rss"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", errors="replace")
            if "<item>" in body:
                return body
        except Exception as e:
            logger.warning("tweet_watch: %s failed for %s: %s", base, handle, e)
            continue
    logger.error("tweet_watch: ALL nitter instances failed for @%s", handle)
    return None


def _parse_items(handle: str, xml_text: str) -> list[dict]:
    out: list[dict] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        creator = (it.findtext("creator") or "").strip().lstrip("@")
        pub = (it.findtext("pubDate") or "").strip()
        tid = _extract_id(link)
        if not tid:
            continue
        is_rt = title.lower().startswith("rt by")
        # canonical url: prefer the author in the nitter link, else the handle
        m = re.search(r"/([^/]+)/status/", link)
        owner = (m.group(1) if m else handle)
        url = f"https://x.com/{owner}/status/{tid}"
        posted_iso = None
        try:
            posted_iso = parsedate_to_datetime(pub).astimezone(timezone.utc).isoformat()
        except Exception:
            pass
        out.append({
            "tweet_id": tid, "handle": handle, "author": creator or owner,
            "text": title, "url": url, "posted_at": posted_iso, "is_retweet": is_rt,
        })
    return out


def _flag(text: str) -> list[str]:
    low = (text or "").lower()
    return [s for s in _SIGNALS if s.lower() in low]


def poll_watchlist(handles: Optional[list[str]] = None) -> dict[str, int]:
    """Poll each watched handle's Nitter RSS, dedup by tweet id, insert new
    tweets, flagging credit-steal/fact candidates. Returns counts."""
    db = get_db()
    handles = handles or WATCHLIST
    counts = {"fetched": 0, "new": 0, "candidates": 0, "dup": 0, "failed_handles": 0}

    for handle in handles:
        xml_text = _fetch_rss(handle)
        if not xml_text:
            counts["failed_handles"] += 1
            continue
        items = _parse_items(handle, xml_text)
        counts["fetched"] += len(items)
        if not items:
            continue
        ids = [it["tweet_id"] for it in items]
        try:
            existing = (db.table("tweet_watch").select("tweet_id")
                        .in_("tweet_id", ids).execute().data or [])
            seen = {r["tweet_id"] for r in existing}
        except Exception as e:
            logger.error("tweet_watch dedup query failed: %s", e)
            seen = set()
        for it in items:
            if it["tweet_id"] in seen:
                counts["dup"] += 1
                continue
            kws = _flag(it["text"])
            row = {**it, "is_candidate": bool(kws), "matched_keywords": kws, "status": "new"}
            try:
                db.table("tweet_watch").insert(row).execute()
                counts["new"] += 1
                if kws:
                    counts["candidates"] += 1
            except Exception as e:
                logger.warning("tweet_watch insert failed for %s: %s", it["url"], e)

    logger.info("tweet_watch poll: %s", counts)
    return counts
