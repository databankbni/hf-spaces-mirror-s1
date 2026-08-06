"""Pro-TVK propaganda + counter-narrative tracking.

Closes the structural blind spot the user named: the incumbency meter
measures DOCUMENTED accountability failures, not what TN voters
actually see. This router exposes the OTHER side of the information
ecosystem — manufactured / misleading / fake content amplified by the
TVK ecosystem — and the asymmetry between that and the corrections.

Endpoints
---------
GET  /api/propaganda/             — list events, paginated
GET  /api/propaganda/summary      — top-line stats for the dashboard widget
                                    (totals, asymmetry ratio, recent debunks)
POST /api/propaganda/             — admin-create a new event
PATCH/api/propaganda/{id}         — admin-update (mark debunked, add reach, etc.)
"""
from __future__ import annotations
from datetime import date, datetime, timezone, timedelta
from typing import Optional, Any
from fastapi import APIRouter, HTTPException, Header, Query
from pydantic import BaseModel, Field
from app.database import get_db
from app.config import settings

router = APIRouter(prefix="/propaganda", tags=["propaganda"])


def _fetch_all(make_query, page_size: int = 1000):
    """Page past Supabase's 1000-row default cap so full-table counts stay
    accurate as the incidents corpus grows. make_query() returns a fresh
    query builder (filters applied, no range/execute)."""
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


class PropagandaCreate(BaseModel):
    title: str
    description: Optional[str] = None
    propaganda_type: str = Field(..., description="manufactured_achievement | dubbed_footage | deepfake | paid_trending | misleading_edit | fake_quote | meme_glorification | astroturfing | misattributed_event | other")
    favoring: str = "TVK"
    platform: Optional[str] = None
    propaganda_url: Optional[str] = None
    reach_estimate: Optional[int] = None
    likes: Optional[int] = None
    shares: Optional[int] = None
    comments: Optional[int] = None
    debunk_url: Optional[str] = None
    debunk_source: Optional[str] = None
    debunk_reach_estimate: Optional[int] = None
    first_seen: Optional[date] = None
    incident_date: Optional[date] = None
    status: str = "active"
    related_incident_id: Optional[str] = None
    tags: list[str] = []
    source_urls: list[str] = []
    notes: Optional[str] = None


class PropagandaUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    propaganda_type: Optional[str] = None
    platform: Optional[str] = None
    propaganda_url: Optional[str] = None
    reach_estimate: Optional[int] = None
    likes: Optional[int] = None
    shares: Optional[int] = None
    debunk_url: Optional[str] = None
    debunk_source: Optional[str] = None
    debunk_reach_estimate: Optional[int] = None
    debunked_at: Optional[datetime] = None
    status: Optional[str] = None
    tags: Optional[list[str]] = None
    source_urls: Optional[list[str]] = None
    notes: Optional[str] = None


def _verify_admin(secret: Optional[str]) -> None:
    if not secret or secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")


def _incident_to_propaganda(inc: dict) -> dict:
    """Normalise a fake_news/propaganda INCIDENT (e.g. a Telegram-submitted
    fake claim) into the propaganda-card shape so it shows on the same page
    as scraper-sourced propaganda_events. Without this, manually-submitted
    fake claims land in `incidents` and never appear on the propaganda page."""
    urls = inc.get("source_urls") or []
    return {
        "id": inc["id"],
        "title": inc.get("title"),
        "description": inc.get("summary"),
        "propaganda_type": "other",
        # fake_news incidents are overwhelmingly pro-TVK manufactured content;
        # default accordingly (admin can refine on the propaganda_events side).
        "favoring": "TVK",
        "platform": None,
        "first_seen": inc.get("incident_date"),
        "incident_date": inc.get("incident_date"),
        "reach_estimate": None,
        "debunk_reach_estimate": None,
        "propaganda_url": urls[0] if urls else None,
        "debunk_url": urls[0] if urls else None,
        "debunk_source": None,
        "status": "debunked" if inc.get("status") == "approved" else "active",
        "tags": [inc.get("category")] if inc.get("category") else [],
        "source_urls": urls,
        "origin": "incident",   # lets the frontend distinguish if it wants to
    }


