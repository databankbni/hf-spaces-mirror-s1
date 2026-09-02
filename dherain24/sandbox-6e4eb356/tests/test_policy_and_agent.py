import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RecoveryCase, RecoveryAction, Merchant, Customer
from app.policies.rules import evaluate_policy, MerchantPolicy
from app.agents.prompt_builder import synthesize_error_code
from app.domain.state_machine import CaseState

def test_error_code_synthesis():
    semantic, expl = synthesize_error_code("NPCI_U19_ERR", "default")
    assert semantic == "insufficient_funds"
    assert "balance" in expl.lower()

    semantic_exp, expl_exp = synthesize_error_code("CARD_EXPIRED_01", "default")
    assert semantic_exp == "expired_payment_method"

    semantic_unk, _ = synthesize_error_code("RANDOM_CUSTOM_CODE", "payment_failed")
    assert semantic_unk == "payment_failed"

def test_policy_high_value_escalation():
    policy = MerchantPolicy(human_approval_threshold=100000.0)
    case = RecoveryCase(
        id="RR-HIGH",
        merchant_id="m1",
        customer_id="c1",
        source_type="payment_failed",
        source_id="p1",
        amount_at_risk=150000.0,
        failure_reason="insufficient_funds",
    )
    result = evaluate_policy(case, "delayed_retry", {}, [], policy)
    assert result.approval_required is True
    assert result.policy_status == "APPROVAL_REQUIRED"
    assert any("exceeds human approval threshold" in v for v in result.violations)

def test_policy_retry_budget_and_cooldown():
    policy = MerchantPolicy(max_retries=2, retry_cooldown_hours=24.0)
    case = RecoveryCase(
        id="RR-RETRY",
        merchant_id="m1",
        customer_id="c1",
        source_type="payment_failed",
        source_id="p2",
        amount_at_risk=10000.0,
        failure_reason="insufficient_funds",
    )
    
    # 1. First retry - Allowed
    res1 = evaluate_policy(case, "delayed_retry", {}, [], policy)
    assert res1.is_allowed is True

    # 2. Within cooldown (executed 2 hours ago) - Blocked
    prior1 = RecoveryAction(
        id="act1",
        case_id="RR-RETRY",
        action_type="delayed_retry",
        executed_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    res2 = evaluate_policy(case, "delayed_retry", {}, [prior1], policy)
    assert res2.is_allowed is False
    assert any("Cooldown active" in v for v in res2.violations)

    # 3. Exhausted retries (2 prior retries outside cooldown) - Blocked
    prior2 = RecoveryAction(
        id="act2",
        case_id="RR-RETRY",
        action_type="delayed_retry",
        executed_at=datetime.now(timezone.utc) - timedelta(hours=30),
    )
    res3 = evaluate_policy(case, "delayed_retry", {}, [prior1, prior2], policy)
    assert res3.is_allowed is False
    assert any("Retry budget exhausted" in v for v in res3.violations)

def test_policy_no_action_always_safe():
    case = RecoveryCase(
        id="RR-SAFE",
        merchant_id="m1",
        customer_id="c1",
        source_type="payment_failed",
        source_id="p3",
        amount_at_risk=200000.0,  # Even high value
        failure_reason="repeated_failures",
    )
    res = evaluate_policy(case, "no_action", {}, [])
    assert res.is_allowed is True
    assert res.policy_status == "APPROVED"
    assert res.approval_required is False

@pytest.mark.asyncio
async def test_agent_investigate_api_standard_case(client: AsyncClient):
    # 1. Create a case for ₹25,000
    create_res = await client.post(
        "/api/v1/cases",
        json={
            "merchant_id": "m_agent_1",
            "customer_id": "c_agent_1",
            "source_type": "payment_failed",
            "source_id": "pay_agent_001",
            "amount_at_risk": 25000.0,
            "failure_reason": "insufficient_funds",
            "raw_decline_code": "NPCI_U19",
        },
    )
    case_id = create_res.json()["id"]

    # 2. Trigger investigation
    inv_res = await client.post(f"/api/v1/cases/{case_id}/investigate")
    assert inv_res.status_code == 200, f"Investigation failed with: {inv_res.json()}"
    case_data = inv_res.json()

    # Should be APPROVED because ₹25k is within auto limits
    assert case_data["status"] == "APPROVED"
    assert len(case_data["actions"]) >= 1
    action = case_data["actions"][0]
    assert action["action_type"] in ["delayed_retry", "payment_link"]
    assert action["policy_status"] == "APPROVED"
    assert "rationale" in action["parameters"]

@pytest.mark.asyncio
async def test_agent_investigate_api_high_value_case(client: AsyncClient):
    # Create ₹1,50,000 case (exceeds threshold)
    create_res = await client.post(
        "/api/v1/cases",
        json={
            "merchant_id": "m_agent_2",
            "customer_id": "c_agent_2",
            "source_type": "payment_failed",
            "source_id": "pay_agent_002",
            "amount_at_risk": 150000.0,
            "failure_reason": "insufficient_funds",
        },
    )
    case_id = create_res.json()["id"]

    # Trigger investigation
    inv_res = await client.post(f"/api/v1/cases/{case_id}/investigate")
    assert inv_res.status_code == 200
    case_data = inv_res.json()

    # Must be ESCALATED for human review
    assert case_data["status"] == "ESCALATED"
    action = case_data["actions"][0]
    assert action["approval_required"] is True

@pytest.mark.asyncio
async def test_policy_api_get_and_update(client: AsyncClient):
    # Get current policy
    get_res = await client.get("/api/v1/policies")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["max_retries"] == 2

    # Update policy
    update_res = await client.put(
        "/api/v1/policies",
        json={
            "max_retries": 3,
            "retry_cooldown_hours": 12.0,
            "max_contacts_per_7d": 2,
            "auto_action_max_amount": 60000.0,
            "human_approval_threshold": 120000.0,
            "recovery_window_days": 10,
        },
    )
    assert update_res.status_code == 200
    updated = update_res.json()
    assert updated["max_retries"] == 3
    assert updated["human_approval_threshold"] == 120000.0
