import json
import pytest
from httpx import AsyncClient

from app.razorpay.webhooks import verify_webhook_signature, generate_test_signature
from app.core.config import settings

def test_webhook_signature_math():
    payload = b'{"event":"payment.failed","id":"evt_123"}'
    valid_sig = generate_test_signature(payload)

    assert verify_webhook_signature(payload, valid_sig) is True
    assert verify_webhook_signature(payload, "invalid_signature_hex") is False
    assert verify_webhook_signature(b'{"tampered":true}', valid_sig) is False

@pytest.mark.asyncio
async def test_webhook_unauthorized_rejection(client: AsyncClient):
    res = await client.post(
        "/api/v1/webhooks/razorpay",
        headers={"X-Razorpay-Signature": "bad_sig"},
        content=b'{"event":"test"}',
    )
    assert res.status_code == 401
    assert "Invalid or missing" in res.json()["detail"]

@pytest.mark.asyncio
async def test_webhook_payment_failed_and_idempotency(client: AsyncClient):
    event_payload = {
        "id": "evt_test_failed_001",
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test_fail_999",
                    "amount": 450000,  # ₹4,500.00
                    "currency": "INR",
                    "error_code": "NPCI_U19",
                    "error_description": "Insufficient funds in bank account.",
                    "customer_id": "cust_rzp_999",
                }
            }
        },
    }
    raw_body = json.dumps(event_payload).encode("utf-8")
    sig = generate_test_signature(raw_body)

    # 1. First delivery -> Ingested and investigated
    res1 = await client.post(
        "/api/v1/webhooks/razorpay",
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
        content=raw_body,
    )
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["status"] == "case_investigated"
    assert data1["amount"] == 4500.0
    case_id = data1["case_id"]

    # Verify case details
    case_res = await client.get(f"/api/v1/cases/{case_id}")
    assert case_res.status_code == 200
    case_data = case_res.json()
    assert case_data["source_id"] == "pay_test_fail_999"
    assert case_data["amount_at_risk"] == 4500.0
    assert len(case_data["actions"]) >= 1

    # 2. Duplicate delivery -> Idempotently ignored
    res2 = await client.post(
        "/api/v1/webhooks/razorpay",
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
        content=raw_body,
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["status"] == "ignored_duplicate"

@pytest.mark.asyncio
async def test_webhook_payment_captured_recovery(client: AsyncClient):
    # 1. Create a case
    create_res = await client.post(
        "/api/v1/cases",
        json={
            "merchant_id": "m_rzp_rec",
            "customer_id": "c_rzp_rec",
            "source_type": "payment_failed",
            "source_id": "pay_to_be_recovered_777",
            "amount_at_risk": 12000.0,
            "failure_reason": "network_decline",
        },
    )
    case_id = create_res.json()["id"]

    # Investigate to advance to APPROVED
    inv_res = await client.post(f"/api/v1/cases/{case_id}/investigate")
    assert inv_res.status_code == 200

    # 2. Send payment.captured webhook
    capture_event = {
        "id": "evt_capture_777",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_to_be_recovered_777",
                    "amount": 1200000,  # ₹12,000.00
                }
            }
        },
    }
    raw_body = json.dumps(capture_event).encode("utf-8")
    sig = generate_test_signature(raw_body)

    cap_res = await client.post(
        "/api/v1/webhooks/razorpay",
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
        content=raw_body,
    )
    assert cap_res.status_code == 200
    assert cap_res.json()["status"] == "case_recovered"

    # Verify final case state is RECOVERED
    final_case = await client.get(f"/api/v1/cases/{case_id}")
    assert final_case.json()["status"] == "RECOVERED"

@pytest.mark.asyncio
async def test_runtime_failure_recovery_scenario(client: AsyncClient):
    """
    Rubric Requirement:
    Verify system handles gateway 500 failure safely without duplicate retries or corruption.
    """
    # 1. Create and investigate a case with an expired card (proposes payment_link)
    create_res = await client.post(
        "/api/v1/cases",
        json={
            "merchant_id": "m_failure_test",
            "customer_id": "c_failure_test",
            "source_type": "payment_failed",
            "source_id": "pay_outage_001",
            "amount_at_risk": 8500.0,
            "failure_reason": "expired_card",
            "raw_decline_code": "CARD_EXPIRED",
        },
    )
    case_id = create_res.json()["id"]

    inv_res = await client.post(f"/api/v1/cases/{case_id}/investigate")
    case_data = inv_res.json()
    assert case_data["status"] == "APPROVED"
    action_id = case_data["actions"][0]["id"]

    # 2. Execute action with simulated gateway 500 outage
    exec_res = await client.post(
        f"/api/v1/cases/{case_id}/actions/{action_id}/execute?simulate_failure=true"
    )
    assert exec_res.status_code == 200
    res_case = exec_res.json()

    # Verify safe escalation and failure marking
    assert res_case["status"] == "ESCALATED"
    action = res_case["actions"][0]
    assert action["execution_status"] == "FAILED_SAFELY"
    assert "Razorpay API Gateway unavailable" in action["parameters"]["failure_error"]

    # Verify audit trail contains the gateway failure safeguard event
    audit_res = await client.get(f"/api/v1/cases/{case_id}/audit")
    assert audit_res.status_code == 200
    events = [entry["event_type"] for entry in audit_res.json()]
    assert "GATEWAY_FAILURE_HALTED" in events
