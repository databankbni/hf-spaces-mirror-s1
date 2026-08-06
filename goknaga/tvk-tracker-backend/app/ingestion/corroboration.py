"""
Automated corroboration: search the web for press coverage that confirms
single-source-pending incidents, and auto-promote when 2+ distinct press
outlets are found.

We use Google News RSS — free, no API key, no rate limit hassle, and it
covers the entire indexed news web including Tamil press outlets. Each
result includes the outlet name so we can verify against our credibility
tier registry.

The corroboration loop runs as a scheduled job (POST /api/admin/sweep-verify).
For each pending incident:
  1. Build a focused search query from location + key title nouns
  2. Hit Google News RSS for India edition
  3. Parse the XML to get (url, outlet, date) per result
  4. Map each outlet name to our credibility tier
  5. Filter to PRESS-tier outlets, dated within ±7 days of incident_date
  6. If 2+ DISTINCT press outlets → promote and attach as new sources
"""
from __future__ import annotations
import re
import logging
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus, urlparse

import httpx

from app.database import get_db

logger = logging.getLogger(__name__)

GOOGLE_NEWS_RSS = (
    "https://news.google.com/rss/search"
    "?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
)

# Registry of known outlets — keyed by lowercase "fingerprint" snippets that
# appear in either the result URL host OR Google News' <source> title.
# When ANY fingerprint matches, the outlet is recognized and counted toward
# verification.
#
# Format:
#   "fingerprint substring": ("canonical_outlet_id", "credibility_tier")
#
# Google's <source> titles look like "The Hindu", "Times of India", "DT Next".
# Keep fingerprints lowercase + short so they match these reliably.
OUTLET_REGISTRY: dict[str, tuple[str, str]] = {
    # ---- Established English press ----
    "the hindu":             ("the_hindu",              "established_press"),
    "thehindu":              ("the_hindu",              "established_press"),
    "indian express":        ("indian_express",         "established_press"),
    "indianexpress":         ("indian_express",         "established_press"),
    "times of india":        ("times_of_india",         "established_press"),
    "timesofindia":          ("times_of_india",         "established_press"),
    "ndtv":                  ("ndtv",                   "established_press"),
    "deccan chronicle":      ("deccan_chronicle",       "established_press"),
    "deccan herald":         ("deccan_herald",          "established_press"),
    "new indian express":    ("new_indian_express",     "established_press"),
    "newindianexpress":      ("new_indian_express",     "established_press"),
    "hindustan times":       ("hindustan_times",        "established_press"),
    "tribune":               ("tribune",                "established_press"),
    "news18":                ("news18",                 "established_press"),
    "india today":           ("india_today",            "established_press"),
    "republic":              ("republic_tv",            "established_press"),
    "wion":                  ("wion",                   "established_press"),
    "moneycontrol":          ("moneycontrol",           "established_press"),
    "business standard":     ("business_standard",      "established_press"),
    "mint":                  ("livemint",               "established_press"),
    "economic times":        ("economic_times",         "established_press"),
    "outlook":               ("outlook",                "established_press"),
    # ---- Tamil press ----
    "vikatan":               ("vikatan",                "established_press"),
    "dinamani":              ("dinamani",               "established_press"),
    "hindu tamil":           ("hindu_tamil",            "established_press"),
    "hindutamil":            ("hindu_tamil",            "established_press"),
    "dinamalar":             ("dinamalar",              "regional_press"),
    "maalai malar":          ("maalai_malar",           "regional_press"),
    "maalaimalar":           ("maalai_malar",           "regional_press"),
    "puthiya thalaimurai":   ("puthiya_thalaimurai",    "regional_press"),
    "puthiyathalaimurai":    ("puthiya_thalaimurai",    "regional_press"),
    "theekkathir":           ("theekkathir",            "regional_press"),
    "thanthi":               ("thanthi_tv",             "regional_press"),
    "polimer":               ("polimer_news",           "regional_press"),
    "sun news":              ("sun_news_tamil",         "established_press"),
    "sunnewstamil":          ("sun_news_tamil",         "established_press"),
    # ---- Regional English (TN-focused) ----
    "dt next":               ("dt_next",                "regional_press"),
    "dtnext":                ("dt_next",                "regional_press"),
    "tamil guardian":        ("tamil_guardian",         "regional_press"),
    # ---- Online native ----
    "scroll":                ("scroll",                 "online_native"),
    "thewire":               ("the_wire",               "online_native"),
    "the wire":              ("the_wire",               "online_native"),
    "thenewsminute":         ("thenewsminute",          "online_native"),
    "the news minute":       ("thenewsminute",          "online_native"),
    "thequint":              ("the_quint",              "online_native"),
    "the quint":             ("the_quint",              "online_native"),
    "theprint":              ("the_print",              "online_native"),
    "the print":             ("the_print",              "online_native"),
    "newslaundry":           ("newslaundry",            "online_native"),
    "newsmobile":            ("newsmobile",             "online_native"),
    "sparkpluz":             ("spark_plus",             "online_native"),
    "spark plus":            ("spark_plus",             "online_native"),
    "frontline":             ("frontline",              "established_press"),
    "factly":                ("factly",                 "online_native"),
    "alt news":              ("alt_news",               "online_native"),
    "altnews":               ("alt_news",               "online_native"),
    "boom":                  ("boom_live",              "online_native"),
    "youturn":               ("youturn",                "online_native"),
    # ---- Government official channels (primary sources) ----
    # tier='govt_announcement' — counted toward verification (PRESS_TIERS)
    # but excluded from sentiment scoring because these are by definition
    # spokespeople for the ruling party (not neutral observers).
    "cmotamilnadu":          ("cmo_tn",                 "govt_announcement"),
    "tndiprnews":            ("tn_dipr",                "govt_announcement"),
    "twitter_cmotamilnadu":  ("cmo_tn",                 "govt_announcement"),
    "twitter_tndiprnews":    ("tn_dipr",                "govt_announcement"),
    "cmo tn":                ("cmo_tn",                 "govt_announcement"),
    "tn dipr":               ("tn_dipr",                "govt_announcement"),
}

