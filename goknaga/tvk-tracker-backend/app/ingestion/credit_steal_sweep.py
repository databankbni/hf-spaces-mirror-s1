"""Credit-steal cross-check sweep — match new TVK announcements against the
FULL DMK archive.

Why this exists: the AI processor's credit-steal check only "knows" the curated
dmk_schemes list (~387 items) baked into its prompt. But the full DMK archive is
3,000+ items (387 dmk.in achievements + ~1,400 @CMOTamilnadu + ~1,200 @TNDIPRNEWS
tweets). So a TVK re-announcement that echoes a DMK-era DIPR/CMO *tweet* — not one
of the curated schemes — slips past the AI and is never cross-referenced.

This sweep closes that gap. For every recent TVK-era announcement-type incident
that isn't already flagged, it runs the keyword precedent search against the
WHOLE archive (pure DB, no AI-pool cost). Because the DMK archive ends at the
tenure boundary (2026-05-04) and the TVK govt began 2026-05-11, EVERY archive
match is by construction a DMK-predating precedent — the credit-steal signature.

Action ladder (thresholds tunable per call):
  - score >= auto_threshold   -> auto-mark is_credit_steal=true, category=
                                  credit_stealing, with the dated DMK precedent
                                  attached as original_credit (the receipt).
  - score >= review_threshold -> attach precedents + send to pending_review.
  - below                     -> ignore.

Run dry_run=True first to preview what WOULD be flagged before anything is
written / made public.
"""
from __future__ import annotations
import logging
from datetime import date, timedelta
from typing import Any

from app.config import settings
from app.database import get_db
from app.ingestion.archive_lookup import find_precedents, attach_evidence

logger = logging.getLogger(__name__)

# Categories where a TVK claim could be stealing DMK credit. Excludes pure
# failures (crime, civic_failure, power_cut, etc.) which can't be credit-steals.
ANNOUNCEMENT_CATS = {
    "new_initiative", "kept_promise", "partial_promise", "governance",
    "credit_stealing", "infrastructure", "welfare_scheme", "achievement",
}

# Keyword search is only a SHORTLIST — it is far too noisy to decide a public
# credit-steal accusation by itself (it pairs "Singappen Special Force" with
# "Green Tamil Nadu Mission" on generic word overlap). So any precedent above
# this floor is handed to an LLM judge, which makes the actual call.
SHORTLIST_SCORE = 0.25
# LLM-judge confidence gates (this is what auto-marking actually keys on):
AUTO_CONF = 0.75          # AI-confirmed, high confidence -> auto-mark (public)
REVIEW_CONF = 0.50        # AI-confirmed, medium -> human confirms first
MAX_AI_CALLS = 35         # free-tier / HF safety cap per run

_SRC_LABEL = {
    "dmk_website": "dmk.in", "cmo_tamil_nadu": "@CMOTamilnadu",
    "tn_dipr": "@TNDIPRNEWS", "manual": "archive",
}

_JUDGE_PROMPT = """You decide whether a TVK-government announcement (2026) is STEALING CREDIT for work the PREVIOUS DMK government (2021-2026) already did.

TVK ANNOUNCEMENT (current govt):
"{tvk}"

CANDIDATE DMK PRECEDENT (from the DMK 2021-2026 archive, dated {date}, source {src}):
"{dmk}"

A CREDIT-STEAL means the TVK item presents as NEW / its own achievement something that is substantially the SAME scheme or work the DMK precedent already launched or carried out.
It is NOT a credit-steal if: it is a different scheme; merely the same broad theme/sector; a failure, protest or criticism; routine governance; or the TVK item is genuinely new.
Be strict — when unsure, answer false. A wrong credit-steal accusation destroys this tool's credibility.

Output ONLY this JSON:
{{"is_credit_steal": true/false, "confidence": 0.0-1.0, "note": "<one line: exactly what overlaps, or why it is not a steal>"}}"""


