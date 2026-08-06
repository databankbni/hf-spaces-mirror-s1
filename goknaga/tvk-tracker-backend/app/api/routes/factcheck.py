"""Fact-check copilot API (Phase 0 — admin-only).

Flow: POST /run queues a job (202 + id, pipeline runs in a BackgroundTask),
the admin UI polls GET /{id} until status leaves queued/running, then the
human confirms or rejects the draft via PATCH /{id}/review.

Everything here requires x-admin-secret. Public exposure is Phase 3 — and
even then only status='confirmed' rows are surfaced (enforced by RLS too).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from app.config import settings
from app.database import get_db

router = APIRouter(prefix="/factcheck", tags=["factcheck"])


def _require_admin(secret: Optional[str]) -> None:
    if not secret or secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")


class FactcheckRun(BaseModel):
    input_type: str = Field("text", pattern="^(text|url|image)$")
    # max_length is generous so an image's base64 data: URL fits; text/url are
    # held to the tight 8 KB cap by the validator below. (Frontend downscales
    # images to ~1024px before encoding, keeping payloads well under this.)
    content: str = Field(..., min_length=8, max_length=4_000_000,
                         description="The claim text, a URL, or an image data: URL")

    @model_validator(mode="after")
    def _check_content(self) -> "FactcheckRun":
        if self.input_type == "image":
            if not self.content.startswith("data:image/"):
                raise ValueError("image input must be a base64 data:image/ URL")
        elif len(self.content) > 8000:
            raise ValueError("text/url content must be <= 8000 characters")
        return self


class FactcheckReview(BaseModel):
    decision: str = Field(..., pattern="^(confirmed|rejected)$")
    note: Optional[str] = Field(None, max_length=1000)
    # Reviewer may override the AI verdict while confirming — the human
    # judgment is canonical, the AI draft is just the starting point.
    verdict_override: Optional[str] = Field(
        None, pattern="^(true|partly_true|misleading|false|unverifiable|needs_context)$")


@router.post("/run", status_code=202)
async def run_factcheck_job(
    body: FactcheckRun,
    background_tasks: BackgroundTasks,
    x_admin_secret: Optional[str] = Header(None),
):
    """Queue one fact-check. ~4 LLM calls + a few HTTP fetches per run —
    well inside the free-tier Space's safe envelope for one BackgroundTask."""
    _require_admin(x_admin_secret)
    db = get_db()
    row = db.table("factchecks").insert({
        "input_type": body.input_type,
        "input_content": body.content.strip(),
        "status": "queued",
    }).execute().data[0]

    from app.factcheck.pipeline import run_factcheck
    background_tasks.add_task(run_factcheck, row["id"])
    return {"id": row["id"], "status": "queued"}


@router.get("/")
async def list_factchecks(
    status: Optional[str] = Query(None,
        description="Filter: queued|running|draft|confirmed|rejected|error"),
    limit: int = Query(30, ge=1, le=100),
    offset: int = 0,
    x_admin_secret: Optional[str] = Header(None),
):
    _require_admin(x_admin_secret)
    db = get_db()
    q = db.table("factchecks").select("*")
    if status:
        q = q.eq("status", status)
    res = q.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return res.data or []


@router.get("/{factcheck_id}")
async def get_factcheck(
    factcheck_id: str,
    x_admin_secret: Optional[str] = Header(None),
):
    _require_admin(x_admin_secret)
    db = get_db()
    rows = db.table("factchecks").select("*").eq("id", factcheck_id).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail="Not found")
    return rows[0]


@router.patch("/{factcheck_id}/review")
async def review_factcheck(
    factcheck_id: str,
    body: FactcheckReview,
    x_admin_secret: Optional[str] = Header(None),
):
    """The human gate. Only rows a human confirms here ever count as a
    verdict; a verdict_override lets the reviewer correct the AI draft."""
    _require_admin(x_admin_secret)
    db = get_db()
    rows = db.table("factchecks").select("id, status").eq("id", factcheck_id).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail="Not found")
    if rows[0]["status"] not in ("draft", "error", "confirmed", "rejected"):
        raise HTTPException(status_code=409, detail="Job still running")
    updates = {
        "status": body.decision,
        "reviewer_note": body.note,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if body.verdict_override:
        updates["verdict"] = body.verdict_override
    res = db.table("factchecks").update(updates).eq("id", factcheck_id).execute()
    return res.data[0]
