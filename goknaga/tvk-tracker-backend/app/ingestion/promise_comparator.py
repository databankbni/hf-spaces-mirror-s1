"""Promise Comparator — match a govt-tier announcement against the TVK
manifesto and classify what it actually delivers.

INPUT  : a press release / order from CMO TN / DIPR (already extracted
         by ai_processor — we get title, summary, category, location, etc.)
OUTPUT : a verdict per matching manifesto promise:
   - "fulfilled"  : announcement implements the promise on or above its
                    pledged terms
   - "partial"    : implements but with materially diluted terms
   - "broken"     : contradicts the promise OR implements an inferior
                    version that materially deviates from the pledge
   - "new"        : doesn't relate to any manifesto promise; this is a
                    fresh govt initiative
   - "irrelevant" : not actually a policy announcement (e.g. condolence)

When verdict is fulfilled/partial/broken, this module also:
  - updates the promise row's status to kept / partial / broken
  - adds the announcement URL to promise.evidence_url
  - returns a structured dict the caller can save into incidents.ai_raw

Cost: one Claude Haiku 4.5 call per announcement. ~$0.0008/call.
Why category-prefiltering matters: rather than send all ~390 promises
into the prompt (~30K tokens of noise), we narrow to promises in the
same `category` as the extracted announcement. Most announcements only
plausibly touch 5-15 promises. Token cost drops 10-20×.
"""
from __future__ import annotations
import json
import logging
from typing import Optional

from app.database import get_db
from app.ingestion.ai_processor import (
    _get_client_and_model, _get_client_chain,
    _strip_code_fences, llm_call_with_fallback,
)

logger = logging.getLogger(__name__)


# Category-mapping table: incident categories -> manifesto promise
# categories that could plausibly match.  We over-broaden deliberately
# because the LLM does the final pruning anyway, but exclude obviously
# unrelated combos to save tokens.
_CATEGORY_TO_PROMISE_CATS: dict[str, list[str]] = {
    # Direct mapping for announcements that ARE policy actions
    "governance":              ["governance", "farmers", "fishermen", "msme", "women", "youth",
                                "education", "health", "transport", "infrastructure",
                                "welfare", "tribal", "minority", "sc_st", "industry",
                                "agriculture", "labour", "environment"],
    "broken_promise":          ["farmers", "fishermen", "women", "youth", "education", "health",
                                "msme", "welfare", "governance"],
    "credit_stealing":         ["farmers", "women", "youth", "education", "health", "welfare",
                                "governance"],
    "investment_announcement": ["industry", "infrastructure", "msme", "governance"],
    "tenders":                 ["infrastructure", "governance"],
    "civic_failure":           ["infrastructure", "governance"],
    "power_cut":               ["infrastructure"],
    "water_shortage":          ["infrastructure"],
}


SYSTEM_PROMPT = """You are a manifesto-vs-action auditor for the TVK government in
Tamil Nadu.  Your job is to compare a fresh official announcement (from
CMO TN or DIPR) against TVK's election manifesto and classify whether
the announcement honours, dilutes, contradicts, or is unrelated to the
campaign promise.

Be ANALYTICAL not partisan.  When in doubt between "fulfilled" and
"partial", err toward "partial".  When in doubt between "partial" and
"broken", consider the user's reasonable expectation at the time of
voting — if a voter who voted on the manifesto would feel cheated, it's
"broken"; if they'd feel under-served but not betrayed, it's "partial".

CRITICAL — DELIVERY-ONLY RULE (do not violate):
Only classify fulfilled / partial / broken when the input shows the
GOVERNMENT actually DELIVERING or formally ANNOUNCING concrete action
toward the promise.  If the input is a PROTEST, grievance, complaint,
crime, accountability failure, allegation, opposition criticism, or any
non-delivery event, it is NOT evidence of delivery -> return
verdict="irrelevant" with best_match_promise_id=null.  NEVER put a
protest or grievance in delivered_terms.

Do NOT match by topic keyword alone.  A teacher PROTEST is not evidence
about a teacher-PENSION promise.  A water-shortage complaint is not
delivery of a water promise.  An honour killing is not the breaking of an
anti-discrimination promise.  If the announcement does not concretely
advance or contradict the SPECIFIC promised action, return "irrelevant".

Respond ONLY with valid JSON. No markdown fences, no explanation."""


