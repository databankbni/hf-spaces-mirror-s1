"""
CustomerCore API — Server-Sent Events (SSE) Stream Router (Phase 13)

Wires the Supabase persistent repository layer into the streaming endpoints.
Replaces the in-memory triage_store with TicketRepository.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from src.api.auth import AuthenticatedTenant, verify_token
from src.api.models import TriageStatus
from src.db.repository import TicketRepository

router = APIRouter(prefix="/api/v1/triage", tags=["Streaming"])

# How often to check for status updates (seconds)
_POLL_INTERVAL = 0.5
# Maximum wait time before giving up and closing the stream
_MAX_WAIT_SECONDS = 120


@router.get(
    "/{ticket_id}/stream",
    summary="Real-time SSE stream for triage progress",
    description=(
        "Subscribe to Server-Sent Events for a ticket's triage progress. "
        "The stream emits status events as each agent completes. "
        "Closes automatically when triage reaches complete/hitl/failed status."
    ),
    response_class=StreamingResponse,
)
async def stream_triage(
    ticket_id: str,
    caller: AuthenticatedTenant = Depends(verify_token),
) -> StreamingResponse:
    """
    Stream real-time triage progress via Server-Sent Events from Supabase.
    """
    repo = TicketRepository(caller.tenant_id)
    record = await repo.get(ticket_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found.")

    async def event_generator():
        """
        Async generator that polls the database and yields SSE events.
        """
        elapsed = 0.0
        last_status = None

        # Send initial connection confirmation event
        yield _sse_event({
            "type": "connected",
            "ticket_id": ticket_id,
            "timestamp": datetime.utcnow().isoformat(),
        })

        while elapsed < _MAX_WAIT_SECONDS:
            await asyncio.sleep(_POLL_INTERVAL)
            elapsed += _POLL_INTERVAL

            rec = await repo.get(ticket_id)
            current_status = TriageStatus(rec["status"]) if rec else None

            # Only emit an event if status changed (avoids flooding the client)
            if current_status != last_status:
                last_status = current_status

                if current_status == TriageStatus.PROCESSING:
                    yield _sse_event({
                        "type": "status",
                        "status": "processing",
                        "message": "AI agents are analyzing your ticket...",
                        "elapsed_ms": int(elapsed * 1000),
                    })

                elif current_status == TriageStatus.HITL:
                    yield _sse_event({
                        "type": "hitl",
                        "status": "hitl",
                        "message": "Ticket flagged for human review.",
                        "hitl_reason": rec.get("hitl_reason") if rec else None,
                        "elapsed_ms": int(elapsed * 1000),
                    })
                    yield _sse_event({"type": "done"})
                    return

                elif current_status == TriageStatus.COMPLETE:
                    from src.api.routers.triage import row_to_response
                    res_obj = row_to_response(rec) if rec else None
                    yield _sse_event({
                        "type": "complete",
                        "status": "complete",
                        "category": res_obj.category if res_obj else None,
                        "priority": res_obj.priority.value if res_obj and res_obj.priority else None,
                        "confidence": res_obj.confidence if res_obj else 0.85,
                        "churn_risk": res_obj.churn_risk if res_obj else "low",
                        "hitl_required": res_obj.hitl_required if res_obj else False,
                        "processing_ms": res_obj.processing_ms if res_obj else None,
                        "elapsed_ms": int(elapsed * 1000),
                    })
                    yield _sse_event({"type": "done"})
                    return

                elif current_status == TriageStatus.FAILED:
                    yield _sse_event({
                        "type": "error",
                        "status": "failed",
                        "error": rec.get("error_message", "Unknown error") if rec else "Unknown error",
                        "elapsed_ms": int(elapsed * 1000),
                    })
                    yield _sse_event({"type": "done"})
                    return

            # Send a keep-alive comment every 10 seconds (prevents proxy timeouts)
            if elapsed % 10 < _POLL_INTERVAL:
                yield ": keep-alive\n\n"

        # Timeout — stream ran too long
        yield _sse_event({
            "type": "timeout",
            "message": f"Stream timed out after {_MAX_WAIT_SECONDS}s. "
                       f"Poll GET /api/v1/triage/{ticket_id} for result.",
        })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering (critical for SSE)
            "Connection": "keep-alive",
        },
    )


def _sse_event(data: dict) -> str:
    """Format a dictionary as a W3C-compliant SSE event string."""
    return f"data: {json.dumps(data)}\n\n"