@router.get("/", response_model=list[dict])
async def list_propaganda(
    status: Optional[str] = Query(None, description="active | debunked | retracted | organic"),
    propaganda_type: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
):
    db = get_db()
    rows: list[dict] = []

    # Pool 1: curated/scraped propaganda_events
    try:
        q = db.table("propaganda_events").select("*").order("first_seen", desc=True).limit(limit)
        if status:
            q = q.eq("status", status)
        if propaganda_type:
            q = q.eq("propaganda_type", propaganda_type)
        rows.extend(q.execute().data or [])
    except Exception:
        pass

    # Pool 2: fake_news / propaganda INCIDENTS (manual + Telegram submissions).
    # These otherwise never reach this page. Only when no propaganda_type
    # filter is set (incidents don't carry that field) and not filtering to
    # organic-only.
    if propaganda_type is None and status != "organic":
        try:
            inc = (
                db.table("incidents")
                .select("id, title, summary, category, status, incident_date, source_urls")
                .in_("category", ["fake_news", "propaganda", "propaganda_event"])
                .in_("status", ["approved", "press_verified", "single_source", "pending_review"])
                .order("incident_date", desc=True)
                .limit(limit)
                .execute()
                .data
                or []
            )
            rows.extend(_incident_to_propaganda(x) for x in inc)
        except Exception:
            pass

    # Merge + sort by first_seen desc; cap at limit.
    rows.sort(key=lambda r: (r.get("first_seen") or r.get("incident_date") or ""), reverse=True)
    return rows[:limit]