PROMPT = """A TVK govt official channel just announced the following:

TITLE   : {title}
SUMMARY : {summary}
CATEGORY: {category}
LOCATION: {location}
DATE    : {date}

Compare it against these RELEVANT manifesto promises (filtered by
category to keep this prompt focused — irrelevant promises were
already excluded):

{promises_block}

Return JSON of the form:
{{
  "best_match_promise_id": "<uuid or null if NEW initiative>",
  "verdict": one of [
    "fulfilled",   // delivers on the promise at promised level or better
    "partial",     // implements but with materially diluted terms
    "broken",      // contradicts or implements a materially inferior version
    "new",         // unrelated to any listed promise — fresh govt initiative
    "irrelevant"   // not actually a policy announcement
  ],
  "confidence": 0.0-1.0,
  "gap_summary": "1-2 sentences: what was promised vs what was announced. If verdict=new, describe what the new initiative is. If verdict=irrelevant, explain.",
  "promised_terms": "exact terms from the manifesto (verbatim phrase OK)",
  "delivered_terms": "exact terms of the announcement (verbatim or paraphrase)"
}}

CALIBRATION EXAMPLES:

  EX 1: Manifesto: "Complete crop loan waiver for small + marginal farmers"
        Announcement: "Tiered waiver: 100% only up to ₹50K for marginal,
                       50% up to ₹50K for small, just ₹5K for loans >₹1L"
        -> verdict=broken, gap_summary="Manifesto promised complete
           unconditional waiver. Announcement is a heavily tiered partial
           scheme with most beneficiaries getting only ₹5-20K relief on
           larger loans."

  EX 2: Manifesto: "Free bus travel for women on all routes"
        Announcement: "Free bus travel for women launched on all govt
                       buses including express routes from day 1"
        -> verdict=fulfilled

  EX 3: Manifesto: "Rs 1500/month assistance for unemployed graduates"
        Announcement: "Rs 1000/month assistance for unemployed graduates"
        -> verdict=partial (slightly under-delivered on amount)

  EX 4: Manifesto: (no matching pledge)
        Announcement: "TN govt launches AI research center in IIT Madras"
        -> verdict=new, gap_summary="New initiative — AI research center
           at IIT Madras. No matching manifesto pledge."

  EX 5: Announcement: "CM expresses condolences on the passing of veteran
                       actor Sivakumar"
        -> verdict=irrelevant"""


_KEYWORD_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be",
    "of", "to", "in", "on", "at", "for", "with", "by", "from", "as", "that",
    "this", "these", "those", "tamil", "nadu", "tn", "tvk", "govt", "government",
    "state", "scheme", "will", "has", "have", "had", "shall", "may", "rs",
    "rupees", "crore", "lakh", "lakhs", "annual", "per", "year",
}


def _extract_keywords(text: str, max_n: int = 8) -> list[str]:
    """Cheap keyword extractor — splits, strips stopwords, keeps top
    distinctive tokens for an ILIKE search."""
    import re
    words = re.findall(r"[a-zA-Z]{4,}", (text or "").lower())
    seen, out = set(), []
    for w in words:
        if w in _KEYWORD_STOPWORDS or w in seen:
            continue
        seen.add(w)
        out.append(w)
        if len(out) >= max_n:
            break
    return out


