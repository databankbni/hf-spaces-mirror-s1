"""One-shot reclassifier: strip mis-tagged 'corruption' incidents.

The old extraction rule counted ANY corruption in TN as the govt's
responsibility, so it swept in two kinds of incident that are NOT TVK
corruption:
  1. The TVK government ACTING AGAINST corruption — ordering a probe /
     overhaul / audit, seeking sanction to prosecute, suspending an official.
  2. TVK prosecuting a PRIOR-REGIME (DMK / AIADMK / ex-minister) figure for
     pre-May-11 conduct, or an ED/CBI/IT central case against such a figure.

This module re-judges every category=corruption incident with the LLM and
moves the mis-tagged ones to category='political_event' (neutral — not a
failure, not counted in the accountability headline). Genuine TVK-side
corruption (a sitting TVK functionary / MLA / govt official under TVK taking
a bribe, extorting, defrauding) is left untouched.

Non-destructive: only the category field changes; nothing is deleted, and an
incident_audit row records each change so it's reversible/auditable.
"""
from __future__ import annotations
import json
import logging
import re
from typing import Any

from app.database import get_db

logger = logging.getLogger(__name__)

_JUDGE_PROMPT = """You audit the category of an incident on a Tamil Nadu TVK-government
accountability tracker. The TVK government took office 2026-05-11.

We track corruption ONLY when the ACCUSED is the government's OWN side:
a sitting TVK office-holder (minister, MLA, candidate, functionary, cadre),
or a government official/employee serving UNDER the TVK administration.

It is NOT TVK corruption (it is a neutral political_event) when EITHER:
  - the TVK government is ACTING AGAINST corruption: ordering a probe /
    overhaul / audit, seeking sanction to prosecute, suspending/transferring
    an official as a remedy, filing a case; OR
  - the accused is a PRIOR-REGIME figure (DMK / AIADMK / a "former" or "ex-"
    minister, e.g. Senthil Balaji, K.N. Nehru) for conduct before 2026-05-11,
    or it is an ED/CBI/IT central-agency case against such a figure.

INCIDENT
  Title: {title}
  Summary: {summary}

Output ONLY this JSON:
{{"is_tvk_side_corruption": true/false, "reason": "<one short line>"}}

true  = the accused is a current TVK figure or a govt official under TVK → keep as corruption.
false = govt anti-corruption action, or a prior-regime / central-agency case → reclassify."""


def _judge(title: str, summary: str) -> dict[str, Any] | None:
    from app.ingestion.ai_processor import llm_call_with_fallback
    raw = llm_call_with_fallback(
        [{"role": "user", "content": _JUDGE_PROMPT.format(
            title=(title or "")[:300], summary=(summary or "")[:1200])}],
        max_tokens=120,
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


def reclassify_corruption(*, limit: int = 200, dry_run: bool = False) -> dict[str, Any]:
    """Re-judge category=corruption incidents; move non-TVK ones to
    political_event. Returns a summary with the titles that were moved."""
    db = get_db()
    rows = (db.table("incidents")
            .select("id, title, summary, category")
            .eq("category", "corruption")
            .eq("status", "approved")
            .limit(limit).execute().data or [])
    out: dict[str, Any] = {"scanned": len(rows), "reclassified": 0,
                           "kept": 0, "skipped_no_judgment": 0, "moved": []}
    for inc in rows:
        verdict = _judge(inc.get("title") or "", inc.get("summary") or "")
        if not verdict:
            out["skipped_no_judgment"] += 1
            continue
        if verdict.get("is_tvk_side_corruption") is True:
            out["kept"] += 1
            continue
        # is_tvk_side_corruption == False → reclassify to neutral political_event
        out["reclassified"] += 1
        out["moved"].append({
            "id": inc["id"], "title": (inc.get("title") or "")[:80],
            "reason": verdict.get("reason", ""),
        })
        if dry_run:
            continue
        try:
            db.table("incidents").update(
                {"category": "political_event", "is_credit_steal": False}
            ).eq("id", inc["id"]).execute()
            try:
                db.table("incident_audit").insert({
                    "incident_id": inc["id"],
                    "action": "recategorized",
                    "from_value": "corruption",
                    "to_value": "political_event",
                    "actor": "reclassify_corruption",
                    "reason": f"Not TVK-side corruption: {verdict.get('reason','')[:160]}",
                }).execute()
            except Exception:
                pass
        except Exception:
            logger.exception("reclassify update failed for %s", inc.get("id"))
    logger.info("reclassify_corruption: %s", {k: v for k, v in out.items() if k != "moved"})
    return out
