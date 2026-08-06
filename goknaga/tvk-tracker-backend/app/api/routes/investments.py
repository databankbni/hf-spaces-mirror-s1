"""Investment Commitment Registry API.

Serves the flagship DMK-era investment watchlist + a scorecard summary.
A "loss" is a row whose status is 'shifted' or 'cancelled'. The weekly
watcher (cron) updates statuses and raises pending incidents when a
commitment shows signs of moving.
"""
from fastapi import APIRouter
from app.database import get_db

router = APIRouter(prefix="/investments", tags=["investments"])

# Statuses that count as a realised loss to TN.
LOST = {"shifted", "cancelled"}
# Statuses that are "still on track" (committed counts toward the pipeline).
ON_TRACK = {"committed", "in_progress", "operational"}
AT_RISK = {"stalled"}


@router.get("/")
async def list_commitments():
    """Full registry, ordered by amount (biggest first)."""
    db = get_db()
    try:
        rows = (
            db.table("investment_commitments")
            .select("*")
            .order("amount_cr", desc=True)
            .execute()
            .data
            or []
        )
    except Exception:
        rows = []
    return rows


@router.get("/scorecard")
async def scorecard():
    """Aggregate view for the dashboard: totals + status breakdown +
    the at-risk / lost shortlist."""
    db = get_db()
    try:
        rows = db.table("investment_commitments").select("*").execute().data or []
    except Exception:
        rows = []

    def _sum(items, field):
        return round(sum((r.get(field) or 0) for r in items))

    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1

    lost = [r for r in rows if r["status"] in LOST]
    at_risk = [r for r in rows if r["status"] in AT_RISK]
    on_track = [r for r in rows if r["status"] in ON_TRACK]

    # Grounded vs MoU — the honest split. "operational" = money actually in the
    # ground; "in_progress" = under construction; "committed" = MoU only (signed,
    # not yet built). Keeps ₹3 lakh cr from being read as "delivered".
    operational = [r for r in rows if r["status"] == "operational"]
    in_progress = [r for r in rows if r["status"] == "in_progress"]
    committed = [r for r in rows if r["status"] == "committed"]

    return {
        "total_commitments": len(rows),
        "total_committed_cr": _sum(rows, "amount_cr"),
        "total_jobs_promised": _sum(rows, "jobs_promised"),
        "on_track_count": len(on_track),
        "at_risk_count": len(at_risk),
        "lost_count": len(lost),
        # grounded vs MoU split
        "operational_count": len(operational),
        "operational_cr": _sum(operational, "amount_cr"),
        "in_progress_count": len(in_progress),
        "in_progress_cr": _sum(in_progress, "amount_cr"),
        "committed_count": len(committed),
        "committed_cr": _sum(committed, "amount_cr"),
        # ₹ + jobs actually lost (only shifted/cancelled — honest, not the pipeline)
        "lost_cr": _sum(lost, "amount_cr"),
        "lost_jobs": _sum(lost, "jobs_promised"),
        "at_risk_cr": _sum(at_risk, "amount_cr"),
        "by_status": by_status,
        "lost": lost,
        "at_risk": at_risk,
    }
