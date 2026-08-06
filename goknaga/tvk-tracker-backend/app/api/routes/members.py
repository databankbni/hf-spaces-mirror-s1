from fastapi import APIRouter, HTTPException, Header
from app.database import get_db
from app.models.schemas import MemberCreate
from app.config import settings

router = APIRouter(prefix="/members", tags=["members"])


@router.get("/", response_model=list[dict])
async def list_members():
    """List members + an approved-incident-count per row.

    The nested PostgREST form `select("*, incidents(count)")` requires a
    declared FK between members.id and incidents.member_ids[], which we
    don't have (member_ids is a uuid[] column on incidents with no FK).
    We compute the count per member in a second pass.  Slightly chatty
    but the /members page is rarely loaded.
    """
    db = get_db()
    try:
        res = db.table("members").select("*").order("name").execute()
        members = res.data or []
    except Exception:
        return []
    for m in members:
        try:
            c = (
                db.table("incidents")
                .select("id", count="exact")
                .eq("status", "approved")
                .contains("member_ids", [m["id"]])
                .execute()
            )
            m["incident_count"] = c.count or 0
        except Exception:
            m["incident_count"] = 0
    return members


@router.get("/{member_id}", response_model=dict)
async def get_member(member_id: str):
    db = get_db()
    res = db.table("members").select("*").eq("id", member_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Member not found")
    incidents = db.table("incidents").select("*").contains("member_ids", [member_id]).eq("status", "approved").execute()
    return {**res.data, "incidents": incidents.data or []}


@router.post("/", response_model=dict, status_code=201)
async def create_member(body: MemberCreate, x_admin_secret: str = Header(...)):
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    db = get_db()
    res = db.table("members").insert(body.model_dump()).execute()
    return res.data[0]
