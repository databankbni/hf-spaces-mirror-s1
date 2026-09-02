"""
CustomerCore API — In-Memory Triage Store (Phase 10)

WHY AN IN-MEMORY STORE BEFORE SUPABASE?
-----------------------------------------
Phase 10 builds the API layer. Phase 12 adds Supabase as the persistent database.
The in-memory store allows the full API to function correctly in Phase 10 without
requiring Supabase to be configured.

The store interface is identical to what the Supabase implementation will expose,
so swapping in Phase 12 requires only changing the dependency injection — no route
handler changes.

Production path:
  Phase 10: TriageStore (in-memory dict)  ← current
  Phase 12: SupabaseTriageStore (PostgreSQL)  ← replaces this

WHY NOT REDIS?
--------------
Redis is used for the semantic cache (RAG layer) and rate limiting. Using Redis for
triage results would create tight coupling between the API and the cache layer.
Triage results are relational data with foreign keys (tenant → ticket → agent outputs)
— they belong in PostgreSQL (Supabase), not a key-value store.
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime
from typing import Any
from uuid import uuid4

from src.api.models import TriageResultResponse, TriageStatus


class TriageStore:
    """
    Thread-safe in-memory store for triage results and status tracking.

    This is intentionally simple — it's a development placeholder for the
    Supabase PostgreSQL store that arrives in Phase 12.

    Data model:
        _tickets: dict[UUID, dict] — full ticket data including AgentState snapshot
        _status:  dict[UUID, TriageStatus] — quick status lookup
        _tenant_index: dict[str, list[UUID]] — tenant → ticket_ids (for list queries)
    """

    def __init__(self) -> None:
        self._tickets: dict[str, dict[str, Any]] = {}
        self._status: dict[str, TriageStatus] = {}
        self._tenant_index: dict[str, list[str]] = defaultdict(list)

    def create(
        self,
        *,
        tenant_id: str,
        customer_id: str,
        text: str,
        channel: str,
        metadata: dict[str, Any],
    ) -> str:
        """Create a new triage record in PENDING state. Returns ticket_id (str UUID)."""
        ticket_id = str(uuid4())
        self._tickets[ticket_id] = {
            "ticket_id": ticket_id,
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "text": text,
            "channel": channel,
            "metadata": metadata,
            "status": TriageStatus.PENDING,
            "created_at": datetime.utcnow().isoformat(),
            "completed_at": None,
            "result": None,
            "_start_ms": time.time() * 1000,
        }
        self._status[ticket_id] = TriageStatus.PENDING
        self._tenant_index[tenant_id].append(ticket_id)
        return ticket_id

    def set_processing(self, ticket_id: str) -> None:
        """Mark a ticket as actively being processed by LangGraph."""
        if ticket_id in self._tickets:
            self._tickets[ticket_id]["status"] = TriageStatus.PROCESSING
            self._status[ticket_id] = TriageStatus.PROCESSING

    def set_hitl(self, ticket_id: str, hitl_reason: str) -> None:
        """Mark a ticket as paused at the HITL interrupt."""
        if ticket_id in self._tickets:
            self._tickets[ticket_id]["status"] = TriageStatus.HITL
            self._tickets[ticket_id]["hitl_reason"] = hitl_reason
            self._status[ticket_id] = TriageStatus.HITL

    def set_complete(self, ticket_id: str, result: dict[str, Any]) -> None:
        """Store the final triage result and mark as complete."""
        if ticket_id in self._tickets:
            now = datetime.utcnow()
            start_ms = self._tickets[ticket_id].get("_start_ms", time.time() * 1000)
            elapsed_ms = int(time.time() * 1000 - start_ms)
            self._tickets[ticket_id].update({
                "status": TriageStatus.COMPLETE,
                "result": result,
                "completed_at": now.isoformat(),
                "processing_ms": elapsed_ms,
            })
            self._status[ticket_id] = TriageStatus.COMPLETE

    def set_failed(self, ticket_id: str, error: str) -> None:
        """Mark a ticket as failed with the error message."""
        if ticket_id in self._tickets:
            self._tickets[ticket_id].update({
                "status": TriageStatus.FAILED,
                "error": error,
                "completed_at": datetime.utcnow().isoformat(),
            })
            self._status[ticket_id] = TriageStatus.FAILED

    def get(self, ticket_id: str) -> dict[str, Any] | None:
        """Retrieve the full ticket record by ID."""
        return self._tickets.get(ticket_id)

    def get_status(self, ticket_id: str) -> TriageStatus | None:
        """Fast status lookup without loading the full record."""
        return self._status.get(ticket_id)

    def list_for_tenant(self, tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """List all tickets for a tenant (newest first, limited)."""
        ids = self._tenant_index.get(tenant_id, [])
        results = []
        for tid in reversed(ids[-limit:]):
            record = self._tickets.get(tid)
            if record:
                results.append(record)
        return results

    def to_response(self, record: dict[str, Any]) -> TriageResultResponse:
        """Convert a store record to the API response model."""
        result = record.get("result") or {}
        return TriageResultResponse(
            ticket_id=record["ticket_id"],
            status=record["status"],
            tenant_id=record["tenant_id"],
            customer_id=record["customer_id"],
            category=result.get("category"),
            priority=result.get("priority"),
            confidence=result.get("confidence"),
            detected_language=result.get("detected_language"),
            suggested_resolution=result.get("suggested_resolution"),
            kb_citations=result.get("kb_citations", []),
            recalled_memories=result.get("recalled_memories", []),
            churn_risk=result.get("churn_risk"),
            sla_breach_risk=result.get("sla_breach_risk"),
            incident_active=result.get("incident_active", False),
            escalation_team=result.get("escalation_team"),
            hitl_required=result.get("hitl_required", False),
            hitl_reason=record.get("hitl_reason"),
            created_at=datetime.fromisoformat(record["created_at"]),
            completed_at=(
                datetime.fromisoformat(record["completed_at"])
                if record.get("completed_at") else None
            ),
            processing_ms=record.get("processing_ms"),
        )


# Singleton store instance — replaced by Supabase client in Phase 12
triage_store = TriageStore()
