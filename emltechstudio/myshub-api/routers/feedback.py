"""Feedback Router — Public feedback submissions + admin management"""
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone

from utils.db import create_feedback, get_feedback, delete_feedback, get_admin

router = APIRouter()

# ── Pydantic Models ─────────────────────────────────────────────────
class FeedbackCreate(BaseModel):
    name: str
    email: str
    message: str
    type: str = "general"  # general, report, claim, partnership

class FeedbackResponse(BaseModel):
    id: str
    name: str
    email: str
    message: str
    type: str
    created_at: str

# ── Auth Helper (reuses admin auth pattern) ─────────────────────────
def _verify_admin(email: str, password: str):
    """Verify admin credentials using same pattern as admin.py"""
    import hashlib
    admin = get_admin(email.lower().strip())
    if not admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    pwd_hash = hashlib.sha256(password.encode()).hexdigest()
    if admin.get("password") != pwd_hash:
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    if not admin.get("active", True):
        raise HTTPException(status_code=403, detail="Account disabled")
    return admin

# ── Public Endpoints ─────────────────────────────────────────────────

@router.post("/")
def submit_feedback(data: FeedbackCreate):
    """Submit feedback from the public. No authentication required."""
    # Validate type
    valid_types = ["general", "report", "claim", "partnership"]
    feedback_type = data.type.lower().strip()
    if feedback_type not in valid_types:
        feedback_type = "general"

    feedback = create_feedback({
        "name": data.name.strip(),
        "email": data.email.lower().strip(),
        "message": data.message.strip(),
        "type": feedback_type,
    })

    return {
        "success": True,
        "message": "Thank you for your feedback!",
        "feedback_id": feedback["id"]
    }

# ── Admin Endpoints ──────────────────────────────────────────────────

@router.get("/admin/feedback")
def list_feedback(
    admin_email: str = Header(...),
    admin_password: str = Header(...),
    type_filter: Optional[str] = None,
    limit: int = 100
):
    """List all feedback (admin only). Optional type filter."""
    _verify_admin(admin_email, admin_password)

    all_feedback = get_feedback()

    # Sort by created_at desc
    all_feedback.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    if type_filter:
        all_feedback = [f for f in all_feedback if f.get("type") == type_filter.lower()]

    return {
        "total": len(all_feedback),
        "feedback": all_feedback[:limit]
    }

@router.delete("/admin/feedback/{feedback_id}")
def remove_feedback(
    feedback_id: str,
    admin_email: str = Header(...),
    admin_password: str = Header(...)
):
    """Delete a feedback entry by ID (admin only)."""
    _verify_admin(admin_email, admin_password)

    success = delete_feedback(feedback_id)
    if not success:
        raise HTTPException(status_code=404, detail="Feedback not found")

    return {"success": True, "message": "Feedback deleted."}
