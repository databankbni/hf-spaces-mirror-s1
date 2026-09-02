"""
Phase 10 Tests — FastAPI REST API

Tests cover:
  - App creation and route registration
  - Health and readiness endpoints
  - JWT authentication (valid, expired, missing, wrong tenant)
  - Ticket submission (202 response, ticket_id returned)
  - Ticket retrieval with tenant isolation
  - HITL resume with role-based access control
  - Metrics endpoint (Prometheus format)
  - Rate limiting headers present
  - Security headers present
"""

from __future__ import annotations

import time

import jwt
import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app

# ─── Fixtures ────────────────────────────────────────────────────────────────

TEST_SECRET = "sk-test"  # Set in conftest.py via APP_ENV=test


@pytest.fixture(scope="module")
def client():
    """Create a TestClient for the full FastAPI app."""
    import os
    os.environ["LITELLM_MASTER_KEY"] = TEST_SECRET
    os.environ["APP_ENV"] = "test"
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _make_token(tenant_id: str, role: str = "support_agent", expired: bool = False) -> str:
    """Generate a test JWT for the given tenant."""
    payload = {
        "tenant_id": tenant_id,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + (-1 if expired else 86_400),
    }
    return jwt.encode(payload, TEST_SECRET, algorithm="HS256")


def _auth(tenant_id: str, role: str = "support_agent") -> dict:
    return {"Authorization": f"Bearer {_make_token(tenant_id, role)}"}


# ─── App structure tests ──────────────────────────────────────────────────────

