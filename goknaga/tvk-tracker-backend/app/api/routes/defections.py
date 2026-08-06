"""Horse-trading tracker — opposition MLAs/leaders defecting to the
ruling TVK party.

Read endpoints are public (with status filtering so unreviewed rows
don't accidentally surface).  Mutations are admin-gated like the rest
of the system.

The accompanying AI-ingestion update lives in ai_processor.py — when a
news article describes a party switch, the extractor sets a
defection-shape payload that this module persists.
"""
from datetime import date, datetime, timezone
from typing import Optional, List, Any
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from app.database import get_db
from app.config import settings

router = APIRouter(prefix="/defections", tags=["defections"])


# ---------- Schemas ------------------------------------------------------

class DefectionCreate(BaseModel):
    mla_name: str
    constituency: Optional[str] = None
    from_party: str = "AIADMK"
    to_party: str = "TVK"
    resignation_date: Optional[date] = None
    joined_date: Optional[date] = None
    stated_reason: Optional[str] = None
    alleged_reason: Optional[str] = None
    pending_cases: List[dict] = []
    evidence_urls: List[str] = []
    severity: int = 3
    ai_confidence: float = 0.5
    status: str = "pending"
    notes: Optional[str] = None


class DefectionUpdate(BaseModel):
    status: Optional[str] = None
    constituency: Optional[str] = None
    stated_reason: Optional[str] = None
    alleged_reason: Optional[str] = None
    pending_cases: Optional[List[dict]] = None
    evidence_urls: Optional[List[str]] = None
    severity: Optional[int] = None
    notes: Optional[str] = None
    retraction_reason: Optional[str] = None


def _verify_admin(secret: Optional[str]):
    if secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="admin secret required")


# ---------- Routes -------------------------------------------------------

@router.get("/")
async def list_defections(
    status: Optional[str] = None,
    from_party: Optional[str] = None,
    to_party: Optional[str] = None,
    limit: int = 100,
):
    db = get_db()
    try:
        q = db.table("defections").select("*")
        if status:
            q = q.eq("status", status)
        else:
            # Default to anything except retracted (verified + pending)
            q = q.neq("status", "retracted")
        if from_party:
            q = q.eq("from_party", from_party)
        if to_party:
            q = q.eq("to_party", to_party)
        res = (
            q.order("joined_date", desc=True)
             .order("resignation_date", desc=True)
             .limit(limit)
             .execute()
        )
        return res.data or []
    except Exception:
        return []


@router.get("/stats")
async def defections_stats():
    """Top-line numbers for the dashboard card + page header.

    Returns plain numbers, no jargon — UI shows them as
    "5 MLAs poached", "3 verified", etc.
    """
    db = get_db()
    try:
        res = (
            db.table("defections")
            .select("from_party, to_party, status, joined_date, resignation_date")
            .neq("status", "retracted")
            .execute()
        )
        rows = res.data or []
    except Exception:
        rows = []

    total = len(rows)
    verified = sum(1 for r in rows if r.get("status") == "verified")
    pending  = sum(1 for r in rows if r.get("status") == "pending")
    to_tvk   = sum(1 for r in rows if r.get("to_party") == "TVK")
    from_aiadmk = sum(1 for r in rows if r.get("from_party") == "AIADMK")
    # 30-day rate
    today = date.today()
    recent = 0
    for r in rows:
        d = r.get("joined_date") or r.get("resignation_date")
        if d:
            try:
                if (today - date.fromisoformat(d[:10])).days <= 30:
                    recent += 1
            except Exception:
                pass

    return {
        "total":         total,
        "verified":      verified,
        "pending":       pending,
        "to_tvk":        to_tvk,
        "from_aiadmk":   from_aiadmk,
        "last_30_days":  recent,
        "as_of":         today.isoformat(),
    }


@router.get("/{defection_id}")
async def get_defection(defection_id: str):
    db = get_db()
    try:
        res = db.table("defections").select("*").eq("id", defection_id).single().execute()
        return res.data
    except Exception:
        raise HTTPException(status_code=404, detail="not found")


@router.post("/")
async def create_defection(
    payload: DefectionCreate,
    x_admin_secret: Optional[str] = Header(None),
):
    _verify_admin(x_admin_secret)
    db = get_db()
    record: dict[str, Any] = payload.model_dump(mode="json")
    record["created_at"] = datetime.now(timezone.utc).isoformat()
    record["updated_at"] = record["created_at"]
    try:
        res = db.table("defections").insert(record).execute()
        return {"ok": True, "data": (res.data or [None])[0]}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Insert failed (run migration 013?). Underlying: {e}",
        )


@router.patch("/{defection_id}")
async def update_defection(
    defection_id: str,
    payload: DefectionUpdate,
    x_admin_secret: Optional[str] = Header(None),
):
    _verify_admin(x_admin_secret)
    fields = {k: v for k, v in payload.model_dump(mode="json").items() if v is not None}
    if not fields:
        return {"ok": True, "updated": []}
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    if fields.get("status") and fields["status"] not in (
        "pending", "verified", "disputed", "retracted"
    ):
        raise HTTPException(status_code=400, detail="invalid status")
    db = get_db()
    try:
        res = db.table("defections").update(fields).eq("id", defection_id).execute()
        return {"ok": True, "updated": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update failed: {e}")
