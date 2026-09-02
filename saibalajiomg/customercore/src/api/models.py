"""
CustomerCore API — Pydantic Request/Response Models (Phase 10)

These are the PUBLIC API contracts. They are separate from the internal
AgentState / TriageOutput schemas (src/agent/schemas.py) because:
  - API models are versioned and stable — breaking changes require a new API version
  - Internal schemas can evolve freely without breaking API consumers
  - API models include only what external clients need to see, not internal state fields

Design principles:
  - All fields are explicitly typed with descriptions (appear in OpenAPI docs)
  - Sensitive internal fields (raw LLM prompts, vault tokens) are excluded
  - Response models use Optional for fields that may not be populated yet
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Enums — typed categorical values used in request/response bodies
# ─────────────────────────────────────────────────────────────────────────────

class TicketChannel(str, Enum):
    """How the ticket was submitted."""
    API        = "api"
    SLACK      = "slack"
    EMAIL      = "email"
    WEBHOOK    = "webhook"
    CONSOLE    = "console"


class TicketPriority(str, Enum):
    """Ticket priority levels used in both requests and AI classification output."""
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


class CustomerTier(str, Enum):
    """B2B customer tier — affects VIP priority multiplier in the Classify Agent."""
    FREE       = "free"
    STARTER    = "starter"
    GROWTH     = "growth"
    ENTERPRISE = "enterprise"
    VIP        = "vip"


class TriageStatus(str, Enum):
    """Lifecycle status of a triage request."""
    PENDING    = "pending"      # Received, not yet processed
    PROCESSING = "processing"   # LangGraph supervisor running
    HITL       = "hitl"         # Paused at HITL interrupt, awaiting human review
    COMPLETE   = "complete"     # All agents finished, result available
    FAILED     = "failed"       # Unrecoverable error


# ─────────────────────────────────────────────────────────────────────────────
# Request Models — what the API consumer sends
# ─────────────────────────────────────────────────────────────────────────────

class TicketSubmitRequest(BaseModel):
    """
    Submit a support ticket for AI triage.

    This is the primary entry point for all ticket processing. The ticket text
    is processed by the 6-agent LangGraph supervisor which classifies, recalls
    memories, retrieves similar tickets, computes churn risk, detects incidents,
    and decides if human review is needed.
    """

    text: str = Field(
        ...,
        min_length=10,
        max_length=10_000,
        description="Full text of the support ticket. May be in any language — "
                    "multilingual detection (EN/DE/FR/ES/PT/IT/NL/JA) is automatic.",
        examples=["My payment keeps failing and I can't access my account. "
                  "This has been happening for 3 days and I'm on the Enterprise plan."]
    )
    customer_id: str = Field(
        ...,
        min_length=3,
        max_length=128,
        description="Unique identifier for the end customer within the tenant.",
        examples=["cust_abc123", "user-456", "john.doe@company.com"]
    )
    customer_tier: CustomerTier = Field(
        default=CustomerTier.GROWTH,
        description="B2B customer subscription tier. Enterprise/VIP tickets get "
                    "automatic priority escalation via the VIP multiplier."
    )
    channel: TicketChannel = Field(
        default=TicketChannel.API,
        description="Ingestion channel. Used for routing and analytics."
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional arbitrary metadata (e.g., browser version, OS, "
                    "account age). Stored alongside the ticket but not used in triage.",
        examples=[{"browser": "Chrome 120", "os": "macOS 14", "account_age_days": 365}]
    )

    class Config:
        json_schema_extra = {
            "example": {
                "text": "Zahlungsverarbeitung schlägt fehl, obwohl die Karte gültig ist.",
                "customer_id": "cust_de_789",
                "customer_tier": "enterprise",
                "channel": "api",
                "metadata": {"language_hint": "de", "contract_value_eur": 48000}
            }
        }


class HITLResumeRequest(BaseModel):
    """
    Resume a paused HITL (Human-in-the-Loop) triage.

    When a ticket triggers the HITL interrupt (low confidence, critical priority,
    or security-sensitive content), the LangGraph graph pauses and saves its state.
    A human operator reviews the paused state and may override any field before
    resuming. Only fields explicitly set in this request are overridden — unset
    fields retain their AI-generated values.
    """

    ticket_id: UUID = Field(
        ...,
        description="The ticket ID that was paused at HITL. Must match an existing "
                    "ticket with status=hitl."
    )
    operator_id: str = Field(
        ...,
        description="ID of the human operator performing the review. Recorded in audit trail.",
        examples=["support_lead_007", "manager@company.com"]
    )
    override_category: str | None = Field(
        default=None,
        description="Override the AI-classified ticket category.",
        examples=["billing", "technical", "account", "security"]
    )
    override_priority: TicketPriority | None = Field(
        default=None,
        description="Override the AI-assigned priority."
    )
    override_resolution: str | None = Field(
        default=None,
        description="Override the AI-generated suggested resolution with a human-written one.",
    )
    operator_notes: str | None = Field(
        default=None,
        max_length=2000,
        description="Free-text notes from the operator, recorded in the audit trail."
    )

    class Config:
        json_schema_extra = {
            "example": {
                "ticket_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "operator_id": "support_lead_007",
                "override_priority": "critical",
                "override_category": "billing",
                "operator_notes": "Customer is Fortune 500. Escalate immediately."
            }
        }


# ─────────────────────────────────────────────────────────────────────────────
# Response Models — what the API returns to consumers
# ─────────────────────────────────────────────────────────────────────────────

class TicketSubmitResponse(BaseModel):
    """Immediate response after a ticket is accepted for triage."""

    ticket_id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this triage request. Use this ID to poll "
                    "for results or subscribe to the SSE stream."
    )
    status: TriageStatus = Field(
        default=TriageStatus.PENDING,
        description="Initial status is always 'pending'. Poll GET /triage/{ticket_id} "
                    "for the final result."
    )
    message: str = Field(
        default="Ticket accepted for triage",
        description="Human-readable status message."
    )
    estimated_seconds: int = Field(
        default=5,
        description="Estimated seconds until triage completes. Based on priority: "
                    "critical tickets skip the queue."
    )
    stream_url: str = Field(
        ...,
        description="Server-Sent Events URL for real-time triage progress updates."
    )


class KBCitation(BaseModel):
    """A knowledge base document cited in the triage resolution."""
    citation_id: str = Field(..., description="e.g. TICKET-20241103-xyz or KB-billing-001")
    relevance_score: float = Field(..., ge=0.0, le=1.0)
    excerpt: str = Field(..., max_length=500)


class TriageResultResponse(BaseModel):
    """
    Complete AI triage result for a ticket.

    This response includes the full output from the 6-agent LangGraph supervisor:
    classification, RAG-retrieved resolution, churn risk, incident detection,
    recalled memories, and HITL decision.
    """

    ticket_id: UUID
    status: TriageStatus
    tenant_id: str = Field(..., description="Tenant that submitted this ticket.")
    customer_id: str
    customer_tier: CustomerTier = Field(default=CustomerTier.FREE, description="B2B customer subscription tier.")
    text: str | None = Field(None, description="The ticket text (PII-masked for safety).")
    masked_text: str | None = Field(None, description="PII-masked and tokenized ticket body.")

    # ── Classification outputs ──
    category: str | None = Field(None, description="AI-classified ticket category.")
    priority: TicketPriority | None = Field(None)
    confidence: float | None = Field(None, ge=0.0, le=1.0,
                                      description="Classification confidence (0–1).")
    detected_language: str | None = Field(None, description="ISO 639-1 language code e.g. 'de'.")

    # ── RAG outputs ──
    suggested_resolution: str | None = Field(
        None,
        description="AI-generated resolution based on similar past tickets."
    )
    kb_citations: list[KBCitation] = Field(
        default_factory=list,
        description="Knowledge base documents that informed the resolution."
    )
    recalled_memories: list[str] = Field(
        default_factory=list,
        description="Relevant past interactions recalled for this customer."
    )

    # ── Risk signals ──
    churn_risk: str | None = Field(None, description="low | medium | high | critical")
    sla_breach_risk: bool | None = Field(None)

    # ── Incident signals ──
    incident_active: bool = Field(default=False)
    escalation_team: str | None = Field(None)

    # ── HITL ──
    hitl_required: bool = Field(default=False)
    hitl_reason: str | None = Field(None)

    # ── Constitutional Policy Engine Audit ──
    constitutional_blocked: bool = Field(default=False, description="Whether the resolution was blocked by the AI safety policy engine.")
    constitutional_violations: list[dict] = Field(default_factory=list, description="List of constitutional rule violations detected.")

    # ── Audit ──
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    processing_ms: int | None = Field(None, description="Total triage latency in milliseconds.")
    error_message: str | None = Field(None, description="Detailed error message if processing failed.")


class HealthResponse(BaseModel):
    """API health check response."""
    status: str = Field(default="ok")
    version: str = Field(default="1.0.0")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    services: dict[str, str] = Field(
        default_factory=dict,
        description="Status of dependent services: redis, chromadb, supabase."
    )


class ErrorResponse(BaseModel):
    """Standard error response shape."""
    error: str
    detail: str | None = None
    request_id: str | None = None