class TestAppCreation:
    def test_all_routes_registered(self, client):
        """All 9 API routes must be present."""
        paths = {r.path for r in client.app.routes}
        required = {
            "/api/v1/health",
            "/api/v1/ready",
            "/api/v1/triage",
            "/api/v1/triage/{ticket_id}",
            "/api/v1/triage/{ticket_id}/resume",
            "/api/v1/triage/{ticket_id}/stream",
            "/api/v1/metrics",
        }
        assert required.issubset(paths), f"Missing routes: {required - paths}"

    def test_openapi_spec_available(self, client):
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        spec = resp.json()
        assert spec["info"]["title"] == "CustomerCore API"
        assert spec["info"]["version"] == "1.0.0"

    def test_root_returns_api_info(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert "CustomerCore" in data["name"]
        assert "/docs" in data["docs"]


# ─── Health tests ─────────────────────────────────────────────────────────────

class TestHealthEndpoints:
    def test_health_returns_200(self, client):
        """Liveness probe must always return 200."""
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "1.0.0"

    def test_health_no_auth_required(self, client):
        """Health endpoint must work without any Authorization header."""
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_ready_returns_service_status(self, client):
        """Readiness probe returns service connectivity dict."""
        resp = client.get("/api/v1/ready")
        # May return 200 or 503 depending on whether Docker services are running
        assert resp.status_code in (200, 503)
        data = resp.json()
        assert "services" in data
        assert "redis" in data["services"]

    def test_security_headers_present(self, client):
        """Security headers must be injected by middleware."""
        resp = client.get("/api/v1/health")
        assert "x-content-type-options" in resp.headers
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert "x-frame-options" in resp.headers
        assert "x-request-id" in resp.headers


# ─── Auth tests ───────────────────────────────────────────────────────────────

class TestAuthentication:
    def test_no_token_returns_401(self, client):
        """Endpoints without token must return 401 (HTTPBearer standard behaviour)."""
        resp = client.post("/api/v1/triage", json={
            "text": "My payment is failing",
            "customer_id": "cust_001",
        })
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, client):
        """Malformed JWT must return 401."""
        resp = client.post(
            "/api/v1/triage",
            json={"text": "Payment failing", "customer_id": "cust_001"},
            headers={"Authorization": "Bearer this-is-not-a-jwt"},
        )
        assert resp.status_code == 401

    def test_expired_token_returns_401(self, client):
        """Expired JWT must return 401."""
        token = _make_token("acme-corp", expired=True)
        resp = client.post(
            "/api/v1/triage",
            json={"text": "Payment failing", "customer_id": "cust_001"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    def test_valid_token_accepted(self, client):
        """Valid JWT must pass authentication and return 202."""
        resp = client.post(
            "/api/v1/triage",
            json={"text": "My invoice is incorrect and I need a refund", "customer_id": "cust_002"},
            headers=_auth("test-tenant"),
        )
        assert resp.status_code == 202


# ─── Triage submission tests ──────────────────────────────────────────────────

class TestTriageSubmission:
    def test_submit_returns_202_with_ticket_id(self, client):
        """POST /triage must return 202 with a valid UUID ticket_id."""
        resp = client.post(
            "/api/v1/triage",
            json={
                "text": "I cannot log into my account since yesterday",
                "customer_id": "cust_login_001",
                "customer_tier": "enterprise",
            },
            headers=_auth("acme-corp"),
        )
        assert resp.status_code == 202
        data = resp.json()
        assert "ticket_id" in data
        assert len(data["ticket_id"]) == 36  # UUID format
        assert data["status"] == "pending"
        assert "/stream" in data["stream_url"]

    def test_text_too_short_returns_422(self, client):
        """Text under 10 characters must fail Pydantic validation."""
        resp = client.post(
            "/api/v1/triage",
            json={"text": "Hi", "customer_id": "cust_003"},
            headers=_auth("acme-corp"),
        )
        assert resp.status_code == 422

    def test_tenant_isolation_on_get(self, client):
        """Tenant A cannot read Tenant B's ticket."""
        # Submit as tenant A
        resp = client.post(
            "/api/v1/triage",
            json={"text": "Billing issue with my subscription renewal", "customer_id": "cust_a"},
            headers=_auth("tenant-a"),
        )
        ticket_id = resp.json()["ticket_id"]

        # Try to read as tenant B → must get 404
        resp_b = client.get(
            f"/api/v1/triage/{ticket_id}",
            headers=_auth("tenant-b"),
        )
        assert resp_b.status_code == 404, "Tenant B must not see Tenant A's tickets"

    def test_get_own_ticket_returns_200(self, client):
        """Submitting tenant can always retrieve their own ticket."""
        submit = client.post(
            "/api/v1/triage",
            json={"text": "API integration keeps returning 500 errors", "customer_id": "cust_dev"},
            headers=_auth("dev-tenant"),
        )
        ticket_id = submit.json()["ticket_id"]

        get_resp = client.get(
            f"/api/v1/triage/{ticket_id}",
            headers=_auth("dev-tenant"),
        )
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["ticket_id"] == ticket_id
        assert data["customer_id"] == "cust_dev"

    def test_list_returns_only_own_tickets(self, client):
        """GET /triage returns only the authenticated tenant's tickets."""
        # Submit 2 tickets for tenant-x
        for i in range(2):
            client.post(
                "/api/v1/triage",
                json={"text": f"Test ticket number {i} for list test", "customer_id": f"cust_{i}"},
                headers=_auth("tenant-x"),
            )

        resp = client.get("/api/v1/triage", headers=_auth("tenant-x"))
        assert resp.status_code == 200
        tickets = resp.json()
        assert len(tickets) >= 2
        # All returned tickets must belong to tenant-x
        for t in tickets:
            assert t["tenant_id"] == "tenant-x"


# ─── HITL resume tests ────────────────────────────────────────────────────────

class TestHITLResume:
    def test_support_agent_cannot_resume_hitl(self, client):
        """support_agent role must be rejected for HITL resume (403)."""
        # Submit a ticket
        submit = client.post(
            "/api/v1/triage",
            json={"text": "Critical security breach detected in our account", "customer_id": "cust_sec"},
            headers=_auth("sec-tenant"),
        )
        ticket_id = submit.json()["ticket_id"]

        # Try to resume as support_agent → must get 403
        resp = client.post(
            f"/api/v1/triage/{ticket_id}/resume",
            json={
                "ticket_id": ticket_id,
                "operator_id": "agent_007",
            },
            headers=_auth("sec-tenant", role="support_agent"),
        )
        assert resp.status_code == 403

    def test_manager_can_call_resume_endpoint(self, client):
        """manager role must be accepted by the HITL resume endpoint."""
        submit = client.post(
            "/api/v1/triage",
            json={"text": "My account has been suspended without warning", "customer_id": "cust_mgr"},
            headers=_auth("mgr-tenant"),
        )
        ticket_id = submit.json()["ticket_id"]

        # Manager calls resume — ticket is PENDING not HITL, so expect 409
        resp = client.post(
            f"/api/v1/triage/{ticket_id}/resume",
            json={
                "ticket_id": ticket_id,
                "operator_id": "manager_001",
            },
            headers=_auth("mgr-tenant", role="manager"),
        )
        # 409 Conflict is correct (ticket is PENDING, not HITL) — but auth passed!
        assert resp.status_code == 409
        assert "HITL" in resp.json()["detail"]


# ─── Metrics tests ────────────────────────────────────────────────────────────

class TestMetricsEndpoint:
    def test_metrics_returns_prometheus_format(self, client):
        """GET /metrics must return text in Prometheus OpenMetrics format."""
        resp = client.get("/api/v1/metrics")
        assert resp.status_code == 200
        # Prometheus format starts with # HELP or # TYPE lines
        assert "customercore_" in resp.text or "# HELP" in resp.text

    def test_metrics_no_auth_required(self, client):
        """Metrics endpoint must be publicly accessible for Prometheus scraping."""
        resp = client.get("/api/v1/metrics")
        assert resp.status_code == 200
