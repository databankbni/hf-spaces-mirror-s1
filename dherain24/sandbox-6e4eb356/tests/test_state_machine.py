import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models import RecoveryCase, AuditLog, Merchant, Customer
from app.domain.state_machine import (
    CaseState,
    transition_case,
    InvalidStateTransitionError,
)

@pytest.mark.asyncio
async def test_valid_recovery_lifecycle(db_session: AsyncSession):
    # Setup test merchant and customer
    merchant = Merchant(id="m_test_1", name="Test Store", email="test@store.com")
    customer = Customer(id="c_test_1", merchant_id="m_test_1", name="Alice", email="alice@example.com")
    case = RecoveryCase(
        id="RR-0001",
        merchant_id="m_test_1",
        customer_id="c_test_1",
        source_type="payment_failed",
        source_id="pay_test_001",
        amount_at_risk=25000.0,
        currency="INR",
        failure_reason="insufficient_funds",
        status=CaseState.DETECTED.value,
    )
    db_session.add_all([merchant, customer, case])
    await db_session.commit()

    # DETECTED -> INVESTIGATING
    await transition_case(db_session, case, CaseState.INVESTIGATING, "Agent started investigation")
    assert case.status == CaseState.INVESTIGATING.value

    # INVESTIGATING -> DECISION_READY
    await transition_case(db_session, case, CaseState.DECISION_READY, "Agent selected delayed retry")
    assert case.status == CaseState.DECISION_READY.value

    # DECISION_READY -> APPROVED
    await transition_case(db_session, case, CaseState.APPROVED, "Policy gate passed")
    assert case.status == CaseState.APPROVED.value

    # APPROVED -> EXECUTING
    await transition_case(db_session, case, CaseState.EXECUTING, "Scheduled retry dispatched")
    assert case.status == CaseState.EXECUTING.value

    # EXECUTING -> VERIFYING
    await transition_case(db_session, case, CaseState.VERIFYING, "Payment webhook received")
    assert case.status == CaseState.VERIFYING.value

    # VERIFYING -> RECOVERED
    await transition_case(db_session, case, CaseState.RECOVERED, "Payment verified as captured")
    assert case.status == CaseState.RECOVERED.value

    # Check audit logs
    audit_res = await db_session.execute(select(AuditLog).where(AuditLog.case_id == case.id))
    logs = audit_res.scalars().all()
    assert len(logs) == 6
    assert logs[0].payload["to_state"] == CaseState.INVESTIGATING.value
    assert logs[-1].payload["to_state"] == CaseState.RECOVERED.value

@pytest.mark.asyncio
async def test_invalid_transition_fails(db_session: AsyncSession):
    merchant = Merchant(id="m_test_2", name="Test Store 2", email="test2@store.com")
    customer = Customer(id="c_test_2", merchant_id="m_test_2", name="Bob", email="bob@example.com")
    case = RecoveryCase(
        id="RR-0002",
        merchant_id="m_test_2",
        customer_id="c_test_2",
        source_type="payment_failed",
        source_id="pay_test_002",
        amount_at_risk=10000.0,
        currency="INR",
        failure_reason="expired_card",
        status=CaseState.DETECTED.value,
    )
    db_session.add_all([merchant, customer, case])
    await db_session.commit()

    # Attempt illegal leap: DETECTED -> RECOVERED directly
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        await transition_case(db_session, case, CaseState.RECOVERED, "Direct shortcut jump")
    
    assert "cannot move from 'DETECTED' to 'RECOVERED'" in str(exc_info.value)
    # Ensure state was not mutated
    assert case.status == CaseState.DETECTED.value

@pytest.mark.asyncio
async def test_no_action_transition(db_session: AsyncSession):
    merchant = Merchant(id="m_test_3", name="Test Store 3", email="test3@store.com")
    customer = Customer(id="c_test_3", merchant_id="m_test_3", name="Charlie", email="charlie@example.com")
    case = RecoveryCase(
        id="RR-0003",
        merchant_id="m_test_3",
        customer_id="c_test_3",
        source_type="payment_failed",
        source_id="pay_test_003",
        amount_at_risk=500.0,
        currency="INR",
        failure_reason="repeated_fraud_decline",
        status=CaseState.INVESTIGATING.value,
    )
    db_session.add_all([merchant, customer, case])
    await db_session.commit()

    # INVESTIGATING -> NO_ACTION
    await transition_case(db_session, case, CaseState.NO_ACTION, "Hopeless case, friction penalty exceeds value")
    assert case.status == CaseState.NO_ACTION.value

    # NO_ACTION -> CLOSED
    await transition_case(db_session, case, CaseState.CLOSED, "Case closed safely without intervention")
    assert case.status == CaseState.CLOSED.value