@router.get("/summary")
async def propaganda_summary():
    """Top-line numbers the dashboard widget displays.

    Compares:
      - TVK-era accountability events we've documented (incidents table,
        status='approved', incident_date>=2026-05-11)
      - TVK-era propaganda events tracked (this table)
      - Reach asymmetry (propaganda views vs debunk views)
      - Recent debunks (last 7 days, with sources)
    """
    db = get_db()
    govt_start = "2026-05-11"

    # Accountability side — TVK-era incidents.
    #
    # We expose TWO numbers, both honest:
    #   accountability_events_documented  — every approved TVK-era incident
    #       (the broad "what the pipeline has surfaced" total).
    #   accountability_verified           — the STRICT headline: only
    #       press/multi-source/admin-VERIFIED incidents in genuine FAILURE
    #       categories, plus manifesto promises actually marked broken.
    #       This is the un-debunkable number — every item is both a real
    #       failure (not a neutral political event) and independently
    #       verified (not single-source / pending).
    #
    # Categories that count as governance FAILURES (neutral ones like
    # political_event / new_initiative / kept_promise, and the propaganda
    # pool fake_news/propaganda which is counted on the other side, are
    # deliberately excluded).
    FAILURE_CATEGORIES = {
        "corruption", "murders", "sexual_assault", "crimes_women_kids",
        "power_cut", "eb_failure", "alcohol_menace", "honour_killing",
        "police_excess", "broken_promise", "attack_on_press",
        "custodial_death", "civic_failure", "crowd_management_failure",
        "youth_targeting", "censorship", "governance",
    }
    # STRICT verified — excludes single_source (auto-published-but-unconfirmed)
    # so the word "verified" in the label is literally true.
    STRICT_VERIFIED = {"multi_source_verified", "press_verified", "admin_verified"}
    try:
        acc_rows = _fetch_all(lambda: db.table("incidents")
            .select("id, category, verification_status, ai_raw")
            .eq("status", "approved")
            .gte("incident_date", govt_start))
        accountability_events = len(acc_rows)

        def _is_failure(inc: dict) -> bool:
            cats = {inc.get("category")}
            raw = inc.get("ai_raw") or {}
            if isinstance(raw, dict):
                cats |= {str(t) for t in (raw.get("tags_extra") or []) if isinstance(t, str)}
            return bool(cats & FAILURE_CATEGORIES)

        verified_failures = sum(
            1 for inc in acc_rows
            if inc.get("verification_status") in STRICT_VERIFIED and _is_failure(inc)
        )
    except Exception:
        accountability_events = 0
        verified_failures = 0

    # Manifesto promises actually marked broken (NOT pending/partial).
    try:
        broken_promises = (
            db.table("promises").select("id", count="exact")
            .eq("status", "broken").execute()
        ).count or 0
    except Exception:
        broken_promises = 0

    accountability_verified = verified_failures + broken_promises

    # Propaganda side
    try:
        props = (
            db.table("propaganda_events")
            .select("id, status, reach_estimate, debunk_reach_estimate, first_seen, "
                    "propaganda_type, title, debunk_url, debunk_source, propaganda_url")
            .gte("first_seen", govt_start)
            .execute()
        )
        rows = props.data or []
    except Exception:
        rows = []

    total_propaganda = len(rows)
    confirmed_fake = sum(1 for r in rows if r.get("status") in ("debunked", "active"))
    organic = sum(1 for r in rows if r.get("status") == "organic")

    # Reach math — sum everything we have non-NULL data for
    propaganda_reach = sum((r.get("reach_estimate") or 0) for r in rows)
    debunk_reach = sum((r.get("debunk_reach_estimate") or 0) for r in rows)
    # Asymmetry ratio. Floor at 1 so we don't show "infinity" when no
    # debunk reach is recorded — instead we show "no measurable debunk reach"
    asymmetry_ratio: float | None = None
    if debunk_reach > 0 and propaganda_reach > 0:
        asymmetry_ratio = round(propaganda_reach / debunk_reach, 1)

    # Recent debunks (most useful for users to scan)
    recent_cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    recent_debunks = [
        {
            "id": r["id"],
            "title": r.get("title"),
            "propaganda_type": r.get("propaganda_type"),
            "first_seen": r.get("first_seen"),
            "propaganda_url": r.get("propaganda_url"),
            "debunk_url": r.get("debunk_url"),
            "debunk_source": r.get("debunk_source"),
            "reach_estimate": r.get("reach_estimate"),
            "debunk_reach_estimate": r.get("debunk_reach_estimate"),
        }
        for r in rows
        if r.get("first_seen") and r["first_seen"] >= recent_cutoff
    ][:5]

    # Type breakdown for the chart
    type_counts: dict[str, int] = {}
    for r in rows:
        t = r.get("propaganda_type") or "other"
        type_counts[t] = type_counts.get(t, 0) + 1

    # Press-reported fake news — separate pool from propaganda_events.
    # These are incidents auto-tagged with category=fake_news (or having
    # fake_news in ai_raw.tags_extra) by the AI from press/reddit
    # ingestion. They cover the same beat as propaganda_events but
    # arrive via a different pipeline: press reports of misleading
    # claims that didn't get manually curated with reach data. We
    # surface them in the same widget so admins / readers see ONE fake-
    # content story, not two contradictory numbers.
    try:
        all_incidents = _fetch_all(lambda: db.table("incidents")
            .select("id, title, source_urls, incident_date, "
                    "verification_status, category, ai_raw")
            .eq("status", "approved")
            .gte("incident_date", govt_start))
    except Exception:
        all_incidents = []

    fake_news_incidents = []
    for inc in all_incidents:
        cat = (inc.get("category") or "").lower()
        raw = inc.get("ai_raw") or {}
        tags = []
        if isinstance(raw, dict):
            tags = [str(t).lower() for t in (raw.get("tags_extra") or [])
                    if isinstance(t, str)]
        if cat == "fake_news" or "fake_news" in tags:
            fake_news_incidents.append({
                "id":      inc["id"],
                "title":   inc.get("title"),
                "url":     (inc.get("source_urls") or [None])[0],
                "incident_date": inc.get("incident_date"),
                "verification_status": inc.get("verification_status"),
            })
    press_reported_fake_news = len(fake_news_incidents)
    # Newest first, top 5 for the widget list
    fake_news_incidents.sort(
        key=lambda x: x.get("incident_date") or "", reverse=True
    )
    fake_news_incidents = fake_news_incidents[:5]

    return {
        "accountability_events_documented":  accountability_events,
        "accountability_verified":           accountability_verified,
        "verified_failures":                 verified_failures,
        "broken_promises":                   broken_promises,
        "propaganda_events_tracked":         total_propaganda,
        "confirmed_fake_or_active":          confirmed_fake,
        "organic_high_volume":               organic,
        "propaganda_reach_total":            propaganda_reach,
        "debunk_reach_total":                debunk_reach,
        "asymmetry_ratio":                   asymmetry_ratio,
        "type_breakdown":                    type_counts,
        "recent_debunks":                    recent_debunks,
        # Press-reported fake-news pool (was a separate top-level StatCard
        # on the main dashboard; folded in here for a single coherent story)
        "press_reported_fake_news_count":    press_reported_fake_news,
        "press_reported_fake_news_recent":   fake_news_incidents,
        # Combined for at-a-glance display: curated propaganda + press-reported
        "total_fake_or_misleading":          confirmed_fake + press_reported_fake_news,
        "honest_disclaimer": (
            "These numbers reflect propaganda we've TRACKED, not the full volume "
            "circulating. The real asymmetry is almost certainly larger — most pro-TVK "
            "manipulation never reaches a debunk pipeline. Treat this widget as a "
            "minimum-floor estimate, not a comprehensive measurement."
        ),
    }


@router.post("/", response_model=dict, status_code=201)
async def create_propaganda(body: PropagandaCreate, x_admin_secret: Optional[str] = Header(None)):
    _verify_admin(x_admin_secret)
    db = get_db()
    payload = body.model_dump(exclude_none=True)
    # Convert date objects to iso strings
    for k in ("first_seen", "incident_date"):
        if k in payload and hasattr(payload[k], "isoformat"):
            payload[k] = payload[k].isoformat()
    res = db.table("propaganda_events").insert(payload).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Insert failed")
    return res.data[0]


@router.patch("/{event_id}", response_model=dict)
async def update_propaganda(event_id: str, body: PropagandaUpdate, x_admin_secret: Optional[str] = Header(None)):
    _verify_admin(x_admin_secret)
    db = get_db()
    payload = body.model_dump(exclude_none=True)
    if "debunked_at" in payload and hasattr(payload["debunked_at"], "isoformat"):
        payload["debunked_at"] = payload["debunked_at"].isoformat()
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    res = db.table("propaganda_events").update(payload).eq("id", event_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Not found")
    return res.data[0]
