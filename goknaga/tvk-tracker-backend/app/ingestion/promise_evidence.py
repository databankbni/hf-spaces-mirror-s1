"""Promise evidence sweep — proactively hunt delivery evidence per promise.

Why: the Promise Comparator is REACTIVE (it matches incoming articles to
promises), and after 32 days the result was 392/395 promises sitting at
'pending' with only 6 evidence URLs. Most promises genuinely ARE pending
this early, but nobody is *looking* for the delivery signals either.

This module is PROACTIVE: for each high-salience promise it searches
Google News directly for delivery-shaped coverage, AI-judges the hits
with the same delivery-only discipline as the comparator, and:

  - attaches an evidence_url (always, when confident — even if status
    doesn't change, the receipt is now on the card)
  - upgrades pending -> partial ONLY on a confident delivery signal
  - NEVER auto-marks 'kept' (that stays a human/admin decision)
  - NEVER auto-marks 'broken' (that's the deadline-pass job's domain,
    which has its own deadline guard)

Cost: one GNews RSS fetch + one cheap LLM call per promise with hits.
Run weekly over the top ~50; the full 395 would burn quota for promises
nobody is asking about yet.
"""
from __future__ import annotations
import json
import logging
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional

from app.database import get_db

logger = logging.getLogger(__name__)

GNEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
UA = "Mozilla/5.0 (compatible; TVKTracker-PromiseEvidence/1.0)"
# The govt took office on this date — evidence of IT delivering must post-date it.
GOVT_START = "2026-05-11"

# Words that carry no search signal in promise text.
_STOPWORDS = {
    "the", "a", "an", "of", "for", "in", "on", "at", "to", "and", "or",
    "with", "within", "all", "every", "per", "by", "from", "into", "via",
    "first", "year", "years", "months", "days", "new", "free", "up",
    "through", "starting", "begin", "began", "complete", "ensure",
}


def _promise_query(text: str) -> str:
    """Distill a promise into a GNews query: the ~6 most specific words
    + 'Tamil Nadu'. Numbers and proper-ish nouns carry the most signal."""
    words = re.findall(r"[A-Za-z0-9₹]+", text)
    keep: list[str] = []
    for w in words:
        if w.lower() in _STOPWORDS or len(w) < 3 and not w.isdigit():
            continue
        keep.append(w)
        if len(keep) >= 6:
            break
    return urllib.parse.quote(" ".join(keep) + " Tamil Nadu")


def _gnews_search(query_text: str, *, max_items: int = 5) -> list[dict[str, str]]:
    """Fetch GNews RSS for the promise query. Returns [{title, url, source}]."""
    url = GNEWS_RSS.format(query=_promise_query(query_text))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            xml_text = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("promise gnews fetch failed: %s", e)
        return []
    items: list[dict[str, str]] = []
    try:
        root = ET.fromstring(xml_text)
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            src = (it.findtext("source") or "").strip()
            pub = (it.findtext("pubDate") or "").strip()
            if not (title and link):
                continue
            # HARD date gate: an article can only be evidence of THIS govt
            # delivering if it was published on/after the govt took office.
            # No parseable date OR a pre-era date → not eligible. (This is what
            # let a Sep-2025 'caste bias in schools' article wrongly mark a TVK
            # employment promise as 'partial'.)
            try:
                pdate = parsedate_to_datetime(pub).date().isoformat()
            except Exception:
                pdate = None
            if not pdate or pdate < GOVT_START:
                continue
            items.append({"title": title, "url": link, "source": src, "date": pdate})
            if len(items) >= max_items:
                break
    except ET.ParseError:
        pass
    return items


_JUDGE_PROMPT = """You judge whether news headlines show a Tamil Nadu government promise being DELIVERED.

PROMISE (made by the TVK government, in office since 2026-05-11):
"{promise}"

CANDIDATE HEADLINES (Google News, most recent first):
{headlines}

STRICT RULES — identical discipline to the Promise Comparator:
- DELIVERY means a concrete government ACTION: a GO issued, scheme launched,
  funds released, facility inaugurated, recruitment notified, law passed.
- Announcements of INTENT ("CM says will...", "govt plans...") are NOT delivery.
- Protests, demands, criticism, or coverage of the promise being UNMET are NOT delivery.
- Pre-2026-05-11 events or other states' news are NOT delivery.
- The headline must be about the EXACT SAME subject as the promise — not a
  related theme. A promise about caste bias in EMPLOYMENT is NOT matched by an
  article about caste bias in SCHOOLS; a women's-health promise is NOT matched
  by general women's-safety news. Different sub-domain = NOT a match.
- A headline merely sharing keywords with the promise is NOT a match.
- WHEN IN DOUBT, answer delivery_signal=false. A wrong match destroys trust;
  a missed match costs nothing (the weekly sweep retries).

Output ONLY this JSON:
{{"delivery_signal": true/false, "best_index": <0-based index or null>,
  "confidence": <0.0-1.0>, "note": "<one line why>"}}"""


