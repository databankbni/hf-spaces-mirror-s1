"""Public read-only API over the DMK announcements archive.

The 387 dmk.in achievements + 2177 CMO/DIPR tweets form a date-indexed
record of what the DMK government did 2021-2026. This is the substrate
for the credit-steal cross-reference AND the "DMK timeline" page on
the frontend.
"""
from fastapi import APIRouter, Query
from app.database import get_db
from app.config import settings
from typing import Optional

router = APIRouter(prefix="/dmk-archive", tags=["dmk-archive"])

# DMK tenure ended on this date; govt handles kept posting under TVK afterward.
# Everything in the DMK archive must be on/before this boundary.
_DMK_END = settings.dmk_tenure_end_date.isoformat()


@router.get("/schemes")
async def list_schemes(
    q: Optional[str] = Query(None, description="Free-text search in name/description"),
    category: Optional[str] = Query(None, description="Curated category filter"),
):
    """The curated DMK schemes registry — Kalaignar Magalir Urimai, Pudhumai
    Penn, Free Electricity, etc. Each row is a structured receipt: launch
    date, beneficiary count, key features.

    Used by the /receipts page — the public-facing "what DMK actually did"
    counter-evidence library.
    """
    db = get_db()
    query = db.table("dmk_schemes").select(
        "id, name, aliases, launch_date, description, key_features, "
        "beneficiaries_count, evidence_urls"
    )
    if q:
        query = query.or_(f"name.ilike.*{q}*,description.ilike.*{q}*")
    res = query.order("launch_date", desc=False).execute()
    data = res.data or []

    # Auto-categorize each scheme based on name/description keywords
    # (we don't have a category column yet — derive it for the UI grouping)
    CATEGORY_RULES = [
        ("women",       ("magalir", "penn", "women", "pengal")),
        ("education",   ("kalvi", "school", "student", "naan mudhalvan", "education", "breakfast")),
        ("health",      ("kaapom", "kaakkum", "hospital", "aiims", "health", "medical")),
        ("welfare",     ("welfare", "uravum", "benefit")),
        ("electricity", ("electricity", "tangedco", "meter", "power")),
        ("transport",   ("metro", "bus", "road", "transit", "outer ring")),
        ("industry",    ("foxconn", "pegatron", "investors", "industries", "aerospace", "iphone")),
        ("language",    ("tamil", "periyar", "tamilukku")),
        ("agriculture", ("agriculture", "farmer", "fishermen", "pasumai")),
    ]
    def categorize(scheme: dict) -> str:
        haystack = (scheme.get("name", "") + " " + (scheme.get("description") or "")).lower()
        for cat, kws in CATEGORY_RULES:
            if any(kw in haystack for kw in kws):
                return cat
        return "governance"

    for s in data:
        s["derived_category"] = categorize(s)

    if category:
        data = [s for s in data if s["derived_category"] == category]
    return data


@router.get("/timeline")
async def timeline(
    source: Optional[str] = None,       # dmk_website / cmo_tamil_nadu / tn_dipr / manual
    tag: Optional[str] = None,           # 'women_empowerment', 'roadways', 'governance' ...
    q: Optional[str] = None,             # free-text search in title/content
    year: Optional[int] = None,          # 2021..2026
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    """Paginated list of DMK announcements. Default sort: newest first."""
    db = get_db()
    query = db.table("dmk_announcements").select(
        "id, source, source_url, announcement_date, title, content, "
        "media_urls, tags, scheme_name_hint"
    ).lte("announcement_date", _DMK_END)  # DMK tenure only — no post-handover posts

    if source:
        query = query.eq("source", source)
    if tag:
        query = query.contains("tags", [tag])
    if q:
        query = query.or_(f"title.ilike.*{q}*,content.ilike.*{q}*")
    if year:
        query = query.gte("announcement_date", f"{year}-01-01")
        query = query.lte("announcement_date", f"{year}-12-31")

    res = (
        query.order("announcement_date", desc=True)
             .range(offset, offset + limit - 1)
             .execute()
    )
    return res.data or []


@router.get("/stats")
async def archive_stats():
    """High-level numbers for the timeline page header."""
    db = get_db()
    out = {}
    for source in ("dmk_website", "cmo_tamil_nadu", "tn_dipr", "manual"):
        res = (
            db.table("dmk_announcements")
            .select("id", count="exact")
            .eq("source", source)
            .lte("announcement_date", _DMK_END)
            .execute()
        )
        out[source] = res.count or 0

    # Top tags across all sources (DMK tenure only)
    res = (db.table("dmk_announcements").select("tags")
           .lte("announcement_date", _DMK_END).limit(2000).execute())
    from collections import Counter
    tag_count: Counter = Counter()
    for row in res.data or []:
        for t in row.get("tags") or []:
            if t:
                tag_count[t] += 1
    out["top_tags"] = tag_count.most_common(20)
    out["total"] = sum(out[s] for s in ("dmk_website", "cmo_tamil_nadu", "tn_dipr", "manual"))
    return out
