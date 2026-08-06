"""Citizen reporting — public submission + admin moderation."""
from fastapi import APIRouter, HTTPException, Header, Request
from pydantic import BaseModel
from app.database import get_db
from app.config import settings
from typing import Optional
from datetime import date
import hashlib
import time

router = APIRouter(prefix="/citizen-reports", tags=["citizen"])

# Rudimentary in-process rate limit (5 submissions per IP per hour)
# For production, swap with Redis/upstash.
_RATE_BUCKET: dict[str, list[float]] = {}
_RATE_LIMIT = 5
_RATE_WINDOW = 3600


def _check_rate(ip: str) -> bool:
    now = time.time()
    window = [t for t in _RATE_BUCKET.get(ip, []) if now - t < _RATE_WINDOW]
    if len(window) >= _RATE_LIMIT:
        return False
    window.append(now)
    _RATE_BUCKET[ip] = window
    return True


class CitizenReportIn(BaseModel):
    title: str
    description: str
    category: Optional[str] = None
    location: Optional[str] = None
    incident_date: Optional[date] = None
    reporter_name: Optional[str] = None
    reporter_contact: Optional[str] = None
    image_urls: list[str] = []


@router.post("/", status_code=201)
async def submit_report(report: CitizenReportIn, request: Request):
    """Public endpoint — anyone can submit. Rate-limited per IP. All go to moderation."""
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate(client_ip):
        raise HTTPException(status_code=429, detail="Too many submissions. Try again in an hour.")

    ip_hash = hashlib.sha256(f"{client_ip}{settings.admin_secret}".encode()).hexdigest()[:16]

    db = get_db()
    payload = report.model_dump()
    if payload.get("incident_date"):
        payload["incident_date"] = payload["incident_date"].isoformat()
    payload["ip_hash"] = ip_hash
    res = db.table("citizen_reports").insert(payload).execute()
    return {"id": res.data[0]["id"], "status": "pending_moderation"}


@router.get("/")
async def list_reports(
    status: str = "approved",
    limit: int = 50,
    x_admin_secret: Optional[str] = Header(None),
):
    """Public sees only approved reports; admin sees all."""
    db = get_db()
    is_admin = x_admin_secret == settings.admin_secret
    q = db.table("citizen_reports").select("*")
    if not is_admin:
        q = q.eq("status", "approved")
    else:
        q = q.eq("status", status)
    res = q.order("created_at", desc=True).limit(limit).execute()
    return res.data or []


@router.post("/{report_id}/approve")
async def approve_report(report_id: str, x_admin_secret: str = Header(...)):
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    from datetime import datetime, timezone
    db = get_db()
    res = db.table("citizen_reports").update({
        "status": "approved",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "reviewed_by": "admin",
    }).eq("id", report_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Report not found")
    return res.data[0]


@router.post("/{report_id}/reject")
async def reject_report(report_id: str, reason: str, x_admin_secret: str = Header(...)):
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    from datetime import datetime, timezone
    db = get_db()
    res = db.table("citizen_reports").update({
        "status": "rejected",
        "rejection_reason": reason,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "reviewed_by": "admin",
    }).eq("id", report_id).execute()
    return res.data[0] if res.data else {}


@router.post("/{report_id}/promote-to-incident")
async def promote_report(
    report_id: str,
    x_admin_secret: str = Header(...),
):
    """Convert an approved citizen report into a tracked incident."""
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    db = get_db()
    r = db.table("citizen_reports").select("*").eq("id", report_id).single().execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="Report not found")
    src = r.data

    incident_payload = {
        "title": src["title"],
        "summary": src["description"],
        "category": src.get("category") or "other",
        "incident_date": src.get("incident_date") or date.today().isoformat(),
        "location": src.get("location"),
        "source_urls": [],
        "source_count": 1,
        "is_credit_steal": False,
        "severity": 1,
        "ai_confidence": 1.0,  # human-submitted
        "status": "approved",
        "verification_status": "admin_verified",
        "image_urls": src.get("image_urls") or [],
        "ai_raw": {"source": "citizen_report", "report_id": report_id},
    }
    inserted = db.table("incidents").insert(incident_payload).execute()
    incident_id = inserted.data[0]["id"]

    db.table("citizen_reports").update({
        "promoted_to_incident_id": incident_id,
        "status": "approved",
    }).eq("id", report_id).execute()

    db.table("incident_audit").insert({
        "incident_id": incident_id,
        "action": "created",
        "to_value": "admin_verified",
        "actor": "admin",
        "reason": f"Promoted from citizen report {report_id}",
    }).execute()

    return {"incident_id": incident_id, "report_id": report_id}
