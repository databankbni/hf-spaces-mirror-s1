from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel, Field
from app.db.models import RecoveryCase, RecoveryAction

class MerchantPolicy(BaseModel):
    max_retries: int = Field(default=2, description="Maximum automated retries allowed per case")
    retry_cooldown_hours: float = Field(default=24.0, description="Minimum hours required between retries")
    max_contacts_per_7d: int = Field(default=1, description="Maximum customer recovery messages in 7 days")
    auto_action_max_amount: float = Field(default=50000.0, description="Maximum amount for automated actions")
    human_approval_threshold: float = Field(default=100000.0, description="Amounts at or above this require human approval")
    recovery_window_days: int = Field(default=7, description="Stop all recovery attempts after N days")

class PolicyEvaluationResult(BaseModel):
    policy_status: str  # APPROVED, REJECTED, APPROVAL_REQUIRED
    approval_required: bool
    is_allowed: bool
    violations: List[str] = []
    action_type: str
    parameters: Dict[str, Any] = {}
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def evaluate_policy(
    case: RecoveryCase,
    proposed_action_type: str,
    parameters: Dict[str, Any],
    prior_actions: List[RecoveryAction],
    policy: Optional[MerchantPolicy] = None,
) -> PolicyEvaluationResult:
    if policy is None:
        policy = MerchantPolicy()

    violations: List[str] = []
    approval_required = False

    # Rule 1: High-value transactions exceed human approval threshold
    if case.amount_at_risk >= policy.human_approval_threshold:
        approval_required = True
        violations.append(
            f"Transaction amount ₹{case.amount_at_risk:,.2f} exceeds human approval threshold ₹{policy.human_approval_threshold:,.2f}."
        )

    # Rule 2: Exceeding auto action maximum limit
    if case.amount_at_risk > policy.auto_action_max_amount and not approval_required:
        approval_required = True
        violations.append(
            f"Transaction amount ₹{case.amount_at_risk:,.2f} exceeds automated action limit ₹{policy.auto_action_max_amount:,.2f}."
        )

    # Rule 3: Retry Budget Check (for retry actions)
    if proposed_action_type in ["retry", "delayed_retry", "immediate_retry"]:
        retry_count = sum(
            1 for a in prior_actions if a.action_type in ["retry", "delayed_retry", "immediate_retry"]
        )
        if retry_count >= policy.max_retries:
            violations.append(
                f"Retry budget exhausted: {retry_count} retries already attempted (limit: {policy.max_retries})."
            )

        # Rule 4: Cooldown Enforcement
        if prior_actions:
            last_retry = next(
                (a for a in reversed(prior_actions) if a.action_type in ["retry", "delayed_retry", "immediate_retry"]),
                None,
            )
            if last_retry and last_retry.executed_at:
                executed_at_utc = ensure_utc(last_retry.executed_at)
                cooldown_delta = timedelta(hours=policy.retry_cooldown_hours)
                now = datetime.now(timezone.utc)
                if (now - executed_at_utc) < cooldown_delta:
                    elapsed_hours = (now - executed_at_utc).total_seconds() / 3600.0
                    violations.append(
                        f"Cooldown active: only {elapsed_hours:.1f}h elapsed since last retry (required: {policy.retry_cooldown_hours}h)."
                    )

    # Rule 5: Customer Contact Limit Check (for messaging/links)
    if proposed_action_type in ["payment_link", "send_notification"]:
        contact_count = sum(
            1 for a in prior_actions if a.action_type in ["payment_link", "send_notification"]
        )
        if contact_count >= policy.max_contacts_per_7d:
            violations.append(
                f"Customer contact cap reached: {contact_count} contacts in last 7 days (limit: {policy.max_contacts_per_7d})."
            )

    # Rule 6: Recovery Window Expiry
    if case.created_at:
        created_at_utc = ensure_utc(case.created_at)
        age_delta = datetime.now(timezone.utc) - created_at_utc
        if age_delta.days > policy.recovery_window_days:
            violations.append(
                f"Recovery window expired: case is {age_delta.days} days old (limit: {policy.recovery_window_days} days)."
            )

    # Determine final verdict
    if approval_required:
        status = "APPROVAL_REQUIRED"
        is_allowed = False
    elif violations:
        status = "REJECTED"
        is_allowed = False
    else:
        status = "APPROVED"
        is_allowed = True

    # Exception: NO_ACTION is always allowed safely
    if proposed_action_type == "no_action":
        status = "APPROVED"
        is_allowed = True
        approval_required = False
        violations = []

    return PolicyEvaluationResult(
        policy_status=status,
        approval_required=approval_required,
        is_allowed=is_allowed,
        violations=violations,
        action_type=proposed_action_type,
        parameters=parameters,
    )
