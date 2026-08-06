from fastapi import APIRouter, HTTPException, Query, Header
from app.database import get_db
from app.models.schemas import IncidentCreate, IncidentUpdate
from app.config import settings
from typing import Optional

router = APIRouter(prefix="/incidents", tags=["incidents"])


# Known-outlet → credibility-tier map used as the URL-host fallback when
# a source URL hasn't been written to the `sources` table (typically
# happens for directly-seeded incidents that skipped the AI ingestion
# path). Keeps user-facing source bylines honest: instead of "unknown",
# they see "The Hindu · established press".
_HOST_OUTLET_MAP: dict[str, tuple[str, str]] = {
    # (host_substring): (display_name, credibility_tier)
    "thehindu":            ("The Hindu",            "established_press"),
    "thefederal":          ("The Federal",          "established_press"),
    "tribuneindia":        ("Tribune India",        "established_press"),
    "theweek":             ("The Week",             "established_press"),
    "india.com":           ("India.com",            "established_press"),
    "business-standard":   ("Business Standard",    "established_press"),
    "deccanherald":        ("Deccan Herald",        "established_press"),
    "deccanchronicle":     ("Deccan Chronicle",     "established_press"),
    "newindianexpress":    ("New Indian Express",   "established_press"),
    "newsminute":          ("The News Minute",      "established_press"),
    "thenewsminute":       ("The News Minute",      "established_press"),
    "magzter":             ("New Indian Express",   "established_press"),
    "livelaw":             ("LiveLaw",              "established_press"),
    "barandbench":         ("Bar and Bench",        "established_press"),
    "outlookindia":        ("Outlook India",        "established_press"),
    "hindustanherald":     ("Hindustan Herald",     "online_native"),
    "tamilspark":          ("Tamil Spark",          "regional_press"),
    "newsmeter":           ("NewsMeter",            "online_native"),
    "boomlive":            ("BOOM Live",            "online_native"),
    "altnews":             ("Alt News",             "online_native"),
    "logicallyfacts":      ("Logically Facts",      "online_native"),
    "factly":              ("Factly",               "online_native"),
    "vishvasnews":         ("Vishvas News",         "online_native"),
    "dtnext":              ("DT Next",              "regional_press"),
    "polimer":             ("Polimer News",         "regional_press"),
    "puthiyathalaimurai":  ("Puthiya Thalaimurai",  "regional_press"),
    "vikatan":             ("Vikatan",              "regional_press"),
    "cartoq":              ("Cartoq",               "online_native"),
    "siasat":              ("Siasat",               "online_native"),
    "autocarpro":          ("Autocar Professional", "online_native"),
    "themachinemaker":     ("Machine Maker",        "online_native"),
    "volvobuses":          ("Volvo Buses (press release)", "primary"),
    "oneindia":            ("OneIndia",             "online_native"),
    "newsx":               ("NewsX",                "online_native"),
    "lawbeat":             ("LawBeat",              "online_native"),
    "tvkvijay":            ("TVK Manifesto",        "primary"),
    "tn.gov.in":           ("TN Govt",              "primary"),
    "tnpsc":               ("TNPSC",                "primary"),
    "ncrb":                ("NCRB",                 "primary"),
    "niti.gov":            ("NITI Aayog",           "primary"),
    "x.com":               ("X (tweet)",            "social_media"),
    "twitter.com":         ("Twitter",              "social_media"),
    "reddit.com":          ("Reddit",               "social_media"),
    "youtube.com":         ("YouTube",              "social_media"),
    "youtu.be":            ("YouTube",              "social_media"),
    "instagram.com":       ("Instagram",            "social_media"),
    "facebook.com":        ("Facebook",             "social_media"),
    "news.google.com":     ("Google News",          "anonymous_social"),
}