# Press tiers — anything in this set counts toward verification.
# `govt_announcement` is included so CMO/DIPR releases count as evidence,
# but the ai_processor explicitly skips press_sentiment classification on
# them (govt spokespeople aren't neutral observers).
PRESS_TIERS = {"primary", "established_press", "regional_press", "online_native", "govt_announcement"}

# Subset of PRESS_TIERS whose articles ARE eligible for press_sentiment
# classification (i.e. independent observers). Used by ai_processor to
# decide whether to ask Claude for a tone classification.
INDEPENDENT_PRESS_TIERS = {"primary", "established_press", "regional_press", "online_native"}

# Words to strip from titles before building a search query — they create
# noise and reduce result count without helping match accuracy.
STOPWORDS = {
    "the", "a", "an", "in", "on", "at", "to", "for", "by", "with", "of",
    "and", "or", "but", "is", "was", "are", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "should",
    "tvk", "tamil", "nadu", "tn",  # already implicit
}


def _identify_outlet(article_url: str, google_source_title: str) -> tuple[str, str]:
    """Given a Google-News result URL and the <source> title it provides,
    return (outlet_id, tier).

    Google News wraps article links through `news.google.com/rss/articles/...`
    so the URL hostname is useless for outlet detection — we look in the
    `<source>` element instead, which has a clean outlet name like
    "The Hindu" or "DT Next". URL is used only as a secondary signal.
    """
    title_lower = (google_source_title or "").lower().strip()
    host = ""
    try:
        host = urlparse(article_url).netloc.lower().replace("www.", "")
    except Exception:
        pass

    # PRIMARY: fingerprint match against the <source> title (most reliable)
    if title_lower:
        for fingerprint, (oid, tier) in OUTLET_REGISTRY.items():
            if fingerprint in title_lower:
                return (oid, tier)

    # SECONDARY: fingerprint match against URL host (works for direct links)
    if host:
        for fingerprint, (oid, tier) in OUTLET_REGISTRY.items():
            # Reduce noise: don't match super-short fingerprints against host
            if len(fingerprint) >= 5 and fingerprint.replace(" ", "") in host:
                return (oid, tier)

    return ("unknown", "unknown")


def _build_queries(title: str, location: str | None) -> list[str]:
    """Build a list of progressively-broader queries to try.

    Google News indexes story headlines well but not deep article bodies, so
    overly specific queries (full name + location + verb) often return 0
    results. We try multiple widths and stop at the first that hits.
    """
    cleaned = re.sub(r"[^\w\s]", " ", title or "").lower()
    words = [w for w in cleaned.split() if w not in STOPWORDS and len(w) > 3]
    # Drop pure names (capitalized in original) — they're often spelled
    # differently across outlets. Keep generic incident nouns instead.
    # Names contain unusual letter combos — heuristic: drop tokens whose
    # frequency in real english is low. Cheap proxy: keep first 4 nouns.
    location_norm = (location or "").strip()

    queries: list[str] = []

    # Tier 1 — location + 3 most-frequent generic words (best precision)
    if location_norm and words:
        queries.append(f"{location_norm} {' '.join(words[:3])}")

    # Tier 2 — location + 1 strongest keyword (broader)
    if location_norm and words:
        queries.append(f"{location_norm} {words[0]}")

    # Tier 3 — just words, no location (last resort)
    if words:
        queries.append(" ".join(words[:4]))

    # Dedupe + remove empties
    seen, out = set(), []
    for q in queries:
        q = q.strip()
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out


