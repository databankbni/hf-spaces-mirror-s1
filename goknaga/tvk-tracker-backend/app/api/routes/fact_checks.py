"""The canonical fact-check ledger (FACT_CHECK_PROTOCOL.md).

Serves the `fact_checks` table — the ONE place every published verdict lives,
each carrying a verdict, an evidence tier, the conceded points and
what-would-change. Populated by app.factcheck.sync (mirrors propaganda_events +
credit-steals) and, going forward, the Copilot / manual adds.

Endpoints
---------
GET  /api/fact-checks/          — list published verdicts (filter by verdict/favoring/tier)
GET  /api/fact-checks/summary   — counts by verdict + evidence-tier mix for the page header
POST /api/fact-checks/sync      — admin: re-run the backfill/refresh from all sources
"""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, HTTPException, Header, Query
from app.database import get_db
from app.config import settings

router = APIRouter(prefix="/fact-checks", tags=["fact-checks"])


def _fetch_all(make_query, page_size: int = 1000):
    rows: list = []
    offset = 0
    while True:
        res = make_query().range(offset, offset + page_size - 1).execute()
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return rows


@router.get("/", response_model=list[dict])
async def list_fact_checks(
    verdict: Optional[str] = Query(None),
    favoring: Optional[str] = Query(None),
    max_tier: int = Query(4, ge=1, le=5, description="Only return verdicts at this evidence tier or stronger"),
    limit: int = Query(200, ge=1, le=1000),
):
    db = get_db()
    try:
        rows = _fetch_all(lambda: (
            db.table("fact_checks").select("*")
            .eq("status", "published")
            .lte("evidence_tier", max_tier)
            .order("evidence_tier", desc=False)
            .order("first_seen", desc=True)
        ))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"fact_checks read failed: {e}")
    if verdict:
        rows = [r for r in rows if r.get("verdict") == verdict]
    if favoring:
        rows = [r for r in rows if (r.get("favoring") or "").upper() == favoring.upper()]
    return rows[:limit]


@router.get("/summary")
async def fact_checks_summary():
    db = get_db()
    try:
        rows = _fetch_all(lambda: (
            db.table("fact_checks").select("verdict, evidence_tier, favoring, confidence")
            .eq("status", "published")
        ))
    except Exception:
        rows = []

    by_verdict: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    by_favoring: dict[str, int] = {}
    for r in rows:
        v = r.get("verdict") or "other"
        by_verdict[v] = by_verdict.get(v, 0) + 1
        t = str(r.get("evidence_tier") or "?")
        by_tier[t] = by_tier.get(t, 0) + 1
        f = (r.get("favoring") or "unattributed")
        by_favoring[f] = by_favoring.get(f, 0) + 1

    # Share at primary-source strength (tier 1-2) — the credibility headline.
    strong = sum(1 for r in rows if (r.get("evidence_tier") or 5) <= 2)

    return {
        "total": len(rows),
        "by_verdict": by_verdict,
        "by_evidence_tier": by_tier,
        "by_favoring": by_favoring,
        "primary_sourced": strong,
        "honest_disclaimer": (
            "Every verdict here meets the Fact-Check Protocol: an evidence tier is "
            "stated, the other side's true points are conceded, and what-would-change "
            "is named. Tier-5 (social-media-only) claims are held, not published."
        ),
    }


@router.post("/sync")
async def sync_fact_checks(x_admin_secret: Optional[str] = Header(None)):
    if not x_admin_secret or x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    from app.factcheck.sync import sync_all
    try:
        return sync_all()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"sync failed: {e}")
