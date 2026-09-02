import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_case_lifecycle_api(client: AsyncClient):
    # 1. Create a new case
    create_payload = {
        "merchant_id": "m_test_api",
        "customer_id": "c_test_api",
        "source_type": "payment_failed",
        "source_id": "pay_api_001",
        "amount_at_risk": 35000.0,
        "currency": "INR",
        "failure_reason": "insufficient_funds",
        "raw_decline_code": "NPCI_U19",
        "priority": 85,
    }
    create_res = await client.post("/api/v1/cases", json=create_payload)
    assert create_res.status_code == 201
    case_data = create_res.json()
    case_id = case_data["id"]
    assert case_id.startswith("RR-")
    assert case_data["status"] == "DETECTED"
    assert case_data["amount_at_risk"] == 35000.0
    assert len(case_data["audit_logs"]) == 1
    assert case_data["audit_logs"][0]["event_type"] == "CASE_DETECTED"

    # 2. Test idempotency with duplicate source_id
    dup_res = await client.post("/api/v1/cases", json=create_payload)
    assert dup_res.status_code == 201
    assert dup_res.json()["id"] == case_id

    # 3. Query case detail
    detail_res = await client.get(f"/api/v1/cases/{case_id}")
    assert detail_res.status_code == 200
    assert detail_res.json()["id"] == case_id

    # 4. List cases and verify KPIs
    list_res = await client.get("/api/v1/cases")
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert list_data["total"] >= 1
    assert list_data["at_risk_total"] >= 35000.0

    # 5. Transition state: DETECTED -> INVESTIGATING
    trans_res = await client.post(
        f"/api/v1/cases/{case_id}/transition",
        json={
            "target_state": "INVESTIGATING",
            "reason": "Agent started analysis",
            "metadata": {"analysis_mode": "deep"},
        },
    )
    assert trans_res.status_code == 200
    assert trans_res.json()["status"] == "INVESTIGATING"

    # 6. Attempt illegal transition: INVESTIGATING -> RECOVERED (must fail with 400)
    bad_trans_res = await client.post(
        f"/api/v1/cases/{case_id}/transition",
        json={
            "target_state": "RECOVERED",
            "reason": "Illegal shortcut",
        },
    )
    assert bad_trans_res.status_code == 400
    assert "cannot move from 'INVESTIGATING' to 'RECOVERED'" in bad_trans_res.json()["detail"]

    # 7. Check audit trail
    audit_res = await client.get(f"/api/v1/cases/{case_id}/audit")
    assert audit_res.status_code == 200
    audit_logs = audit_res.json()
    assert len(audit_logs) == 2
    assert audit_logs[0]["event_type"] == "CASE_DETECTED"
    assert audit_logs[1]["event_type"] == "STATE_TRANSITION"

@pytest.mark.asyncio
async def test_case_not_found(client: AsyncClient):
    res = await client.get("/api/v1/cases/RR-NONEXISTENT")
    assert res.status_code == 404