def _fetch_and_parse(query: str, *, timeout_sec: float = 10.0) -> list[dict]:
    """Hit Google News RSS for ONE query, return raw item dicts (no filters)."""
    url = GOOGLE_NEWS_RSS.format(query=quote_plus(query))
    try:
        r = httpx.get(url, timeout=timeout_sec,
                       headers={"User-Agent": "Mozilla/5.0 (TVK-Tracker corroborator)"})
        if r.status_code != 200:
            return []
        body = r.text
    except httpx.RequestError:
        return []

    parsed = []
    for chunk in re.findall(r"<item>(.*?)</item>", body, flags=re.S):
        link_m  = re.search(r"<link>(.*?)</link>", chunk, flags=re.S)
        pub_m   = re.search(r"<pubDate>(.*?)</pubDate>", chunk, flags=re.S)
        src_m   = re.search(r"<source[^>]*>(.*?)</source>", chunk, flags=re.S)
        title_m = re.search(r"<title>(.*?)</title>", chunk, flags=re.S)

        link = (link_m.group(1).strip() if link_m else "")
        if not link:
            continue
        parsed.append({
            "url": link,
            "pub_date": (pub_m.group(1).strip() if pub_m else ""),
            "source_title": (src_m.group(1).strip() if src_m else ""),
            "headline": (title_m.group(1).strip() if title_m else ""),
        })
    return parsed


def search_corroboration(
    title: str,
    location: str | None,
    incident_date: str | None,
    exclude_urls: set[str],
    *,
    timeout_sec: float = 10.0,
) -> list[dict]:
    """Find press-tier articles that cover the same event.

    Tries up to 3 progressively-broader queries to ride out Google News's
    inconsistent indexing. Filters results to:
      - Known press outlets only
      - Within ±7 days of incident_date if given
      - URL not already attached to this incident
    Returns [{url, outlet, tier, date, source_title}].
    """
    queries = _build_queries(title, location)
    raw_items: list[dict] = []
    for q in queries:
        hits = _fetch_and_parse(q, timeout_sec=timeout_sec)
        if hits:
            raw_items.extend(hits)
            # Stop at first query that produced ≥2 hits — that's usually
            # the most specific one that still has results.
            if len(hits) >= 2:
                break

    if not raw_items:
        return []

    # Dedupe by URL
    seen_urls: set[str] = set()
    items: list[dict] = []
    for item in raw_items:
        link = item["url"]
        if link in seen_urls or link in exclude_urls:
            continue
        seen_urls.add(link)

        outlet, tier = _identify_outlet(link, item["source_title"])
        if tier not in PRESS_TIERS:
            continue

        # Date proximity filter — accept any pub date if parsing fails
        if incident_date:
            try:
                inc_dt = datetime.fromisoformat(incident_date[:10])
                pd = re.sub(r"\s+GMT$", "", item["pub_date"])
                try:
                    pub_dt = datetime.strptime(pd, "%a, %d %b %Y %H:%M:%S")
                except ValueError:
                    pub_dt = None
                if pub_dt and abs((pub_dt.date() - inc_dt.date()).days) > 7:
                    continue
            except Exception:
                pass

        items.append({
            "url": link,
            "outlet": outlet,
            "tier": tier,
            "date": item["pub_date"],
            "source_title": item["source_title"],
        })

    return items