def _candidate_promises(
    db,
    category: str | None,
    *,
    title: str = "",
    summary: str = "",
    limit: int = 30,
) -> list[dict]:
    """Two-tier candidate fetch:

    1. KEYWORD MATCH — extract distinctive nouns from the announcement
       title/summary, find promises whose text contains any of them. This
       surfaces semantically-related promises FIRST regardless of when
       they were inserted (vs Supabase's default insertion-order limit).

    2. CATEGORY BACKFILL — fill remaining slots from promises in
       plausibly-related categories (using _CATEGORY_TO_PROMISE_CATS).
       Newest-first so manually-seeded recent additions aren't dropped.

    Total cap = `limit` rows, deduped by id.
    """
    target_cats = _CATEGORY_TO_PROMISE_CATS.get(category or "", []) or [
        "governance", "farmers", "fishermen", "women", "youth",
        "education", "health", "msme", "welfare", "infrastructure",
    ]
    keywords = _extract_keywords(f"{title} {summary}")
    out: dict[str, dict] = {}

    # Tier 1: keyword-matched promises (ILIKE OR-chain).
    # Order newest-first so manually-seeded recent promises aren't dropped
    # under the limit cap (Supabase default is insertion order = oldest first).
    if keywords:
        try:
            or_clause = ",".join([f"text.ilike.%{kw}%" for kw in keywords])
            res = (
                db.table("promises")
                .select("id, text, category, status, made_date, deadline")
                .or_(or_clause)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            for row in (res.data or []):
                out[row["id"]] = row
        except Exception as e:
            logger.warning("Keyword candidate fetch failed: %s", e)

    # Tier 2: category backfill, newest-first
    remaining = limit - len(out)
    if remaining > 0:
        try:
            res = (
                db.table("promises")
                .select("id, text, category, status, made_date, deadline")
                .in_("category", target_cats)
                .order("created_at", desc=True)   # newest first
                .limit(remaining + 20)             # over-fetch for dedup
                .execute()
            )
            for row in (res.data or []):
                if row["id"] not in out:
                    out[row["id"]] = row
                if len(out) >= limit:
                    break
        except Exception as e:
            logger.warning("Category candidate fetch failed: %s", e)

    return list(out.values())


def _format_promises_block(promises: list[dict]) -> str:
    if not promises:
        return "(no matching-category promises on file)"
    lines = []
    for p in promises:
        snippet = (p.get("text") or "")[:200].replace("\n", " ")
        lines.append(f"  - id={p['id']} [{p['category']}] status={p['status']} :: {snippet}")
    return "\n".join(lines)


def compare_to_manifesto(*, title: str, summary: str, category: str,
                          location: Optional[str], date: str,
                          announcement_url: str) -> dict | None:
    """Run one comparison cycle. Returns the LLM verdict dict, or None on
    error.  Also persists side-effects (promise status updates,
    evidence_url) when verdict is fulfilled/partial/broken with
    confidence >= 0.7."""
    if not _get_client_chain():
        logger.warning("Promise comparator: no AI client configured")
        return None

    db = get_db()
    candidates = _candidate_promises(db, category, title=title, summary=summary)
    if not candidates:
        return {
            "best_match_promise_id": None,
            "verdict": "new",
            "confidence": 0.5,
            "gap_summary": "No matching-category promises on file to compare against — treating as new initiative by default.",
            "promised_terms": "",
            "delivered_terms": f"{title}: {summary[:200]}",
        }

    prompt = PROMPT.format(
        title=title,
        summary=summary[:1500],
        category=category,
        location=location or "TN state-wide",
        date=date,
        promises_block=_format_promises_block(candidates),
    )

    try:
        raw_response = llm_call_with_fallback(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=600,
        )
        if raw_response is None:
            logger.warning("Promise comparator: all AI providers failed")
            return None
        raw = _strip_code_fences(raw_response)
        verdict = json.loads(raw)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("Promise comparator AI call failed: %s", e)
        return None

    # Side-effects: update the matched promise if confidence is high enough
    pid = verdict.get("best_match_promise_id")
    v   = verdict.get("verdict")
    conf = float(verdict.get("confidence") or 0.0)

    if pid and v in ("fulfilled", "partial", "broken") and conf >= 0.7:
        new_status = {"fulfilled": "kept", "partial": "partial", "broken": "broken"}[v]
        try:
            cur = db.table("promises").select("evidence_url, notes, status, deadline").eq("id", pid).single().execute()
            cur_row = cur.data or {}
            old_status = cur_row.get("status")
            # DEADLINE GUARD (credibility): a promise cannot be "broken" before
            # its deadline arrives. If the comparator says broken but the
            # deadline is missing or still in the future, the govt is
            # under-delivering, not in breach yet -> cap at "partial". Only the
            # deadline-pass cron flips a promise to true "broken" after its
            # deadline lapses. This stops "12 broken on day 29" nonsense.
            if new_status == "broken":
                from datetime import date as _date
                _dl = cur_row.get("deadline")
                if not _dl or _dl > _date.today().isoformat():
                    new_status = "partial"
                    v = "partial"
            # Don't downgrade: if already "kept", don't switch to "partial".
            # Do upgrade: pending -> kept|partial|broken is always allowed.
            allowed_transitions = {
                "pending": {"kept", "partial", "broken"},
                "partial": {"kept", "broken"},
                "broken":  {"kept"},   # someone reversed a broken promise
                "kept":    set(),      # don't downgrade
            }
            if new_status in allowed_transitions.get(old_status or "pending", set()) or new_status == old_status:
                # Append URL to evidence (preserve existing URL if present)
                existing_evidence = (cur_row.get("evidence_url") or "").strip()
                new_evidence = (
                    f"{existing_evidence} ; {announcement_url}".strip(" ;")
                    if existing_evidence else announcement_url
                )
                note_addition = (
                    f"[auto: {v}] {verdict.get('gap_summary', '')[:300]} "
                    f"Promised: {verdict.get('promised_terms','')[:120]} | "
                    f"Delivered: {verdict.get('delivered_terms','')[:120]}"
                )
                merged_notes = ((cur_row.get("notes") or "") + "\n\n" + note_addition).strip()
                db.table("promises").update({
                    "status": new_status,
                    "evidence_url": new_evidence,
                    "notes": merged_notes[:2000],
                }).eq("id", pid).execute()
                logger.info("Promise comparator: %s -> %s (was %s) :: %s",
                            pid, new_status, old_status, verdict.get("gap_summary", "")[:80])
            else:
                logger.info("Promise comparator: skipped downgrade %s -> %s for %s",
                            old_status, new_status, pid)
        except Exception as e:
            logger.warning("Promise comparator: status update failed for %s: %s", pid, e)

    return verdict
