import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import RecoveryCase, RecoveryAction, AuditLog
from app.domain.state_machine import CaseState, transition_case
from app.razorpay.client import razorpay_client, RazorpayGatewayError

logger = logging.getLogger(__name__)

async def execute_recovery_action_with_failure_guard(
    case_id: str,
    action_id: str,
    db: AsyncSession,
    simulate_gateway_outage: bool = False,
) -> RecoveryCase:
    """
    Executes an approved recovery action with strict failure safeguards:
    1. Prevents duplicate charges by asserting state is APPROVED.
    2. If Razorpay API times out or returns 500:
       - Immediately halts execution.
       - Marks action execution_status as FAILED_SAFELY.
       - Logs an immutable audit entry with failure details.
       - Escalates case to human operations (status: ESCALATED).
       - Zero further automated attempts are made (no retry storm).
    """
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
        raise ValueError(f"Case '{case_id}' not found.")

    action = next((a for a in case.actions if a.id == action_id), None)
    if not action:
        raise ValueError(f"Action '{action_id}' not found on case '{case_id}'.")

    # Step 1: Transition APPROVED -> EXECUTING
    case = await transition_case(
        session=db,
        case=case,
        target_state=CaseState.EXECUTING,
        reason=f"Initiating execution for action: {action.action_type}",
    )

    try:
        if action.action_type == "payment_link":
            # Attempt to generate Razorpay Payment Link
            plink_res = await razorpay_client.create_payment_link(
                amount=case.amount_at_risk,
                description=f"Recovery link for {case.id}",
                customer_name=case.customer.name if case.customer else "Customer",
                customer_email=case.customer.email if case.customer else "customer@example.com",
                reference_id=case.source_id,
                simulate_failure=simulate_gateway_outage,
            )
            action.execution_status = "SUCCESS"
            action.parameters["payment_link_id"] = plink_res.get("id")
            action.parameters["payment_link_url"] = plink_res.get("short_url")

            # Advance to VERIFYING
            case = await transition_case(
                session=db,
                case=case,
                target_state=CaseState.VERIFYING,
                reason="Payment link generated and dispatched. Awaiting customer completion.",
            )
            await db.commit()
            res = await db.execute(query.execution_options(populate_existing=True))
            return res.scalar_one()

        elif action.action_type == "delayed_retry":
            # Schedule delayed retry
            action.execution_status = "SCHEDULED"
            case = await transition_case(
                session=db,
                case=case,
                target_state=CaseState.VERIFYING,
                reason=f"Retry scheduled after {action.parameters.get('delay_hours', 24)}h cooldown.",
            )
            await db.commit()
            res = await db.execute(query.execution_options(populate_existing=True))
            return res.scalar_one()

        else:
            action.execution_status = "SUCCESS"
            await db.commit()
            res = await db.execute(query.execution_options(populate_existing=True))
            return res.scalar_one()

    except RazorpayGatewayError as e:
        # Failure Guardrail Intercept:
        # Stop execution immediately, do NOT retry blindly, protect merchant & customer
        logger.error(f"Gateway outage intercepted for case {case.id}: {e}")
        action.execution_status = "FAILED_SAFELY"
        new_params = dict(action.parameters or {})
        new_params["failure_error"] = str(e)
        action.parameters = new_params

        # Log audit entry
        outage_audit = AuditLog(
            case_id=case.id,
            agent_run_id=f"failure_guard_{case.id}",
            event_type="GATEWAY_FAILURE_HALTED",
            payload={
                "error": str(e),
                "status_code": e.status_code,
                "action_id": action.id,
                "safeguard_action": "Execution halted; escalated to human supervisor to prevent duplicate charge.",
            },
        )
        db.add(outage_audit)

        # Escalate case to human review
        case = await transition_case(
            session=db,
            case=case,
            target_state=CaseState.ESCALATED,
            reason=f"Gateway outage encountered ({str(e)}). Automated execution halted safely to prevent duplicate charges.",
        )
        await db.commit()
        res = await db.execute(query.execution_options(populate_existing=True))
        return res.scalar_one()