def attempt_corroborate(incident: dict) -> dict:
    """Try to verify a single pending incident.

    Args:
        incident: dict with id, title, summary, location, incident_date, source_urls.

    Returns:
        {
          "promoted": bool,
          "matched_outlets": list[str],
          "added_urls": list[str],
          "reason": str,
        }
    """
    db = get_db()
    title = incident.get("title") or ""
    location = incident.get("location") or None
    incident_date = incident.get("incident_date") or None
    existing = set(incident.get("source_urls") or [])

    results = search_corroboration(title, location, incident_date, existing)
    distinct_outlets = {r["outlet"] for r in results}

    if len(distinct_outlets) < 2:
        return {
            "promoted": False,
            "matched_outlets": sorted(distinct_outlets),
            "added_urls": [],
            "reason": f"Found {len(distinct_outlets)} press outlets covering this; need 2+",
        }

    # Pick the best result per outlet (first hit per outlet, already date-filtered)
    seen_outlets: set[str] = set()
    to_add: list[dict] = []
    for r in results:
        if r["outlet"] in seen_outlets:
            continue
        seen_outlets.add(r["outlet"])
        to_add.append(r)
        if len(to_add) >= 4:
            break

    added_urls = [r["url"] for r in to_add]
    new_sources = list(set((incident.get("source_urls") or []) + added_urls))

    # Register each new URL in the sources table so downstream queries can
    # tag them properly
    for r in to_add:
        try:
            db.table("sources").upsert({
                "url": r["url"],
                "outlet": r["outlet"],
                "credibility_tier": r["tier"],
                "title": r.get("source_title") or "",
            }, on_conflict="url").execute()
        except Exception as e:
            logger.debug("Source upsert failed for %s: %s", r["url"], e)

    # Promote the incident
    try:
        db.table("incidents").update({
            "source_urls": new_sources,
            "source_count": len(new_sources),
            "verification_status": "multi_source_verified",
            # Also flip status to approved — a pending_review item that gets
            # 2+ press outlets is verified and should appear on the dashboard,
            # not stay hidden in pending_review.
            "status": "approved",
        }).eq("id", incident["id"]).execute()

        db.table("incident_audit").insert({
            "incident_id": incident["id"],
            "action": "auto_corroborated",
            "from_value": incident.get("verification_status") or "pending_verification",
            "to_value": "multi_source_verified",
            "actor": "corroboration_loop",
            "reason": (
                f"Auto-verified via Google News search. Press outlets found: "
                f"{', '.join(sorted(distinct_outlets))}. {len(added_urls)} URLs attached."
            ),
        }).execute()
    except Exception as e:
        logger.exception("Promote failed for %s", incident["id"])
        return {"promoted": False, "matched_outlets": sorted(distinct_outlets),
                "added_urls": [], "reason": f"DB write failed: {e}"}

    return {
        "promoted": True,
        "matched_outlets": sorted(distinct_outlets),
        "added_urls": added_urls,
        "reason": f"Confirmed by {len(distinct_outlets)} press outlets",
    }


def sweep_pending(
    *,
    max_age_days: int = 45,
    limit: int | None = None,
) -> dict:
    """Run a corroboration pass over all pending_verification incidents.
    Returns summary dict for the admin/cron caller."""
    db = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).date().isoformat()

    # BUG FIX: previously only scanned status='approved'. But most pending
    # items (tvkfiles import, telegram, recovered-from-rejected) land as
    # status='pending_review', so the sweep never saw them — 200+ orphaned
    # for weeks. Now scan BOTH statuses; corroboration promotes them to
    # status='approved' (see attempt_corroborate).
    #
    # BUG FIX 2 (2026-06-11): also re-sweep verification_status='single_source'.
    # The 48h pending-escalation ladder publishes uncorroborated items with the
    # single_source tag — but nothing ever re-checked them afterward, so ~148
    # items that LATER got press coverage stayed tagged single_source forever.
    # pending_verification items keep priority (sorted first) so the trickle's
    # small per-run limit isn't eaten by the single_source backlog.
    res = db.table("incidents").select(
        "id, title, summary, location, incident_date, source_urls, verification_status, status"
    ).in_("status", ["approved", "pending_review"]).in_(
        "verification_status", ["pending_verification", "single_source"]
    ).gte("incident_date", cutoff).execute()
    candidates = res.data or []
    candidates.sort(key=lambda r: 0 if r.get("verification_status") == "pending_verification" else 1)
    if limit:
        candidates = candidates[:limit]

    promoted = 0
    failed = 0
    total_outlets = 0

    for inc in candidates:
        try:
            outcome = attempt_corroborate(inc)
            if outcome["promoted"]:
                promoted += 1
                total_outlets += len(outcome["matched_outlets"])
                logger.info(
                    "Promoted %s via %s",
                    inc["id"], ",".join(outcome["matched_outlets"])
                )
        except Exception:
            logger.exception("attempt_corroborate failed for %s", inc["id"])
            failed += 1

    return {
        "candidates_scanned": len(candidates),
        "promoted": promoted,
        "failed": failed,
        "avg_outlets_per_promote": (total_outlets / promoted) if promoted else 0,
    }
