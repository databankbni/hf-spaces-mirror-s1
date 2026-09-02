import uuid
import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import RecoveryCase, RecoveryAction, AuditLog, Customer
from app.domain.state_machine import CaseState, transition_case
from app.policies.rules import evaluate_policy, MerchantPolicy
from app.agents.schemas import CaseContextPackage, AgentProposal
from app.agents.nim_client import nim_client

logger = logging.getLogger(__name__)

async def run_recovery_investigation(
    case_id: str,
    db: AsyncSession,
    policy: Optional[MerchantPolicy] = None,
) -> RecoveryCase:
    if policy is None:
        policy = MerchantPolicy()

    # 1. Fetch case with related actions and customer
    query = (
        select(RecoveryCase)
        .options(
            selectinload(RecoveryCase.actions),
            selectinload(RecoveryCase.customer),
            selectinload(RecoveryCase.outcomes),
            selectinload(RecoveryCase.audit_logs),
        )
        .where(RecoveryCase.id == case_id)
    )
    res = await db.execute(query)
    case = res.scalar_one_or_none()
    if not case:
        raise ValueError(f"Recovery case '{case_id}' not found.")

    # 2. Extract customer & prior history attributes safely
    customer = case.customer
    customer_tenure = customer.tenure_days if customer else 90
    customer_success_rate = customer.historical_success_rate if customer else 0.85
    prior_actions_count = len(case.actions) if case.actions else 0

    # 3. Transition DETECTED -> INVESTIGATING if currently DETECTED
    agent_run_id = f"run_{uuid.uuid4().hex[:8]}"
    if case.status == CaseState.DETECTED.value:
        case = await transition_case(
            session=db,
            case=case,
            target_state=CaseState.INVESTIGATING,
            reason="Agent began context assembly and root-cause synthesis.",
            agent_run_id=agent_run_id,
        )

    # 4. Assemble Context Package
    context = CaseContextPackage(
        case_id=case.id,
        amount_at_risk=case.amount_at_risk,
        currency=case.currency,
        failure_reason=case.failure_reason,
        raw_decline_code=case.raw_decline_code,
        customer_tenure_days=customer_tenure,
        historical_success_rate=customer_success_rate,
        prior_actions_count=prior_actions_count,
        merchant_max_retries=policy.max_retries,
        similar_cases_summary=[],
    )

    # 4. Generate proposal via NVIDIA NIM
    proposal: AgentProposal = await nim_client.get_recovery_decision(context)

    # 5. Deterministic Policy Gate
    policy_res = evaluate_policy(
        case=case,
        proposed_action_type=proposal.action_type,
        parameters={"delay_hours": proposal.delay_hours},
        prior_actions=case.actions,
        policy=policy,
    )

    # 6. Record the proposed RecoveryAction
    action = RecoveryAction(
        case_id=case.id,
        action_type=proposal.action_type,
        parameters={
            "delay_hours": proposal.delay_hours,
            "rationale": proposal.plain_english_rationale,
            "why_not_alternatives": proposal.why_not_alternatives,
            "customer_friction": proposal.customer_friction,
            "violations": policy_res.violations,
        },
        expected_recovery=proposal.expected_recovered_value,
        policy_status=policy_res.policy_status,
        approval_required=policy_res.approval_required,
        execution_status="READY" if policy_res.is_allowed else "BLOCKED",
    )
    db.add(action)
    await db.flush()

    # 7. Audit log for policy decision
    policy_audit = AuditLog(
        case_id=case.id,
        agent_run_id=agent_run_id,
        event_type="POLICY_EVALUATION",
        payload={
            "action_type": proposal.action_type,
            "policy_status": policy_res.policy_status,
            "approval_required": policy_res.approval_required,
            "violations": policy_res.violations,
            "expected_recovered_value": proposal.expected_recovered_value,
        },
    )
    db.add(policy_audit)

    # 8. Advance State Machine based on policy outcome
    # First advance to DECISION_READY
    case = await transition_case(
        session=db,
        case=case,
        target_state=CaseState.DECISION_READY,
        reason=f"Action proposal generated: {proposal.action_type}",
        agent_run_id=agent_run_id,
        metadata={"action_id": action.id},
    )

    # Then advance to final investigated state
    if proposal.action_type == "no_action":
        case = await transition_case(
            session=db,
            case=case,
            target_state=CaseState.NO_ACTION,
            reason="Deliberately withholding action to avoid unnecessary friction.",
            agent_run_id=agent_run_id,
        )
    elif policy_res.approval_required or not policy_res.is_allowed:
        case = await transition_case(
            session=db,
            case=case,
            target_state=CaseState.ESCALATED,
            reason="Action exceeds automated threshold or violates policy rules.",
            agent_run_id=agent_run_id,
            metadata={"violations": policy_res.violations},
        )
    else:
        case = await transition_case(
            session=db,
            case=case,
            target_state=CaseState.APPROVED,
            reason="Action approved by deterministic policy gate.",
            agent_run_id=agent_run_id,
        )

    await db.commit()

    # Refresh and return
    res = await db.execute(query.execution_options(populate_existing=True))
    return res.scalar_one()
