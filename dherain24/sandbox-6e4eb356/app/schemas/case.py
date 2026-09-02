from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

class CaseCreate(BaseModel):
    merchant_id: str
    customer_id: str
    source_type: str = Field(..., description="payment_failed, subscription_payment_failed, etc.")
    source_id: str = Field(..., description="Razorpay payment_id or subscription_id")
    amount_at_risk: float = Field(..., gt=0, description="Amount in INR, must be positive")
    currency: str = "INR"
    failure_reason: str
    raw_decline_code: Optional[str] = None
    priority: Optional[int] = Field(default=50, ge=0, le=100)

class CaseTransitionRequest(BaseModel):
    target_state: str = Field(..., description="Target state to transition to")
    reason: str = Field(..., description="Justification for state change")
    metadata: Optional[Dict[str, Any]] = None
    agent_run_id: Optional[str] = None

class ActionResponse(BaseModel):
    id: str
    case_id: str
    action_type: str
    parameters: Dict[str, Any]
    expected_recovery: float
    policy_status: str
    approval_required: bool
    execution_status: str
    executed_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class OutcomeResponse(BaseModel):
    id: str
    case_id: str
    action_id: str
    recovered: bool
    recovered_amount: float
    time_to_recovery: float
    failure_reason: Optional[str] = None
    verified_at: datetime

    model_config = ConfigDict(from_attributes=True)

class AuditLogResponse(BaseModel):
    id: str
    case_id: str
    agent_run_id: Optional[str] = None
    event_type: str
    payload: Dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class CaseResponse(BaseModel):
    id: str
    merchant_id: str
    customer_id: str
    source_type: str
    source_id: str
    amount_at_risk: float
    currency: str
    failure_reason: str
    raw_decline_code: Optional[str] = None
    status: str
    priority: int
    created_at: datetime
    updated_at: datetime
    actions: List[ActionResponse] = []
    outcomes: List[OutcomeResponse] = []
    audit_logs: List[AuditLogResponse] = []

    model_config = ConfigDict(from_attributes=True)

class CaseListResponse(BaseModel):
    total: int
    recovered_count: int
    at_risk_total: float
    recovered_total: float
    cases: List[CaseResponse]
