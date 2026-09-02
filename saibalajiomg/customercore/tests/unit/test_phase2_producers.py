"""
tests/unit/test_phase2_producers.py

Phase 2 verification tests.
Tests that:
1. All 4 producer modules import correctly
2. Event factory functions return valid, schema-compliant dicts
3. All required fields are present and correctly typed
"""

from src.streaming.producers.ticket_producer import make_ticket
from src.streaming.producers.billing_producer import make_billing_event
from src.streaming.producers.product_producer import make_product_event
from src.streaming.producers.incident_producer import make_incident_event


# ── Ticket Producer Tests ─────────────────────────────────────

class TestTicketProducer:
    REQUIRED_FIELDS = [
        "event_id", "event_type", "timestamp", "tenant_id",
        "ticket_id", "customer_id", "customer_tier", "subject",
        "body", "category", "priority", "channel",
    ]

    def test_ticket_has_all_required_fields(self):
        ticket = make_ticket()
        for field in self.REQUIRED_FIELDS:
            assert field in ticket, f"Missing field: {field}"

    def test_ticket_event_type_is_correct(self):
        ticket = make_ticket()
        assert ticket["event_type"] == "support_ticket_created"

    def test_ticket_priority_is_valid(self):
        for _ in range(20):
            ticket = make_ticket()
            assert ticket["priority"] in ["low", "medium", "high", "critical"]

    def test_ticket_tier_is_valid(self):
        for _ in range(20):
            ticket = make_ticket()
            assert ticket["customer_tier"] in ["enterprise", "professional", "free"]

    def test_ticket_id_has_correct_prefix(self):
        ticket = make_ticket()
        assert ticket["ticket_id"].startswith("TKT-")

    def test_ticket_is_json_serializable(self):
        import json
        ticket = make_ticket()
        serialized = json.dumps(ticket)
        assert len(serialized) > 0


# ── Billing Producer Tests ────────────────────────────────────

class TestBillingProducer:
    REQUIRED_FIELDS = [
        "event_id", "event_type", "timestamp", "tenant_id",
        "customer_id", "invoice_id", "amount", "currency", "plan",
    ]

    def test_billing_has_all_required_fields(self):
        event = make_billing_event()
        for field in self.REQUIRED_FIELDS:
            assert field in event, f"Missing field: {field}"

    def test_billing_amount_is_positive(self):
        for _ in range(10):
            event = make_billing_event()
            assert event["amount"] > 0

    def test_billing_currency_is_valid(self):
        for _ in range(10):
            event = make_billing_event()
            assert event["currency"] in ["USD", "EUR", "GBP"]

    def test_billing_invoice_id_has_correct_prefix(self):
        event = make_billing_event()
        assert event["invoice_id"].startswith("INV-")


# ── Product Producer Tests ────────────────────────────────────

class TestProductProducer:
    REQUIRED_FIELDS = [
        "event_id", "event_type", "timestamp", "tenant_id",
        "customer_id", "feature", "sentiment", "sentiment_score",
    ]

    def test_product_has_all_required_fields(self):
        event = make_product_event()
        for field in self.REQUIRED_FIELDS:
            assert field in event, f"Missing field: {field}"

    def test_sentiment_score_in_range(self):
        for _ in range(20):
            event = make_product_event()
            assert -1.0 <= event["sentiment_score"] <= 1.0

    def test_satisfaction_rating_in_range(self):
        for _ in range(20):
            event = make_product_event()
            assert 1 <= event["satisfaction_rating"] <= 10


# ── Incident Producer Tests ───────────────────────────────────

class TestIncidentProducer:
    REQUIRED_FIELDS = [
        "event_id", "event_type", "timestamp", "incident_id",
        "severity", "status", "affected_service", "affected_tenants",
        "ticket_count", "auto_escalated",
    ]

    def test_incident_has_all_required_fields(self):
        event = make_incident_event()
        for field in self.REQUIRED_FIELDS:
            assert field in event, f"Missing field: {field}"

    def test_severity_is_valid(self):
        for _ in range(20):
            event = make_incident_event()
            assert event["severity"] in ["P1", "P2", "P3", "P4"]

    def test_p1_p2_are_auto_escalated(self):
        for _ in range(50):
            event = make_incident_event()
            if event["severity"] in ["P1", "P2"]:
                assert event["auto_escalated"] is True

    def test_affected_tenants_is_list(self):
        event = make_incident_event()
        assert isinstance(event["affected_tenants"], list)
        assert len(event["affected_tenants"]) >= 1

    def test_incident_id_has_correct_prefix(self):
        event = make_incident_event()
        assert event["incident_id"].startswith("INC-")
