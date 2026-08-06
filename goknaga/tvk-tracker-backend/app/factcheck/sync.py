"""Normalise every debunk into the canonical `fact_checks` ledger.

Maps the existing scattered stores — propaganda_events (debunked fakes, incl.
YouTurn imports) and incidents.is_credit_steal (credit-steals) — into one
protocol-compliant `fact_checks` row each (FACT_CHECK_PROTOCOL.md). Idempotent:
upserts on (origin, origin_id), so it can run as a backfill AND on a schedule.

Going forward the YouTurn fetcher / Copilot / manual adds keep writing their own
stores; this sync mirrors them into the canonical ledger with a verdict +
evidence tier + conceded points. (A later pass can have writers target
fact_checks directly; sync is the low-risk bridge that unifies them now.)
"""
from __future__ import annotations
import logging
from app.database import get_db

logger = logging.getLogger(__name__)

# propaganda_type -> verdict (Protocol A)
_PT_VERDICT = {
    "misleading_edit": "misleading",
    "dubbed_footage": "fabricated",
    "deepfake": "fabricated",
    "fake_quote": "fabricated",
    # Old/unrelated footage passed off as a current TN event = misleading
    # recontextualisation, NOT stolen credit. Genuine credit-steals (real DMK
    # work claimed as TVK's) come from the is_credit_steal pool, and an explicit
    # credit/steal tag still upgrades a propaganda row below.
    "misattributed_event": "misleading",
    "meme_glorification": "misleading",
    "paid_trending": "misleading",
    "astroturfing": "misleading",
    "manufactured_achievement": "false",
    "other": "false",
}


def _verdict_for_propaganda(pe: dict) -> str:
    tags = [str(t).lower() for t in (pe.get("tags") or [])]
    title = (pe.get("title") or "").lower()
    if any("credit" in t or "steal" in t for t in tags) or "credit-steal" in title:
        return "credit_steal"
    if "false_first" in tags or "manufactured_first" in tags:
        return "manufactured_first"
    return _PT_VERDICT.get((pe.get("propaganda_type") or "").lower(), "false")


def _tier_for_source(source: str, urls) -> int:
    """Evidence tier 1 (primary) .. 5 (social-only). Protocol B."""
    s = (source or "").lower()
    if any(w in s for w in ("go ", "gazette", "government order", "wayback", "archive",
                            "rajya sabha", "assembly", "white paper", "ncrb", "primary", "document")):
        return 1
    if any(w in s for w in ("youturn", "newsmeter", "factly", "alt news", "boom", "the hindu",
                            "indian express", "times of india", "dt next", "the federal", "etv",
                            "deccan", "press", "fact-check", "fact check")):
        return 3
    if "social" in s or "x user" in s or "@" in s:
        return 4
    return 3 if urls else 4


def _conf_for_tier(tier: int, fallback) -> float:
    base = {1: 0.95, 2: 0.9, 3: 0.8, 4: 0.6, 5: 0.4}.get(tier, 0.7)
    try:
        return round(min(float(fallback), 0.99), 2) if fallback else base
    except Exception:
        return base


def _row_from_propaganda(pe: dict) -> dict:
    urls = pe.get("source_urls") or []
    src = pe.get("debunk_source") or ""
    tier = _tier_for_source(src, urls)
    # `notes` carries hand-written honest caveats for our curated rows, but for
    # YouTurn auto-imports it is just ingestion metadata ("Auto-ingested from
    # YouTurn GraphQL... Verdict=fake; views=524") — never surface that as a
    # conceded point. These verdicts mirror YouTurn's published rating.
    is_youturn = src.lower().startswith("youturn")
    notes = pe.get("notes")
    concedes = None if (is_youturn or (notes or "").startswith("Auto-ingested")) else notes
    what_would_change = (
        "Mirrors YouTurn's published fact-check; would change if YouTurn corrects "
        "or retracts it." if is_youturn else None
    )
    return {
        "claim": (pe.get("title") or "")[:500],
        "claim_summary": (pe.get("title") or "")[:200],
        "verdict": _verdict_for_propaganda(pe),
        "evidence_tier": tier,
        "confidence": _conf_for_tier(tier, pe.get("reach_estimate") and None),
        "favoring": pe.get("favoring"),
        "concedes": concedes,
        "what_would_change": what_would_change,
        "debunk_source": pe.get("debunk_source"),
        "debunk_url": pe.get("debunk_url"),
        "sources": urls,
        "tags": pe.get("tags") or [],
        "first_seen": pe.get("first_seen"),
        "status": "published",
        "origin": "youturn" if (pe.get("debunk_source") or "").lower().startswith("youturn") else "propaganda_event",
        "origin_id": pe.get("id"),
    }


