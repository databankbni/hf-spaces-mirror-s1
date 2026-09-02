from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Literal

VALID_CATEGORIES = [
    "bug", "feature_request", "security", "performance",
    "billing", "auth", "docs", "question", "incident", "other",
]

VALID_PRIORITIES = ["critical", "high", "medium", "low"]
VALID_TEAMS = ["support", "engineering", "infra", "billing", "security", "escalation"]

class TriageOutput(BaseModel):
    """14-field structured output for every ticket processed by the triage agent."""

    # Field 1: Category classification
    category: Literal[
        "bug", "feature_request", "security", "performance",
        "billing", "auth", "docs", "question", "incident", "other"
    ] = Field(description="Ticket category determined by the classifier agent")

    # Field 2: Priority classification
    priority: Literal["critical", "high", "medium", "low"] = Field(
        description="Ticket priority. critical=SLA breach risk. high=blocking. medium=normal. low=cosmetic"
    )

    # Field 3: Routing team
    routing_team: Literal["support", "engineering", "infra", "billing", "security", "escalation"] = Field(
        description="Team this ticket should be routed to"
    )

    # Field 4: SLA breach risk score
    sla_breach_risk: float = Field(
        ge=0.0, le=1.0,
        description="Probability of SLA breach (0.0=safe, 1.0=certain breach)"
    )

    # Field 5: Churn risk score
    churn_risk: float = Field(
        ge=0.0, le=1.0,
        description="Customer churn risk score based on ticket history and billing signals"
    )

    # Field 6: Confidence score
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Agent confidence in this triage decision. < 0.65 triggers HITL"
    )

    # Field 7: Short summary of the ticket
    summary: str = Field(
        min_length=10, max_length=300,
        description="One sentence summary of the ticket issue"
    )

    # Field 8: Suggested resolution
    suggested_resolution: str = Field(
        min_length=10, max_length=1000,
        description="Recommended resolution or next action based on KB and ticket history"
    )

    # Field 9: Knowledge base citations
    kb_citations: List[str] = Field(
        default_factory=list,
        description="List of KB article IDs that support this triage decision"
    )

    # Field 10: Customer memories recalled
    recalled_memories: List[str] = Field(
        default_factory=list,
        description="Relevant memories recalled from previous interactions with this customer"
    )

    # Field 11: Incident detected
    incident_detected: bool = Field(
        description="True if this ticket is part of or related to a detected incident"
    )

    # Field 12: HITL required
    hitl_required: bool = Field(
        description="True if a human must review this triage before acting on it"
    )

    # Field 13: HITL reason
    hitl_reason: Optional[str] = Field(
        default=None,
        description="Reason HITL is required, if hitl_required is True"
    )

    # Field 14: Model versions used
    models_used: List[str] = Field(
        default_factory=list,
        description="List of model names used in this triage (for audit and debugging)"
    )

    @field_validator("hitl_reason")
    @classmethod
    def hitl_reason_required_when_hitl(cls, v, info):
        if info.data.get("hitl_required") and not v:
            raise ValueError("hitl_reason must be provided when hitl_required is True")
        return v

    @field_validator("kb_citations")
    @classmethod
    def validate_citations_format(cls, v):
        for citation in v:
            if not citation.startswith(("KB-", "TICKET-", "DOC-")):
                raise ValueError(f"Invalid citation format: {citation}. Must start with KB-, TICKET-, or DOC-")
        return v

    def should_trigger_hitl(self) -> bool:
        return self.confidence < 0.65 or self.hitl_required

    class Config:
        json_schema_extra = {
            "example": {
                "category": "auth",
                "priority": "high",
                "routing_team": "security",
                "sla_breach_risk": 0.72,
                "churn_risk": 0.35,
                "confidence": 0.88,
                "summary": "Customer reports 401 errors after OAuth token refresh",
                "suggested_resolution": "Verify token expiry settings and redirect URI configuration",
                "kb_citations": ["KB-001"],
                "recalled_memories": ["Previous auth issue resolved with token rotation - 2025-03-01"],
                "incident_detected": False,
                "hitl_required": False,
                "hitl_reason": None,
                "models_used": ["priority-classifier-v2", "category-classifier-v2", "gemma-3-4b"],
            }
        }