def _judge(tvk_text: str, precedent: dict) -> dict | None:
    """LLM confirms whether the TVK item re-claims this specific DMK precedent.
    Returns the parsed verdict, or None if the AI pool is exhausted/unparseable."""
    import json
    import re
    from app.ingestion.ai_processor import llm_call_with_fallback
    raw = llm_call_with_fallback(
        [{"role": "user", "content": _JUDGE_PROMPT.format(
            tvk=tvk_text[:600],
            dmk=(precedent.get("title") or "")[:300],
            date=(precedent.get("announcement_date") or "")[:10],
            src=_SRC_LABEL.get(precedent.get("source"), precedent.get("source")),
        )}],
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


def _fetch_candidates(db, start_iso: str, page_size: int = 1000) -> list[dict]:
    """All TVK-era announcement-type incidents not already flagged as a
    credit-steal. Paginates past Supabase's 1000-row cap."""
    out: list[dict] = []
    page = 0
    while True:
        res = (db.table("incidents")
               .select("id, title, summary, category, incident_date, "
                       "is_credit_steal, status, source_urls")
               .gte("incident_date", start_iso)
               .in_("category", sorted(ANNOUNCEMENT_CATS))
               .neq("status", "rejected")
               .range(page * page_size, page * page_size + page_size - 1)
               .execute())
        batch = res.data or []
        out.extend(batch)
        if len(batch) < page_size:
            break
        page += 1
    return out


def sweep_credit_steals(
    *,
    days: int = 60,
    dry_run: bool = True,
    use_ai: bool = True,
    auto_conf: float = AUTO_CONF,
    review_conf: float = REVIEW_CONF,
    max_ai: int = MAX_AI_CALLS,
    limit: int = 400,
) -> dict[str, Any]:
    """Cross-check recent TVK announcements against the full DMK archive.

    Keyword search SHORTLISTS precedents; an LLM judge decides. With use_ai=
    False you get a keyword-only PREVIEW (shortlist + scores, no decisions) —
    never auto-mark from that, it is far too noisy.
    """
    db = get_db()
    dmk_end = settings.dmk_tenure_end_date.isoformat()
    floor = settings.govt_start_date.isoformat()
    since = (date.today() - timedelta(days=days)).isoformat()
    start = max(floor, since)

    candidates = _fetch_candidates(db, start)[:limit]
    out: dict[str, Any] = {
        "scanned": 0, "shortlisted": 0, "ai_calls": 0,
        "auto_marked": 0, "sent_to_review": 0, "ai_cleared": 0,
        "dry_run": dry_run, "use_ai": use_ai,
        "auto": [], "review": [], "shortlist_only": [],
    }

    for inc in candidates:
        if inc.get("is_credit_steal"):
            continue
        out["scanned"] += 1
        try:
            preds = find_precedents(inc["title"], inc.get("summary") or "", limit=5)
            preds = [p for p in preds
                     if (p.get("announcement_date") or "")[:10] <= dmk_end
                     and float(p.get("match_score") or 0) >= SHORTLIST_SCORE]
            if not preds:
                continue
            out["shortlisted"] += 1
            best = preds[0]
            rec = {
                "id": inc["id"], "title": inc["title"][:80],
                "category": inc.get("category"),
                "kw_score": float(best.get("match_score") or 0),
                "precedent": best.get("title", "")[:80],
                "precedent_date": (best.get("announcement_date") or "")[:10],
                "precedent_source": _SRC_LABEL.get(best.get("source"), best.get("source")),
            }

            # Keyword-only preview: collect the shortlist, make NO decisions.
            if not use_ai:
                out["shortlist_only"].append(rec)
                continue

            if out["ai_calls"] >= max_ai:
                out["shortlist_only"].append({**rec, "note": "AI cap reached — not judged this run"})
                continue

            out["ai_calls"] += 1
            verdict = _judge(f'{inc["title"]}. {inc.get("summary") or ""}', best)
            if not verdict:
                out["shortlist_only"].append({**rec, "note": "AI pool exhausted/unparseable"})
                continue

            conf = float(verdict.get("confidence") or 0)
            rec["ai_note"] = (verdict.get("note") or "")[:160]
            rec["ai_confidence"] = conf

            if not verdict.get("is_credit_steal"):
                out["ai_cleared"] += 1
                continue

            credit_line = (
                f'DMK precedent: "{(best.get("title") or "")[:140]}" '
                f'({(best.get("announcement_date") or "")[:10]}, '
                f'{_SRC_LABEL.get(best.get("source"), best.get("source"))})'
            )

            if conf >= auto_conf:
                out["auto"].append(rec)
                out["auto_marked"] += 1
                if not dry_run:
                    attach_evidence(inc["id"], preds[:3])
                    db.table("incidents").update({
                        "is_credit_steal": True,
                        "category": "credit_stealing",
                        "original_credit": credit_line,
                    }).eq("id", inc["id"]).execute()
                    logger.info("auto credit-steal: %s <- %s (AI %.2f)",
                                inc["title"][:50], credit_line[:60], conf)
            elif conf >= review_conf:
                out["review"].append(rec)
                out["sent_to_review"] += 1
                if not dry_run:
                    attach_evidence(inc["id"], preds[:3])
                    db.table("incidents").update({
                        "status": "pending_review",
                        "original_credit": credit_line,
                    }).eq("id", inc["id"]).execute()
            else:
                out["ai_cleared"] += 1
        except Exception:
            logger.exception("credit-steal cross-check failed for %s", inc.get("id"))

    return out
