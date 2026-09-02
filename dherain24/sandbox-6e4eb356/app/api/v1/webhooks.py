import json
import logging
from typing import Dict, Any
from fastapi import APIRouter, Request, Header, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.db.models import RecoveryCase, AuditLog, ActionOutcome, RecoveryAction
from app.domain.state_machine import CaseState, transition_case
from app.razorpay.webhooks import verify_webhook_signature
from app.schemas.case import CaseCreate
from app.api.v1.cases import create_recovery_case
from app.agents.recovery_agent import run_recovery_investigation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

@router.post("/razorpay", status_code=status.HTTP_200_OK)
async def razorpay_webhook_receiver(
    request: Request,
    x_razorpay_signature: str = Header(None, alias="X-Razorpay-Signature"),
    db: AsyncSession = Depends(get_db),
):
    body = await request.body()

    # 1. Cryptographic HMAC-SHA256 Signature Verification
    if not verify_webhook_signature(body, x_razorpay_signature):
        logger.warning("Rejected Razorpay webhook with invalid or missing HMAC signature.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Razorpay-Signature header.",
        )

    try:
        event = json.loads(body.decode("utf-8"))
    except Exception as e:
        logger.error(f"Malformed webhook JSON: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed JSON payload.")

    event_id = event.get("id") or event.get("event_id") or "evt_unknown"
    event_type = event.get("event", "unknown")
    payload = event.get("payload", {})

    # 2. Idempotency Check (Reject duplicate webhooks)
    dup_res = await db.execute(
        select(AuditLog).where(AuditLog.event_type == "WEBHOOK_RECEIVED").where(AuditLog.agent_run_id == event_id)
    )
    if dup_res.scalar_one_or_none():
        logger.info(f"Ignored duplicate Razorpay webhook event: {event_id}")
        return {"status": "ignored_duplicate", "event_id": event_id}

    # Record Webhook Event for Audit Trail & Idempotency
    webhook_audit = AuditLog(
        case_id="SYSTEM",
        agent_run_id=event_id,
        event_type="WEBHOOK_RECEIVED",
        payload={"event": event_type, "event_id": event_id},
    )
    db.add(webhook_audit)
    await db.commit()

    # 3. Handle 'payment.failed' -> Create Case & Trigger Autonomous Investigation
    if event_type == "payment.failed":
        payment = payload.get("payment", {}).get("entity", {})
        payment_id = payment.get("id", "pay_unknown")
        amount_paise = payment.get("amount", 0)
        amount_inr = round(amount_paise / 100.0, 2)
        raw_error_code = payment.get("error_code") or payment.get("error_reason") or "UNKNOWN_DECLINE"
        error_desc = payment.get("error_description") or "Payment failed at issuing bank."
        customer_id = payment.get("customer_id") or payment.get("email") or f"cust_{payment_id[-6:]}"

        case_payload = CaseCreate(
            merchant_id="merchant_demo",
            customer_id=customer_id,
            source_type="payment_failed",
            source_id=payment_id,
            amount_at_risk=amount_inr,
            currency=payment.get("currency", "INR"),
            failure_reason=error_desc,
            raw_decline_code=raw_error_code,
            priority=75,
        )

        case = await create_recovery_case(case_payload, db)

        # Trigger immediate autonomous recovery investigation
        try:
            investigated_case = await run_recovery_investigation(case.id, db)
            return {
                "status": "case_investigated",
                "case_id": investigated_case.id,
                "case_status": investigated_case.status,
                "amount": amount_inr,
            }
        except Exception as e:
            logger.error(f"Error investigating case {case.id}: {e}")
            return {"status": "case_created_pending_investigation", "case_id": case.id}

    # 4. Handle 'payment.captured' -> Recovered Payment Verification
    elif event_type == "payment.captured":
        payment = payload.get("payment", {}).get("entity", {})
        payment_id = payment.get("id")
        amount_inr = round(payment.get("amount", 0) / 100.0, 2)

        # Find matching recovery case
        query = (
            select(RecoveryCase)
            .options(selectinload(RecoveryCase.actions), selectinload(RecoveryCase.outcomes))
            .where(RecoveryCase.source_id == payment_id)
        )
        res = await db.execute(query)
        case = res.scalar_one_or_none()

        if case:
            # Transition to RECOVERED if permissible
            if case.status in [CaseState.EXECUTING.value, CaseState.VERIFYING.value, CaseState.APPROVED.value]:
                # If currently EXECUTING or APPROVED, advance through VERIFYING
                if case.status != CaseState.VERIFYING.value:
                    case = await transition_case(db, case, CaseState.VERIFYING, "Payment capture webhook received.")
                case = await transition_case(db, case, CaseState.RECOVERED, "Payment confirmed captured by Razorpay.")

                outcome = ActionOutcome(
                    case_id=case.id,
                    action_id=case.actions[-1].id if case.actions else "act_direct",
                    recovered=True,
                    recovered_amount=amount_inr,
                    time_to_recovery=1.0,
                    failure_reason=None,
                )
                db.add(outcome)
                await db.commit()
                return {"status": "case_recovered", "case_id": case.id, "recovered_amount": amount_inr}

        return {"status": "payment_captured_no_active_case", "payment_id": payment_id}

    # 5. Handle 'payment_link.paid' -> Alternate Recovery Path Verified
    elif event_type == "payment_link.paid":
        plink = payload.get("payment_link", {}).get("entity", {})
        ref_id = plink.get("reference_id")
        amount_inr = round(plink.get("amount_paid", 0) / 100.0, 2)

        query = (
            select(RecoveryCase)
            .options(selectinload(RecoveryCase.actions), selectinload(RecoveryCase.outcomes))
            .where(RecoveryCase.source_id == ref_id)
        )
        res = await db.execute(query)
        case = res.scalar_one_or_none()

        if case and case.status != CaseState.RECOVERED.value:
            if case.status != CaseState.VERIFYING.value:
                case = await transition_case(db, case, CaseState.VERIFYING, "Payment link paid by customer.")
            case = await transition_case(db, case, CaseState.RECOVERED, "Recovered via alternate Razorpay payment link.")

            outcome = ActionOutcome(
                case_id=case.id,
                action_id=case.actions[-1].id if case.actions else "act_link",
                recovered=True,
                recovered_amount=amount_inr,
                time_to_recovery=2.5,
            )
            db.add(outcome)
            await db.commit()
            return {"status": "case_recovered_via_link", "case_id": case.id, "recovered_amount": amount_inr}

        return {"status": "payment_link_paid_recorded", "reference_id": ref_id}

    return {"status": "event_acknowledged", "event": event_type}