def _outlet_from_url(url: str) -> tuple[str, str]:
    """Derive (outlet_display_name, credibility_tier) from a URL.

    Used as the fallback when a source URL hasn't been written to the
    sources table. Honours the principle that EVERY source visible on
    the dashboard must have a recognisable label, not a bare 'unknown'.
    """
    try:
        host = url.split("//", 1)[1].split("/", 1)[0].lower()
        host = host.removeprefix("www.").removeprefix("amp.")
    except (IndexError, AttributeError):
        return ("source", "unknown")
    # Check known outlets first (substring match against host)
    for needle, (name, tier) in _HOST_OUTLET_MAP.items():
        if needle in host:
            return (name, tier)
    # Generic fallback: second-level domain titlecased
    parts = host.split(".")
    if len(parts) >= 2:
        return (parts[-2].title(), "unknown")
    return (host.title() or "source", "unknown")


def _enrich_sources(db, incidents: list[dict]) -> list[dict]:
    """Attach outlet info + credibility tier to each incident's source_urls.

    The IN() call must be CHUNKED — Supabase/PostgREST has an ~8KB
    query-string limit, and many URLs (especially Reddit comment links
    with Tamil-script paths and Twitter status URLs) push us over the
    edge somewhere around 50-75 incidents. Chunking at 30 URLs per
    fetch keeps every request well under the limit no matter how many
    incidents are being enriched at once.

    Fallback: when a URL isn't in the sources table (typical for
    directly-seeded rows), derive the outlet name from the URL host
    via _outlet_from_url() so the user never sees a bare 'unknown'
    on the dashboard.
    """
    if not incidents:
        return incidents
    all_urls = list({u for inc in incidents for u in (inc.get("source_urls") or [])})
    if not all_urls:
        return incidents
    source_lookup: dict[str, dict] = {}
    CHUNK = 30
    for start in range(0, len(all_urls), CHUNK):
        chunk = all_urls[start:start + CHUNK]
        try:
            res = (
                db.table("sources")
                .select("url,outlet,credibility_tier,title")
                .in_("url", chunk)
                .execute()
            )
            for s in (res.data or []):
                source_lookup[s["url"]] = s
        except Exception:
            # Single-chunk failure should not break the whole list response
            continue
    for inc in incidents:
        sources_out: list[dict] = []
        for u in (inc.get("source_urls") or []):
            if u in source_lookup:
                sources_out.append(source_lookup[u])
            else:
                outlet, tier = _outlet_from_url(u)
                sources_out.append({
                    "url": u,
                    "outlet": outlet,
                    "credibility_tier": tier,
                })
        inc["sources"] = sources_out
    return incidents


def _compute_visibility(incidents: list[dict]) -> list[dict]:
    """Attach a `visibility_score` + `visibility_label` to each incident.

    The score answers: "If a TVK supporter scrolling Instagram all day
    encountered nothing about this — would that be normal?" High score
    means mainstream press covered it (likely visible to TVK base too).
    Low score means only opposition / fringe coverage (almost certainly
    invisible to TVK supporters).

    Categories of `credibility_tier` on each source:
      primary, established_press, regional_press -> "mainstream"
      online_native                              -> "alternative press"
      social_media, anonymous_social             -> "social only"

    Score scale:
      3 = HIGH      — 2+ mainstream press outlets
      2 = MEDIUM    — 1 mainstream outlet (visible but not amplified)
      1 = LOW       — only alternative press / fringe Tamil outlets
      0 = INVISIBLE — only social media, no press coverage at all
    """
    MAINSTREAM = {"primary", "established_press", "regional_press"}
    ALTERNATIVE = {"online_native"}
    for inc in incidents:
        sources = inc.get("sources") or []
        mainstream_count = sum(
            1 for s in sources
            if (s.get("credibility_tier") or "") in MAINSTREAM
        )
        alt_count = sum(
            1 for s in sources
            if (s.get("credibility_tier") or "") in ALTERNATIVE
        )
        if mainstream_count >= 2:
            inc["visibility_score"] = 3
            inc["visibility_label"] = "High — mainstream press covered"
        elif mainstream_count == 1:
            inc["visibility_score"] = 2
            inc["visibility_label"] = "Medium — 1 mainstream outlet"
        elif alt_count >= 1:
            inc["visibility_score"] = 1
            inc["visibility_label"] = "Low — alternative press only"
        else:
            inc["visibility_score"] = 0
            inc["visibility_label"] = "Invisible — no press coverage"
    return incidents