def _row_from_credit_steal(inc: dict) -> dict:
    raw = inc.get("ai_raw") or {}
    raw = raw if isinstance(raw, dict) else {}
    vs = (inc.get("verification_status") or "").lower()
    tier = 1 if "multi_source" in vs else (3 if "press" in vs else 4)
    urls = inc.get("source_urls") or []
    return {
        "claim": (inc.get("title") or "")[:500],
        "claim_summary": (inc.get("title") or "")[:200],
        "verdict": "credit_steal",
        "evidence_tier": tier,
        "confidence": _conf_for_tier(tier, inc.get("ai_confidence")),
        "favoring": "TVK",
        "concedes": raw.get("honesty_caveats") or inc.get("original_credit"),
        "what_would_change": None,
        "debunk_source": "TVK Files verification",
        "debunk_url": (urls[0] if urls else None),
        "sources": urls,
        "tags": (raw.get("tags_extra") or []) + ["credit_steal"],
        "first_seen": inc.get("incident_date"),
        "status": "published",
        "origin": "credit_steal",
        "origin_id": inc.get("id"),
    }


def _existing_map(db) -> dict:
    """(origin, origin_id) -> id, so sync stays idempotent without relying on a
    PostgREST ON CONFLICT arbiter (the unique index is partial, which PostgREST
    can't target). Paged past the 1000-row cap."""
    out: dict = {}
    offset = 0
    while True:
        batch = (db.table("fact_checks").select("id,origin,origin_id")
                 .range(offset, offset + 999).execute().data or [])
        for r in batch:
            out[(r.get("origin"), r.get("origin_id"))] = r["id"]
        if len(batch) < 1000:
            break
        offset += 1000
    return out


def _upsert(db, rows: list[dict], existing: dict) -> dict:
    ins = upd = err = 0
    for r in rows:
        key = (r.get("origin"), r.get("origin_id"))
        try:
            if key in existing:
                db.table("fact_checks").update(r).eq("id", existing[key]).execute()
                upd += 1
            else:
                res = db.table("fact_checks").insert(r).execute()
                if res.data:
                    existing[key] = res.data[0]["id"]
                ins += 1
        except Exception as e:
            err += 1
            logger.warning("fact_checks write failed (%s): %s", r.get("origin_id"), e)
    return {"inserted": ins, "updated": upd, "errors": err}


def sync_all() -> dict:
    """Backfill / refresh the fact_checks ledger from all sources. Idempotent."""
    db = get_db()
    existing = _existing_map(db)
    counts: dict = {}

    props = (db.table("propaganda_events").select("*").eq("status", "debunked").execute().data or [])
    counts["propaganda"] = _upsert(db, [_row_from_propaganda(p) for p in props], existing)

    # Credit-steals are flagged by the boolean column (matches the incidents
    # route: /api/incidents/?is_credit_steal=true), NOT by category alone.
    steals = (db.table("incidents").select(
        "id,title,source_urls,verification_status,ai_confidence,original_credit,incident_date,ai_raw")
        .eq("is_credit_steal", True).eq("status", "approved").execute().data or [])
    counts["credit_steal"] = _upsert(db, [_row_from_credit_steal(s) for s in steals], existing)

    counts["total_in_ledger"] = db.table("fact_checks").select("id", count="exact").execute().count
    logger.info("fact_checks sync: %s", counts)
    return counts
