from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class AgentProposal(BaseModel):
    action_type: str = Field(
        ...,
        description="Must be one of: delayed_retry, payment_link, escalate_human, no_action"
    )
    delay_hours: Optional[float] = Field(default=0.0, description="Recommended delay before retry")
    expected_recovery_probability: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Estimated probability of successful recovery"
    )
    expected_recovered_value: float = Field(
        ...,
        ge=0.0,
        description="Probability * amount at risk - friction penalty"
    )
    customer_friction: str = Field(
        default="low",
        description="low, medium, high"
    )
    plain_english_rationale: str = Field(
        ...,
        description="Clear, non-technical explanation for merchant operations"
    )
    why_not_alternatives: Optional[str] = Field(
        None,
        description="Why other intervention pathways were less optimal"
    )
    requires_human_approval: bool = Field(default=False)

class CaseContextPackage(BaseModel):
    case_id: str
    amount_at_risk: float
    currency: str
    failure_reason: str
    raw_decline_code: Optional[str]
    customer_tenure_days: int
    historical_success_rate: float
    prior_actions_count: int
    merchant_max_retries: int
    similar_cases_summary: List[Dict[str, Any]] = []
