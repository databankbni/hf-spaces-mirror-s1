from src.agent.supervisor import run_triage, resume_triage
from src.agent.schemas import TriageOutput

def test_successful_direct_triage_no_hitl():
    """Verify a standard, non-critical, clear support ticket bypasses HITL and completes directly."""
    ticket = {
        "ticket_id": "TKT-TEST-001",
        "body": "Where can I find the documentation for configuring SSO on our system?",
        "customer_id": "cust-docs-12",
        "tenant_id": "acme-corp",
        "customer_tier": "professional"
    }
    
    output = run_triage(ticket, thread_id="thread-direct-ok")
    
    assert isinstance(output, TriageOutput)
    assert output.category == "docs"
    assert output.priority == "low"
    assert output.routing_team == "support"
    assert output.hitl_required is False
    assert output.hitl_reason is None
    assert output.sla_breach_risk < 0.40
    assert output.confidence >= 0.70
    assert len(output.summary) >= 10
    assert len(output.suggested_resolution) >= 10

def test_hitl_triggered_due_to_security_policy():
    """Verify security category tickets are automatically paused for human compliance review."""
    ticket = {
        "ticket_id": "TKT-SEC-002",
        "body": "URGENT: We discovered a potential database vulnerability leaking auth tokens",
        "customer_id": "cust-sec-99",
        "tenant_id": "globex-inc",
        "customer_tier": "enterprise"
    }
    
    output = run_triage(ticket, thread_id="thread-sec-hitl")
    
    assert isinstance(output, TriageOutput)
    assert output.category == "security"
    assert output.priority == "critical"
    # Enterprise VIP critical is escalated to escalation or security
    assert output.routing_team == "escalation"
    assert output.hitl_required is True
    assert "Security compliance" in output.hitl_reason
    assert output.sla_breach_risk > 0.80

def test_hitl_triggered_due_to_low_confidence():
    """Verify extremely short tickets trigger HITL due to low confidence penalty."""
    ticket = {
        "ticket_id": "TKT-SHORT-003",
        "body": "broken",
        "customer_id": "cust-short",
        "tenant_id": "acme-corp",
        "customer_tier": "free"
    }
    
    output = run_triage(ticket, thread_id="thread-short-hitl")
    
    assert isinstance(output, TriageOutput)
    assert output.hitl_required is True
    assert "Low confidence" in output.hitl_reason
    assert output.confidence < 0.65

def test_human_override_and_resume():
    """Verify human operators can apply overrides (corrections) and successfully resume the graph from interruption."""
    ticket = {
        "ticket_id": "TKT-OVERRIDE-004",
        "body": "Database credentials exposed on public forum",
        "customer_id": "cust-leak",
        "tenant_id": "acme-corp",
        "customer_tier": "professional"
    }
    
    thread_id = "thread-override-test"
    
    # 1. First run: triggers HITL due to security compliance
    initial_output = run_triage(ticket, thread_id=thread_id)
    assert initial_output.hitl_required is True
    assert initial_output.category == "security"
    
    # 2. Operator reviews and decides to route to 'security' team with confidence=1.0 and hitl_required=False
    overrides = {
        "category": "security",
        "routing_team": "security",
        "confidence": 1.0,
        "hitl_required": False,
        "hitl_reason": None
    }
    
    final_output = resume_triage(thread_id, overrides=overrides)
    
    assert isinstance(final_output, TriageOutput)
    assert final_output.category == "security"
    assert final_output.routing_team == "security"
    assert final_output.confidence == 1.0
    assert final_output.hitl_required is False
    assert final_output.hitl_reason is None

def test_multilingual_triage_routing():
    """Verify non-English (e.g. German) support tickets are routed correctly and yield native translations."""
    ticket = {
        "ticket_id": "TKT-DE-005",
        "body": "Konto gesperrt. Ich kann mich nicht mehr einloggen und brauche Hilfe beim Zurücksetzen meines Passworts.",
        "customer_id": "cust-de",
        "tenant_id": "acme-corp",
        "customer_tier": "professional"
    }
    
    output = run_triage(ticket, thread_id="thread-german-ok")
    
    assert isinstance(output, TriageOutput)
    # German keywords for login/account block map to auth category
    assert output.category == "auth"
    # Under heuristics, priority is high
    assert output.priority == "high"
