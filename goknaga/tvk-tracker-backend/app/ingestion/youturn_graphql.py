"""YouTurn fact-check ingester (GraphQL).

YouTurn (youturn.in) is Tamil Nadu's main Tamil fact-checker, but its site is a
pure SPA with NO RSS / sitemap / WP-API — so the RSS scraper and Twitter monitor
both miss it, and its debunks only reached this dashboard via manual flagging.

This module uses YouTurn's own backend — a public GraphQL API the SPA calls:
    https://www.youturn.in/api/graphql
The `get_recent_fact_checks(language_id, page_number, page_limit)` query returns
every published fact-check with a verdict (`is_fact` ∈ false/fake/misleading),
the headline, party tag, category, view count and a perma_link. We map each
political debunk straight into `propaganda_events` (status='debunked') with NO
LLM call — the data is already structured, which also means the backfill is free
and unaffected by AI-provider quota.

Deterministic mapping:
  - favoring        ← party_tags.name (Tamil/English) or tokens in the slug
  - propaganda_type ← keyword heuristic on the slug (best-effort; default 'other')
  - debunk_reach_estimate ← YouTurn article views (how far the correction travelled)
  - status='debunked', debunk_source='YouTurn', debunk_url=https://youturn.in/factcheck/<slug>

Scope: only items we can tie to a Tamil-Nadu party (TVK/DMK/AIADMK/…) are
imported; generic/national fakes with no TN-party signal are skipped.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from app.database import get_db

logger = logging.getLogger(__name__)

GQL_ENDPOINT = "https://www.youturn.in/api/graphql"
_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; TVKTracker-YouTurn/1.0)",
    "Origin": "https://youturn.in",
    "Referer": "https://youturn.in/",
}

# Discovered via get_all_system_languages (UUIDs are stable per language).
LANG_TAMIL = "839bcc29-853f-4c4c-8700-98fd88558952"
LANG_ENGLISH = "ea83e859-ce26-4086-9e85-ec40f5dbe4f0"

# Canonical favoring labels from a party tag (Tamil dot-less + English forms).
_PARTY_MAP = {
    "திமுக": "DMK", "dmk": "DMK",
    "தவெக": "TVK", "tvk": "TVK", "tamilagavettrikazhagam": "TVK",
    "அதிமுக": "AIADMK", "aiadmk": "AIADMK", "admk": "AIADMK",
    "பாஜக": "BJP", "bjp": "BJP",
    "பாமக": "PMK", "pmk": "PMK",
    "விசிக": "VCK", "vck": "VCK",
    "நதக": "NTK", "நாம்தமிழர்": "NTK", "ntk": "NTK", "naamtamilar": "NTK",
    "மதிமுக": "MDMK", "mdmk": "MDMK",
    "காங்கிரஸ்": "Congress", "congress": "Congress", "inc": "Congress",
}
# Slug tokens → favoring, for when the party tag is missing/unmapped.
_SLUG_PARTY = [("aiadmk", "AIADMK"), ("admk", "AIADMK"), ("tvk", "TVK"),
               ("dmk", "DMK"), ("bjp", "BJP"), ("pmk", "PMK"), ("vck", "VCK")]

# This tracker's mission is TVK-government accountability + DMK defence, so we
# only import debunks tied to the TN electoral triangle. National/other-party
# fakes (e.g. a fake ₹500 note tagged BJP) are skipped as off-mission.
TN_SCOPE = {"TVK", "DMK", "AIADMK"}


def _norm_party(name: str) -> str:
    """Lowercase + strip dots/spaces/punct so 'த.வெ.க' and 'TVK' both match."""
    return re.sub(r"[\s.\-_/]", "", (name or "").strip().lower())


def _tag_name(tag: Any) -> str:
    """party_tags comes back as an object {name} OR a list [{name}]."""
    if isinstance(tag, dict):
        return tag.get("name") or ""
    if isinstance(tag, list) and tag:
        first = tag[0]
        return (first.get("name") or "") if isinstance(first, dict) else ""
    return ""


def _tag_names(tags: Any) -> list[str]:
    if isinstance(tags, dict):
        return [tags.get("name")] if tags.get("name") else []
    if isinstance(tags, list):
        return [t.get("name") for t in tags if isinstance(t, dict) and t.get("name")]
    return []


def _favoring(party_name: str, slug: str) -> Optional[str]:
    """Identify the TN party a debunked fake serves. Returns None if we can't
    tie it to a TN party (→ out of scope, skip)."""
    mapped = _PARTY_MAP.get(_norm_party(party_name))
    if mapped:
        return mapped
    s = (slug or "").lower()
    for token, fav in _SLUG_PARTY:
        if re.search(rf"\b{token}\b", s) or token in s:
            return fav
    return None


def _propaganda_type(slug: str) -> str:
    s = (slug or "").lower()
    if any(k in s for k in ("edited-image", "morphed", "photoshop", "fake-image",
                            "fake-edited", "old-image", "old-photo", "edited-photo")):
        return "misleading_edit"
    if any(k in s for k in ("video", "footage", "clip", "dubbed", "old-video")):
        return "dubbed_footage"
    if any(k in s for k in ("quote", "said", "statement", "speech", "remark")):
        return "fake_quote"
    if any(k in s for k in ("initiative", "scheme", "launched", "credit", "restored",
                            "by-tvk", "tvk-gov", "tvk-regime", "achievement", "inaugurat")):
        return "manufactured_achievement"
    return "other"


def _slug_to_title(slug: str) -> str:
    """Human-readable English title from the perma_link slug."""
    t = re.sub(r"[-_]+", " ", (slug or "").strip("-_/")).strip()
    return (t[:1].upper() + t[1:]) if t else "YouTurn fact-check"


def _gql(query: str, timeout: int = 30) -> Optional[dict]:
    try:
        body = json.dumps({"query": query}).encode("utf-8")
        req = urllib.request.Request(GQL_ENDPOINT, data=body, headers=_HEADERS, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        logger.warning("youturn gql failed: %s", e)
        return None


_ITEM_FIELDS = ("is_fact perma_link published_date_time title views likes "
                "party_tags{ name } category_tags{ name }")


def fetch_page(language_id: str, page_number: int, page_limit: int = 30) -> list[dict]:
    q = (f'{{ get_recent_fact_checks(language_id:"{language_id}",'
         f'page_number:{page_number},page_limit:{page_limit}){{ items{{ {_ITEM_FIELDS} }} }} }}')
    data = _gql(q)
    try:
        return (data["data"]["get_recent_fact_checks"]["items"]) or []
    except (TypeError, KeyError):
        return []


def _load_seen_urls(db) -> set[str]:
    """Pre-load existing YouTurn debunk_urls so the backfill is O(1) per item."""
    seen: set[str] = set()
    try:
        rows = (db.table("propaganda_events").select("debunk_url")
                .ilike("debunk_url", "%youturn.in%").execute().data or [])
        seen = {r["debunk_url"] for r in rows if r.get("debunk_url")}
    except Exception:
        pass
    return seen


def ingest_youturn(days_back: int = 7, page_limit: int = 30,
                   max_pages: int = 40, language_id: str = LANG_TAMIL) -> dict[str, int]:
    """Pull recent YouTurn fact-checks and insert TN-political debunks into
    propaganda_events. `days_back` bounds how far to page (use 45-60 for the
    one-time backfill, 7 for the daily cron)."""
    db = get_db()
    seen = _load_seen_urls(db)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).date().isoformat()
    counts = {"fetched": 0, "inserted": 0, "dup": 0, "out_of_scope": 0, "failed": 0, "pages": 0}

    for page in range(1, max_pages + 1):
        items = fetch_page(language_id, page, page_limit)
        if not items:
            break
        counts["pages"] = page
        oldest_on_page = "9999"
        for it in items:
            counts["fetched"] += 1
            pub = (it.get("published_date_time") or "")[:10]
            if pub:
                oldest_on_page = min(oldest_on_page, pub)
            slug = it.get("perma_link") or ""
            if not slug:
                continue
            # YouTurn's SPA routes a fact-check at /factcheck/<perma_link>
            # (SINGLE_FACT_CHECK route). A bare /<slug> falls through to the
            # app's catch-all 404, so the prefix is required for the link to work.
            url = f"https://youturn.in/factcheck/{slug}"
            if url in seen:
                counts["dup"] += 1
                continue
            fav = _favoring(_tag_name(it.get("party_tags")), slug)
            if fav not in TN_SCOPE:
                counts["out_of_scope"] += 1
                continue
            views = it.get("views") or 0
            cats = _tag_names(it.get("category_tags"))
            is_fact = (it.get("is_fact") or "").lower()
            row = {
                "title": _slug_to_title(slug)[:200],
                "description": (
                    f"YouTurn fact-check (verdict: {is_fact or 'false'}). "
                    f"Original headline: {it.get('title') or '—'}"
                )[:1000],
                "propaganda_type": _propaganda_type(slug),
                "favoring": fav,
                "platform": None,
                "reach_estimate": None,  # fake's reach unknown
                "debunk_url": url,
                "debunk_source": "YouTurn",
                "debunk_reach_estimate": int(views) if views else None,
                "first_seen": pub or None,
                "incident_date": pub or None,
                "status": "debunked",
                "tags": ["youturn", is_fact or "false", *[c for c in cats if c]][:8],
                "source_urls": [url],
                "notes": (
                    f"Auto-ingested from YouTurn GraphQL on "
                    f"{datetime.now(timezone.utc).isoformat()}. Verdict={is_fact}; "
                    f"party_tag={_tag_name(it.get('party_tags'))!r}; views={views}."
                ),
            }
            try:
                db.table("propaganda_events").insert(row).execute()
                seen.add(url)
                counts["inserted"] += 1
            except Exception as e:
                logger.warning("youturn insert failed for %s: %s", url, e)
                counts["failed"] += 1
        if oldest_on_page < cutoff:
            break  # paged past the window

    logger.info("youturn ingest: %s", counts)
    return counts
