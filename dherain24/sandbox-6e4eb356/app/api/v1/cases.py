import random
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.db.models import RecoveryCase, Customer, Merchant, AuditLog
from app.schemas.case import (
    CaseCreate,
    CaseResponse,
    CaseListResponse,
    CaseTransitionRequest,
    AuditLogResponse,
)
from app.domain.state_machine import (
    CaseState,
    transition_case,
    InvalidStateTransitionError,
)

router = APIRouter(prefix="/cases", tags=["Cases"])

def generate_case_id() -> str:
    num = random.randint(1000, 9999)
    return f"RR-{num}"

@router.post("", response_model=CaseResponse, status_code=status.HTTP_201_CREATED)
async def create_recovery_case(
    payload: CaseCreate,
    db: AsyncSession = Depends(get_db),
):
    # Ensure merchant exists or auto-provision demo merchant
    merchant_res = await db.execute(select(Merchant).where(Merchant.id == payload.merchant_id))
    merchant = merchant_res.scalar_one_or_none()
    if not merchant:
        merchant = Merchant(
            id=payload.merchant_id,
            name="Demo Merchant",
            email=f"{payload.merchant_id}@example.com",
        )
        db.add(merchant)
        await db.flush()

    # Ensure customer exists or auto-provision demo customer
    customer_res = await db.execute(select(Customer).where(Customer.id == payload.customer_id))
    customer = customer_res.scalar_one_or_none()
    if not customer:
        customer = Customer(
            id=payload.customer_id,
            merchant_id=merchant.id,
            name=f"Customer {payload.customer_id[-4:] if len(payload.customer_id) >= 4 else payload.customer_id}",
            email=f"customer_{payload.customer_id}@example.com",
            tenure_days=180,
            historical_success_rate=0.88,
        )
        db.add(customer)
        await db.flush()

    # Check idempotency on source_id (e.g. Razorpay payment_id)
    existing_case_res = await db.execute(
        select(RecoveryCase)
        .options(
            selectinload(RecoveryCase.actions),
            selectinload(RecoveryCase.outcomes),
            selectinload(RecoveryCase.audit_logs),
        )
        .where(RecoveryCase.source_id == payload.source_id)
    )
    existing_case = existing_case_res.scalar_one_or_none()
    if existing_case:
        return existing_case

    case_id = generate_case_id()
    new_case = RecoveryCase(
        id=case_id,
        merchant_id=merchant.id,
        customer_id=customer.id,
        source_type=payload.source_type,
        source_id=payload.source_id,
        amount_at_risk=payload.amount_at_risk,
        currency=payload.currency,
        failure_reason=payload.failure_reason,
        raw_decline_code=payload.raw_decline_code,
        status=CaseState.DETECTED.value,
        priority=payload.priority or 50,
    )
    db.add(new_case)
    await db.flush()

    # Add initial creation audit log
    initial_audit = AuditLog(
        case_id=new_case.id,
        event_type="CASE_DETECTED",
        payload={
            "amount_at_risk": payload.amount_at_risk,
            "failure_reason": payload.failure_reason,
            "source_type": payload.source_type,
            "source_id": payload.source_id,
        },
    )
    db.add(initial_audit)
    await db.commit()

    # Return refreshed case with relations
    res = await db.execute(
        select(RecoveryCase)
        .options(
            selectinload(RecoveryCase.actions),
            selectinload(RecoveryCase.outcomes),
            selectinload(RecoveryCase.audit_logs),
        )
        .where(RecoveryCase.id == new_case.id)
    )
    return res.scalar_one()

@router.get("", response_model=CaseListResponse)
async def list_recovery_cases(
    status_filter: Optional[str] = Query(None, alias="status"),
    source_type: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    query = select(RecoveryCase).options(
        selectinload(RecoveryCase.actions),
        selectinload(RecoveryCase.outcomes),
        selectinload(RecoveryCase.audit_logs),
    )

    if status_filter:
        query = query.where(RecoveryCase.status == status_filter.upper())
    if source_type:
        query = query.where(RecoveryCase.source_type == source_type)

    query = query.order_by(RecoveryCase.created_at.desc()).offset(offset).limit(limit)
    cases_res = await db.execute(query)
    cases = cases_res.scalars().all()

    # Aggregate KPIs
    total_res = await db.execute(select(func.count(RecoveryCase.id)))
    total = total_res.scalar() or 0

    at_risk_res = await db.execute(select(func.sum(RecoveryCase.amount_at_risk)))
    at_risk_total = at_risk_res.scalar() or 0.0

    recovered_cases_res = await db.execute(
        select(func.count(RecoveryCase.id)).where(RecoveryCase.status == CaseState.RECOVERED.value)
    )
    recovered_count = recovered_cases_res.scalar() or 0

    recovered_total_res = await db.execute(
        select(func.sum(RecoveryCase.amount_at_risk)).where(RecoveryCase.status == CaseState.RECOVERED.value)
    )
    recovered_total = recovered_total_res.scalar() or 0.0

    return CaseListResponse(
        total=total,
        recovered_count=recovered_count,
        at_risk_total=float(at_risk_total),
        recovered_total=float(recovered_total),
        cases=cases,
    )

@router.get("/{case_id}", response_model=CaseResponse)
async def get_case_detail(
    case_id: str,
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(RecoveryCase)
        .options(
            selectinload(RecoveryCase.actions),
            selectinload(RecoveryCase.outcomes),
            selectinload(RecoveryCase.audit_logs),
        )
        .where(RecoveryCase.id == case_id)
    )
    res = await db.execute(query)
    case = res.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail=f"Case with ID '{case_id}' not found.")
    return case

@router.get("/{case_id}/audit", response_model=list[AuditLogResponse])
async def get_case_audit_trail(
    case_id: str,
    db: AsyncSession = Depends(get_db),
):
    query = select(AuditLog).where(AuditLog.case_id == case_id).order_by(AuditLog.created_at.asc())
    res = await db.execute(query)
    logs = res.scalars().all()
    return logs

@router.post("/{case_id}/transition", response_model=CaseResponse)
async def transition_case_state_endpoint(
    case_id: str,
    payload: CaseTransitionRequest,
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(RecoveryCase)
        .options(
            selectinload(RecoveryCase.actions),
            selectinload(RecoveryCase.outcomes),
            selectinload(RecoveryCase.audit_logs),
        )
        .where(RecoveryCase.id == case_id)
    )
    res = await db.execute(query)
    case = res.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail=f"Case with ID '{case_id}' not found.")

    try:
        updated_case = await transition_case(
            session=db,
            case=case,
            target_state=CaseState(payload.target_state.upper()),
            reason=payload.reason,
            metadata=payload.metadata,
            agent_run_id=payload.agent_run_id,
        )
        return updated_case
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown state: {payload.target_state}")

@router.post("/{case_id}/actions/{action_id}/execute", response_model=CaseResponse)
async def execute_case_action_endpoint(
    case_id: str,
    action_id: str,
    simulate_failure: bool = Query(False, description="Simulate Razorpay API 500 outage to test failure guard"),
    db: AsyncSession = Depends(get_db),
):
    from app.domain.failure_recovery import execute_recovery_action_with_failure_guard
    try:
        updated_case = await execute_recovery_action_with_failure_guard(
            case_id=case_id,
            action_id=action_id,
            db=db,
            simulate_gateway_outage=simulate_failure,
        )
        return updated_case
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
