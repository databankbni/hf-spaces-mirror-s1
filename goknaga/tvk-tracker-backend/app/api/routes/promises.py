from fastapi import APIRouter, HTTPException, Header, Query
from app.database import get_db
from app.models.schemas import PromiseCreate, PromiseUpdate
from app.config import settings
from typing import Optional

router = APIRouter(prefix="/promises", tags=["promises"])


@router.get("/", response_model=list[dict])
async def list_promises(
    status: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = Query(500, le=1000),
):
    db = get_db()
    query = db.table("promises").select("*")
    if status:
        query = query.eq("status", status)
    if category:
        query = query.eq("category", category)
    res = query.order("made_date", desc=False).limit(limit).execute()
    return res.data or []


@router.post("/", response_model=dict, status_code=201)
async def create_promise(body: PromiseCreate, x_admin_secret: str = Header(...)):
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    db = get_db()
    payload = body.model_dump()
    payload["made_date"] = payload["made_date"].isoformat()
    if payload.get("deadline"):
        payload["deadline"] = payload["deadline"].isoformat()
    res = db.table("promises").insert(payload).execute()
    return res.data[0]


@router.patch("/{promise_id}", response_model=dict)
async def update_promise(promise_id: str, body: PromiseUpdate, x_admin_secret: str = Header(...)):
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    db = get_db()
    updates = body.model_dump(exclude_none=True)
    res = db.table("promises").update(updates).eq("id", promise_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Promise not found")
    return res.data[0]
