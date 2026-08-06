"""
DMK archive cross-reference lookup.

When the AI processor flags an incident as credit_stealing (or finds a
related_dmk_scheme hint), this module searches the dmk_announcements
archive for date-stamped official precedents and attaches them as
evidence on the incident.

Sources searched:
  - dmk_website (387 official achievements from dmk.in)
  - cmo_tamil_nadu (historical @CMOTamilnadu tweets — Phase 4)
  - tn_dipr (historical @TNDIPR tweets — Phase 4)
"""
import logging
import re
from app.database import get_db

logger = logging.getLogger(__name__)


# Useful "stop words" that hurt full-text matching against generic
# DMK announcement titles.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "by",
    "is", "was", "with", "scheme", "thittam", "tamil", "nadu", "tn",
    "tvk", "dmk", "stalin", "vijay", "cm", "govt", "government",
}


def _extract_keywords(text: str, min_len: int = 4) -> list[str]:
    """Pull content-bearing words from a title/summary for matching."""
    if not text:
        return []
    words = re.findall(r"[A-Za-z][A-Za-z0-9]+", text.lower())
    return list({w for w in words if len(w) >= min_len and w not in _STOPWORDS})


def find_precedents(
    incident_title: str,
    incident_summary: str,
    related_scheme: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """Return up to `limit` DMK archive items that look like precedents for
    the given incident. Each dict carries match_score (0-1) and match_reason.

    Heuristic:
      1. If `related_scheme` matches a dmk_schemes row, fetch announcements
         linked to that scheme_id directly (highest confidence).
      2. Run a full-text search on dmk_announcements using high-signal
         keywords extracted from incident title+summary.
      3. Score by how many keywords overlap.
    """
    db = get_db()
    results: dict[str, dict] = {}  # id -> result

    # ---- Stage 1: exact scheme link (highest confidence) ----
    if related_scheme:
        try:
            scheme = (
                db.table("dmk_schemes")
                .select("id, name, aliases")
                .eq("name", related_scheme)
                .limit(1)
                .execute()
            )
            if not scheme.data:
                scheme = (
                    db.table("dmk_schemes")
                    .select("id, name, aliases")
                    .ilike("name", f"%{related_scheme}%")
                    .limit(1)
                    .execute()
                )

            if scheme.data:
                row = scheme.data[0]
                scheme_id = row["id"]
                scheme_name = row["name"]
                aliases = row.get("aliases") or []

                # 1a. Pre-linked announcements (scheme_id column set by linker script)
                linked = (
                    db.table("dmk_announcements")
                    .select("id, title, content, announcement_date, source, source_url")
                    .eq("scheme_id", scheme_id)
                    .limit(limit)
                    .execute()
                )
                for a in linked.data or []:
                    results[a["id"]] = {
                        **a,
                        "match_score": 0.95,
                        "match_reason": f"Linked to DMK scheme '{scheme_name}'",
                    }

                # 1b. Text-search by scheme name + aliases (catches Tamil-script
                # entries the linker script couldn't match)
                terms = [scheme_name] + aliases
                for t in terms:
                    if not t or len(t) < 4:
                        continue
                    safe = t.replace("%", "")
                    try:
                        text_match = (
                            db.table("dmk_announcements")
                            .select("id, title, content, announcement_date, source, source_url")
                            .or_(f"title.ilike.*{safe}*,content.ilike.*{safe}*")
                            .limit(5)
                            .execute()
                        )
                        for a in text_match.data or []:
                            if a["id"] in results:
                                continue
                            results[a["id"]] = {
                                **a,
                                "match_score": 0.85,
                                "match_reason": f"Mentions '{t}' (alias of {scheme_name})",
                            }
                    except Exception as e:
                        logger.debug("Alias text-search failed for '%s': %s", t, e)
        except Exception as e:
            logger.debug("Scheme link lookup failed: %s", e)

    # ---- Stage 2: keyword-based fuzzy match ----
    keywords = _extract_keywords(incident_title)[:6] + _extract_keywords(incident_summary)[:4]
    keywords = list(dict.fromkeys(keywords))[:8]  # dedup, cap at 8

    if keywords:
        # Build OR query over title/content using ilike (Postgres'
        # full-text on the tsvector index would be faster but ilike is
        # adequate at this scale and easier to reason about).
        try:
            # Supabase OR filter syntax: or=(title.ilike.%word1%,content.ilike.%word1%, ...)
            or_parts = []
            for kw in keywords:
                safe = kw.replace("%", "")  # avoid wildcard injection
                or_parts.append(f"title.ilike.*{safe}*")
                or_parts.append(f"content.ilike.*{safe}*")
            or_filter = ",".join(or_parts)

            res = (
                db.table("dmk_announcements")
                .select("id, title, content, announcement_date, source, source_url, tags")
                .or_(or_filter)
                .limit(25)
                .execute()
            )

            for a in res.data or []:
                if a["id"] in results:
                    continue
                # Score = # of overlapping keywords / total keywords
                blob = ((a.get("title") or "") + " " + (a.get("content") or "")).lower()
                hits = sum(1 for kw in keywords if kw in blob)
                score = round(hits / max(len(keywords), 1), 2)
                if score < 0.25:
                    continue  # too weak
                results[a["id"]] = {
                    **a,
                    "match_score": score,
                    "match_reason": (
                        f"Matched {hits}/{len(keywords)} keywords: "
                        + ", ".join(k for k in keywords if k in blob)[:120]
                    ),
                }
        except Exception as e:
            logger.debug("Keyword search failed: %s", e)

    # Sort by score desc, return top N
    sorted_results = sorted(results.values(), key=lambda r: r["match_score"], reverse=True)[:limit]
    return sorted_results


def attach_evidence(incident_id: str, precedents: list[dict]) -> int:
    """Persist precedents as rows in incident_dmk_evidence."""
    if not precedents:
        return 0
    db = get_db()
    inserted = 0
    for p in precedents:
        try:
            db.table("incident_dmk_evidence").insert({
                "incident_id": incident_id,
                "announcement_id": p["id"],
                "match_score": p.get("match_score"),
                "match_reason": p.get("match_reason"),
            }).execute()
            inserted += 1
        except Exception as e:
            # likely unique violation if same pair already exists — ignore
            logger.debug("Evidence link insert: %s", e)
    return inserted