def _judge(promise_text: str, hits: list[dict[str, str]]) -> Optional[dict[str, Any]]:
    from app.ingestion.ai_processor import llm_call_with_fallback
    headlines = "\n".join(
        f"{i}. [{h['source']}, {h.get('date', '?')}] {h['title']}"
        for i, h in enumerate(hits))
    raw = llm_call_with_fallback(
        [{"role": "user", "content": _JUDGE_PROMPT.format(
            promise=promise_text, headlines=headlines)}],
        max_tokens=200,
    )
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def sweep_promise_evidence(*, limit: int = 50) -> dict[str, Any]:
    """Search delivery evidence for the top `limit` open promises.

    Priority order: promises WITH a deadline first (deadline ascending —
    the most accountable ones), then the rest by id. Skips promises that
    already have an evidence_url (the comparator/admin already covered them).
    """
    db = get_db()
    rows = (db.table("promises").select("*")
            .in_("status", ["pending", "partial"])
            .execute().data or [])
    # Deadline-bearing promises first, nearest deadline first.
    with_dl = sorted([r for r in rows if r.get("deadline")], key=lambda r: r["deadline"])
    without_dl = [r for r in rows if not r.get("deadline")]
    queue = [r for r in (with_dl + without_dl) if not r.get("evidence_url")][:limit]

    out = {"scanned": 0, "evidence_attached": 0, "upgraded_partial": 0,
           "checked_at": datetime.now(timezone.utc).isoformat()}

    for p in queue:
        out["scanned"] += 1
        try:
            hits = _gnews_search(p.get("text") or "")
            if not hits:
                continue
            verdict = _judge(p.get("text") or "", hits)
            if not verdict or not verdict.get("delivery_signal"):
                continue
            conf = float(verdict.get("confidence") or 0)
            idx = verdict.get("best_index")
            # 0.8 bar (raised from 0.7): a loose match marking a promise
            # 'partial' with weak evidence is far worse than leaving it pending.
            if conf < 0.8 or idx is None or not (0 <= int(idx) < len(hits)):
                continue
            best = hits[int(idx)]
            updates: dict[str, Any] = {"evidence_url": best["url"]}
            # pending -> partial only. NEVER auto-kept; 'kept' needs a human.
            if p.get("status") == "pending":
                updates["status"] = "partial"
                out["upgraded_partial"] += 1
            db.table("promises").update(updates).eq("id", p["id"]).execute()
            out["evidence_attached"] += 1
            logger.info("promise-evidence: %s -> %s (conf %.2f, %s)",
                        (p.get("text") or "")[:60], best["url"][:80], conf,
                        verdict.get("note", ""))
        except Exception:
            logger.exception("promise-evidence failed for promise %s", p.get("id"))

    return out


def clear_lowquality_evidence() -> dict[str, Any]:
    """Undo the loose auto-matches from the earlier date-BLIND sweep.

    The bad matches (e.g. a TVK employment promise pointing at a Sep-2025
    'caste bias in schools' article) all share one signature: the promise's
    ONLY evidence is a single Google-News redirect URL. Genuine evidence
    (comparator / admin) carries multiple real article links. We revert those
    auto-matches — clear the evidence and drop 'partial' back to 'pending' — so
    the fixed, date-gated, stricter sweep can re-evaluate them cleanly."""
    db = get_db()
    rows = db.table("promises").select("id, status, evidence_url").execute().data or []
    reverted: list[str] = []
    for r in rows:
        ev = (r.get("evidence_url") or "").strip()
        if not ev:
            continue
        urls = [u.strip() for u in ev.split(";") if u.strip()]
        if len(urls) == 1 and "news.google.com/rss/articles" in urls[0]:
            upd: dict[str, Any] = {"evidence_url": None}
            if r.get("status") == "partial":
                upd["status"] = "pending"
            try:
                db.table("promises").update(upd).eq("id", r["id"]).execute()
                reverted.append(r["id"])
            except Exception:
                logger.exception("clear_lowquality_evidence failed for %s", r["id"])
    logger.info("clear_lowquality_evidence: reverted %d auto-matches", len(reverted))
    return {"reverted": len(reverted), "ids": reverted}