def _normalize_tags(incidents: list[dict]) -> list[dict]:
    """Ensure every incident has a `tags` array. Falls back to [category]
    if the DB doesn't have the column yet (pre-migration 008)."""
    for inc in incidents:
        if inc.get("tags") is None or inc.get("tags") == []:
            cat = inc.get("category")
            inc["tags"] = [cat] if cat else []
        # Also pull extra tags out of ai_raw if present
        raw = inc.get("ai_raw") or {}
        extra = raw.get("tags_extra") or []
        for t in extra:
            if t not in inc["tags"]:
                inc["tags"].append(t)
    return incidents


def _enrich_dmk_evidence(db, incidents: list[dict]) -> list[dict]:
    """Bulk-load top-3 DMK precedents for credit-steal incidents.

    Chunked for the same reason _enrich_sources is (URL-length limit on
    PostgREST IN() with many uuid values).
    """
    credit_steal_ids = [inc["id"] for inc in incidents if inc.get("is_credit_steal")]
    if not credit_steal_ids:
        return incidents
    by_incident: dict[str, list] = {}
    CHUNK = 30
    for start in range(0, len(credit_steal_ids), CHUNK):
        chunk = credit_steal_ids[start:start + CHUNK]
        try:
            res = (
                db.table("incident_dmk_evidence")
                .select(
                    "incident_id,match_score,match_reason,"
                    "announcement:dmk_announcements("
                    "id,title,content,source,source_url,announcement_date,media_urls"
                    ")"
                )
                .in_("incident_id", chunk)
                .order("match_score", desc=True)
                .execute()
            )
            for ev in res.data or []:
                by_incident.setdefault(ev["incident_id"], []).append(ev)
        except Exception:
            # Single-chunk failure should not break the whole list response
            continue
    try:
        for inc in incidents:
            if inc.get("is_credit_steal"):
                inc["dmk_evidence"] = by_incident.get(inc["id"], [])[:3]
    except Exception:
        # If the evidence table doesn't exist yet (pre-migration), don't break the list
        pass
    return incidents


# Friendly labels for categories — kept here so frontend doesn't need a
# duplicate hardcoded map.  Every category that EVER appears in DB gets a
# label; the frontend will only render chips for ones with non-zero count.
CATEGORY_LABELS_BACKEND: dict[str, str] = {
    "corruption":               "Corruption",
    "murders":                  "Murders",
    "sexual_assault":           "Sexual Assault",
    "crimes_women_kids":        "Crimes vs Women & Kids",
    "police_excess":            "Police Excess",
    "custodial_death":          "Custodial Death",
    "honour_killing":           "Honour Killing",
    "censorship":               "Censorship",
    "media_blackout":           "Media Blackout",
    "fake_news":                "Fake News",
    "propaganda":               "Propaganda",
    "credit_stealing":          "Credit Stealing",
    "broken_promise":           "Broken Promises",
    "kept_promise":             "Promises Kept",
    "partial_promise":          "Partial Promises",
    "new_initiative":           "New Initiatives",
    "defection":                "Defections (MLA Switching)",
    "youth_targeting":          "Youth Targeting",
    "crowd_management_failure": "Crowd / Rally Failures",
    "governance":               "Governance",
    "political_event":          "Political / Party",
    "tenders":                  "Tenders / Procurement",
    "power_cut":                "Power Cut",
    "eb_failure":               "EB / TANGEDCO Failure",
    "water_shortage":           "Water Shortage",
    "civic_failure":            "Civic Failure",
    "drug_menace":              "Drug Menace",
    "alcohol_menace":           "Alcohol Menace",
    "communal_violence":        "Communal Violence",
    "industrial_flight":        "Industrial Flight",
    "investment_announcement":  "Investment Announcement",
    "federalism":               "Federalism Conflict",
    "language_imposition":      "Language Imposition",
    "dravidian_attack":         "Attack on Dravidian Identity",
    "attack_on_press":          "Attack on Press",
    "other":                    "Other",
}


@router.get("/categories")
async def list_categories():
    """Return categories that ACTUALLY have approved incidents, with
    total + verified counts.  Frontend uses this to build dynamic
    filter chips so the UI can never show a category with zero data
    (or omit one that has data).

    Categories the AI may emit but with no rows yet are still returned
    with count=0 so the frontend can show them as greyed-out chips if
    desired (currently we hide them)."""
    from app.api.routes.stats import VERIFIED_STATUSES
    db = get_db()
    res = db.table("incidents").select("category, verification_status").eq("status", "approved").execute()
    from collections import Counter
    counts: dict[str, dict] = {}
    for row in (res.data or []):
        c = row.get("category") or "other"
        bucket = counts.setdefault(c, {"total": 0, "verified": 0})
        bucket["total"] += 1
        if row.get("verification_status") in VERIFIED_STATUSES:
            bucket["verified"] += 1
    out = []
    for c, b in sorted(counts.items(), key=lambda x: -x[1]["total"]):
        out.append({
            "category": c,
            "label":    CATEGORY_LABELS_BACKEND.get(c, c.replace("_", " ").title()),
            "count":    b["total"],
            "verified": b["verified"],
        })
    return out


@router.get("/corrections")
async def list_corrections(limit: int = Query(100, le=300)):
    """Public corrections log — every incident we RETRACTED or REJECTED
    after publishing, with the reason and timestamp.

    Showing our mistakes openly is a credibility feature, not a weakness:
    a tracker that publishes its retractions is more trustworthy than one
    that silently deletes them. Used by the /corrections page.
    """
    db = get_db()
    out = []
    try:
        res = (
            db.table("incidents")
            .select("id, title, category, incident_date, retracted_at, "
                    "retraction_reason, status, created_at")
            .or_("status.eq.rejected,retracted_at.not.is.null")
            .order("retracted_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = res.data or []
    except Exception:
        rows = []

    for r in rows:
        # Only surface entries that carry a genuine correction signal:
        # an explicit retraction reason, or a post-publish rejection.
        reason = r.get("retraction_reason")
        retracted = r.get("retracted_at")
        if not reason and not retracted and r.get("status") != "rejected":
            continue
        out.append({
            "id":            r["id"],
            "title":         r.get("title"),
            "category":      r.get("category"),
            "incident_date": r.get("incident_date"),
            "action":        "retracted" if retracted else "rejected",
            "reason":        reason or "Did not meet the 2-source verification bar after review.",
            "at":            retracted or r.get("created_at"),
        })
    # Newest correction first
    out.sort(key=lambda x: x.get("at") or "", reverse=True)
    return {"corrections": out, "count": len(out)}


@router.get("/", response_model=list[dict])
async def list_incidents(
    category: Optional[str] = None,
    is_credit_steal: Optional[bool] = None,
    verification_status: Optional[str] = None,
    status: str = "approved",
    district: Optional[str] = None,
    era: str = Query("tvk", description="'tvk' = only incidents on TVK's watch "
                     "(incident_date >= 2026-05-11, the default and the honest "
                     "view); 'all' = include pre-era (mostly DMK-era) incidents too."),
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    db = get_db()
    query = db.table("incidents").select("*").eq("status", status)

    # TVK-ERA FLOOR (2026-06-11): default to incidents on TVK's watch so the
    # list reconciles with the dashboard's accountability headline (817, not
    # 900). The ~83 pre-May-11 incidents are mostly DMK-era events that this
    # TVK tracker must not count as TVK's record. Pass era='all' to see them
    # (data is never deleted — just filtered out of the honest default view).
    if era != "all":
        query = query.gte("incident_date", settings.govt_start_date.isoformat())

    if category:
        query = query.eq("category", category)
    if is_credit_steal is not None:
        query = query.eq("is_credit_steal", is_credit_steal)
    if verification_status:
        query = query.eq("verification_status", verification_status)
    if district:
        query = query.eq("district", district)

    res = query.order("incident_date", desc=True).range(offset, offset + limit - 1).execute()
    data = res.data or []
    data = _enrich_sources(db, data)
    data = _compute_visibility(data)
    data = _enrich_dmk_evidence(db, data)
    data = _normalize_tags(data)
    return data


@router.get("/{incident_id}", response_model=dict)
async def get_incident(incident_id: str):
    """Return incident + linked DMK precedents + audit log."""
    db = get_db()
    res = db.table("incidents").select("*").eq("id", incident_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Incident not found")
    incident = res.data

    # Enrich with source outlet info
    incident = _enrich_sources(db, [incident])[0]

    # DMK precedents (cross-reference evidence)
    evidence = (
        db.table("incident_dmk_evidence")
        .select(
            "match_score,match_reason,announcement:dmk_announcements("
            "id,title,content,source,source_url,announcement_date,media_urls"
            ")"
        )
        .eq("incident_id", incident_id)
        .order("match_score", desc=True)
        .execute()
    )
    incident["dmk_evidence"] = evidence.data or []

    # Audit log
    audit = (
        db.table("incident_audit")
        .select("action,from_value,to_value,actor,reason,created_at,metadata")
        .eq("incident_id", incident_id)
        .order("created_at", desc=False)
        .execute()
    )
    incident["audit_log"] = audit.data or []

    return incident


def _require_sources(payload: dict) -> None:
    """Dashboard invariant: every approved/visible incident MUST link to at
    least one source URL. The dashboard's whole credibility rests on every
    claim being verifiable. Reject any create/update that would publish
    an incident without a source."""
    urls = payload.get("source_urls") or []
    if not isinstance(urls, list) or not any(isinstance(u, str) and u.strip() for u in urls):
        raise HTTPException(
            status_code=400,
            detail=(
                "source_urls is required for any incident shown on the dashboard. "
                "Either provide at least one source URL, or set status='pending_review' "
                "to hold the row off the public dashboard until a source is supplied."
            ),
        )


@router.post("/", response_model=dict, status_code=201)
async def create_incident(body: IncidentCreate, x_admin_secret: str = Header(...)):
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    db = get_db()
    payload = body.model_dump(exclude_none=True)
    # ENFORCE source-integrity: no publication without sourcing.
    _require_sources(payload)
    payload["status"] = "approved"
    payload["verification_status"] = "admin_verified"
    payload["incident_date"] = payload["incident_date"].isoformat()
    payload["source_count"] = len(payload.get("source_urls") or [])
    res = db.table("incidents").insert(payload).execute()
    incident_id = res.data[0]["id"]

    # Audit log
    db.table("incident_audit").insert({
        "incident_id": incident_id,
        "action": "created",
        "to_value": "admin_verified",
        "actor": "admin",
        "reason": "manual creation via API",
    }).execute()

    # Credit-steal incidents get DMK archive cross-reference
    if payload.get("is_credit_steal") or payload.get("related_dmk_scheme"):
        try:
            from app.ingestion.archive_lookup import find_precedents, attach_evidence
            precedents = find_precedents(
                incident_title=payload["title"],
                incident_summary=payload["summary"],
                related_scheme=payload.get("related_dmk_scheme"),
                limit=5,
            )
            attach_evidence(incident_id, precedents)
        except Exception:
            pass  # Non-fatal — admin can re-trigger later if needed

    # Immediate Google News corroboration: pull press coverage RIGHT NOW
    # so the new incident lands already-verified when possible.
    try:
        from app.ingestion.corroboration import attempt_corroborate
        fresh = db.table("incidents").select(
            "id, title, summary, location, incident_date, source_urls, verification_status"
        ).eq("id", incident_id).single().execute()
        if fresh.data:
            attempt_corroborate(fresh.data)
    except Exception:
        pass  # Live verification is best-effort

    # Return the latest row (corroboration may have updated it)
    refresh = db.table("incidents").select("*").eq("id", incident_id).single().execute()
    return refresh.data or res.data[0]


@router.patch("/{incident_id}", response_model=dict)
async def update_incident(incident_id: str, body: IncidentUpdate, x_admin_secret: str = Header(...)):
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    db = get_db()
    existing = db.table("incidents").select("*").eq("id", incident_id).single().execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Incident not found")
    updates = body.model_dump(exclude_none=True)
    # Source-integrity invariant: if this update would set status='approved'
    # OR clear sources on an already-approved row, require source_urls.
    target_status = updates.get("status", existing.data.get("status"))
    if target_status == "approved":
        effective_sources = (
            updates.get("source_urls")
            if "source_urls" in updates
            else (existing.data.get("source_urls") or [])
        )
        if not effective_sources or not any(isinstance(u, str) and u.strip() for u in effective_sources):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Cannot leave an approved incident without source_urls. "
                    "Supply at least one source URL or set status='pending_review'."
                ),
            )
    res = db.table("incidents").update(updates).eq("id", incident_id).execute()

    # Audit log status change
    if "status" in updates and updates["status"] != existing.data.get("status"):
        db.table("incident_audit").insert({
            "incident_id": incident_id,
            "action": "status_change",
            "from_value": existing.data.get("status"),
            "to_value": updates["status"],
            "actor": "admin",
        }).execute()

    return res.data[0]


def _find_approved_duplicate(db, incident: dict) -> Optional[dict]:
    """Return an already-APPROVED incident that looks like the same event,
    so the admin can't double-publish. Same logic family as the Telegram
    dedup: exact-ish title similarity within the same category, guarded by
    date proximity."""
    import difflib, re as _re
    def norm(t):
        return _re.sub(r"[^a-z0-9஀-௿]", "", (t or "").lower())[:60]
    cat = incident.get("category")
    idate = (incident.get("incident_date") or "")[:10]
    nt = norm(incident.get("title"))
    if not nt:
        return None
    try:
        rows = (db.table("incidents")
                .select("id, title, category, incident_date")
                .eq("status", "approved").eq("category", cat)
                .neq("id", incident["id"]).execute().data or [])
    except Exception:
        return None
    for r in rows:
        rd = (r.get("incident_date") or "")[:10]
        # within ~2 days
        if idate and rd and abs((_parse_d(idate) - _parse_d(rd))) > 2:
            continue
        ratio = difflib.SequenceMatcher(None, nt, norm(r.get("title"))).ratio()
        if ratio >= 0.78:
            r["_match_ratio"] = round(ratio, 2)
            return r
    return None


def _parse_d(s: str) -> int:
    from datetime import date as _date
    try:
        return _date.fromisoformat(s[:10]).toordinal()
    except Exception:
        return 0


@router.post("/{incident_id}/verify", response_model=dict)
async def admin_verify(incident_id: str, x_admin_secret: str = Header(...)):
    """Admin manually verifies a pending_review/pending_verification incident
    and moves it to the dashboard — UNLESS a duplicate is already approved,
    in which case it returns 409 'already captured' with the existing link."""
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    db = get_db()
    existing = db.table("incidents").select(
        "id, title, category, incident_date, source_urls"
    ).eq("id", incident_id).single().execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Incident not found")
    src = existing.data.get("source_urls") or []
    if not src or not any(isinstance(u, str) and u.strip() for u in src):
        raise HTTPException(
            status_code=400,
            detail=(
                "Cannot verify an incident without source_urls. PATCH the row first "
                "to add at least one source URL, then re-run /verify."
            ),
        )
    # DUPLICATE GUARD: if the same event is already approved, refuse + point
    # at it. Reject this pending copy as a duplicate so it leaves the queue.
    dup = _find_approved_duplicate(db, existing.data)
    if dup:
        db.table("incidents").update({
            "status": "rejected",
            "retracted_at": datetime.now(timezone.utc).isoformat(),
            "retraction_reason": f"Duplicate of approved incident {dup['id'][:8]} "
                                 f"(\"{(dup.get('title') or '')[:60]}\") — already captured.",
        }).eq("id", incident_id).execute()
        raise HTTPException(
            status_code=409,
            detail={
                "error": "already_captured",
                "message": f"Incident already captured ({int(dup['_match_ratio']*100)}% match): "
                           f"\"{dup.get('title')}\"",
                "existing_id": dup["id"],
            },
        )
    res = db.table("incidents").update({
        "status": "approved",
        "verification_status": "admin_verified",
    }).eq("id", incident_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Incident not found")
    db.table("incident_audit").insert({
        "incident_id": incident_id,
        "action": "verified",
        "to_value": "admin_verified",
        "actor": "admin",
    }).execute()
    return res.data[0]


@router.post("/{incident_id}/retract", response_model=dict)
async def retract_incident(
    incident_id: str,
    reason: str,
    x_admin_secret: str = Header(...),
):
    """Mark incident as retracted with a public reason — never deleted."""
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    db = get_db()
    from datetime import datetime, timezone
    res = db.table("incidents").update({
        "verification_status": "retracted",
        "retraction_reason": reason,
        "retracted_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", incident_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Incident not found")
    db.table("incident_audit").insert({
        "incident_id": incident_id,
        "action": "retracted",
        "to_value": "retracted",
        "actor": "admin",
        "reason": reason,
    }).execute()
    return res.data[0]


@router.delete("/{incident_id}", status_code=204)
async def delete_incident(incident_id: str, x_admin_secret: str = Header(...)):
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    db = get_db()
    db.table("incidents").delete().eq("id", incident_id).execute()


# --- Coordinated amplification flagging (admin-driven for now) ---
# When admin spots a TVK narrative being pushed by a bot/troll army, they
# can flag the incident with a pattern note. The flag is stored in ai_raw
# under 'amplification_flags' since the schema doesn't have a dedicated
# column yet (avoids migration risk).
#
# Frontend renders a 'Coordinated amplification suspected' badge when
# this field exists. Future: extend to ingest follower-graph data,
# posting-pattern fingerprints, account-creation-date analysis.
from pydantic import BaseModel


class AmplificationFlag(BaseModel):
    pattern: str            # e.g. "100+ accounts pushed same text within 1h"
    suspect_accounts: list[str] = []
    evidence_urls: list[str] = []
    note: str | None = None


@router.post("/{incident_id}/amplification-flag", response_model=dict)
async def flag_amplification(
    incident_id: str,
    body: AmplificationFlag,
    x_admin_secret: str = Header(...),
):
    """Mark an incident as showing signs of coordinated amplification —
    bot army, troll network, or paid promotion pushing a narrative."""
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    db = get_db()
    cur = db.table("incidents").select("ai_raw").eq("id", incident_id).single().execute()
    if not cur.data:
        raise HTTPException(status_code=404, detail="Incident not found")

    raw = cur.data.get("ai_raw") or {}
    flags = raw.get("amplification_flags") or []
    from datetime import datetime, timezone
    flags.append({
        "pattern": body.pattern,
        "suspect_accounts": body.suspect_accounts,
        "evidence_urls": body.evidence_urls,
        "note": body.note,
        "flagged_at": datetime.now(timezone.utc).isoformat(),
    })
    raw["amplification_flags"] = flags

    db.table("incidents").update({"ai_raw": raw}).eq("id", incident_id).execute()
    db.table("incident_audit").insert({
        "incident_id": incident_id,
        "action": "amplification_flagged",
        "actor": "admin",
        "reason": body.pattern,
        "metadata": {
            "suspect_count": len(body.suspect_accounts),
            "evidence_count": len(body.evidence_urls),
        },
    }).execute()
    return {"id": incident_id, "amplification_flags": flags}
