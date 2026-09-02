"""
Phase 11 Tests — Langfuse LLM Tracing + Constitutional Policy Engine

Tests cover:
  Constitutional Policy Engine:
    - Clean response passes all rules
    - PII detection (email, phone, credit card, IBAN)
    - AI identity denial detection
    - Commitment/promise detection
    - Scope limitation (legal/medical/financial advice)
    - Toxicity detection
    - Language consistency (German ticket, English response)
    - Competitor disparagement
    - Score calculation (violations reduce score)
    - Critical violations trigger BLOCK action
    - VIOLATION level triggers REGENERATE/REDACT
    - Multiple violations accumulate correctly
    - Empty response is blocked
    - Rule addition and removal

  Langfuse Tracer:
    - TriageTrace.start() returns valid object when keys missing (no-op)
    - TriageTrace works as context manager for agent spans
    - No exceptions raised when Langfuse not configured
"""

from __future__ import annotations


from src.responsible_ai.constitutional_policy import (
    ConstitutionalPolicyEngine,
    RemediationAction,
    RuleSeverity,
    ConstitutionalRule,
    RuleViolation,
    policy_engine,
)
from src.monitoring.langfuse_tracer import TriageTrace, _is_langfuse_configured


# ─────────────────────────────────────────────────────────────────────────────
# Constitutional Policy Engine Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestCleanResponse:
    """A well-written, safe response passes all rules."""

    CLEAN = (
        "Thank you for reaching out. I understand you are experiencing an issue "
        "with your payment processing. Our team has reviewed your account and "
        "can see the failed transactions. Please try again with a different payment "
        "method, or contact your bank to verify there are no restrictions on the card. "
        "If the issue persists, please reply to this message and we will escalate to "
        "our billing team for a manual review."
    )

    def test_clean_response_passes(self):
        verdict = policy_engine.evaluate(self.CLEAN)
        assert verdict.passed is True

    def test_clean_response_score_high(self):
        verdict = policy_engine.evaluate(self.CLEAN)
        assert verdict.score >= 0.9

    def test_clean_response_action_allow(self):
        verdict = policy_engine.evaluate(self.CLEAN)
        assert verdict.action in (RemediationAction.ALLOW, RemediationAction.WARN)

    def test_clean_response_no_violations(self):
        verdict = policy_engine.evaluate(self.CLEAN)
        assert verdict.violations == []


class TestPIIDetection:
    """PII in responses must be caught with CRITICAL severity."""

    def test_email_detected(self):
        verdict = policy_engine.evaluate(
            "Please contact admin@internal-company.com for further assistance."
        )
        assert not verdict.passed
        violation_ids = [v.rule_id for v in verdict.violations]
        assert "PII_PROTECTION" in violation_ids

    def test_phone_detected(self):
        verdict = policy_engine.evaluate(
            "You can reach our billing team at +44 20 7946 0958 between 9am and 5pm."
        )
        assert not verdict.passed
        violation_ids = [v.rule_id for v in verdict.violations]
        assert "PII_PROTECTION" in violation_ids

    def test_credit_card_detected(self):
        verdict = policy_engine.evaluate(
            "The card ending in 4532 8901 2345 6789 was declined."
        )
        pii_violations = [v for v in verdict.violations if v.rule_id == "PII_PROTECTION"]
        assert pii_violations, "Credit card number must be caught"

    def test_pii_severity_is_critical(self):
        verdict = policy_engine.evaluate("Contact us at user@example.com")
        pii_v = next((v for v in verdict.violations if v.rule_id == "PII_PROTECTION"), None)
        assert pii_v is not None
        assert pii_v.severity == RuleSeverity.CRITICAL

    def test_pii_action_is_redact(self):
        verdict = policy_engine.evaluate("Contact us at user@example.com")
        pii_v = next((v for v in verdict.violations if v.rule_id == "PII_PROTECTION"), None)
        assert pii_v is not None
        assert pii_v.action == RemediationAction.REDACT


class TestAIIdentityRule:
    """AI identity denial must be caught with CRITICAL severity and BLOCK action."""

    def test_ai_denial_caught(self):
        verdict = policy_engine.evaluate(
            "I am not an AI. I am a real human customer service representative "
            "who genuinely cares about your issue."
        )
        ai_v = next((v for v in verdict.violations if v.rule_id == "AI_IDENTITY"), None)
        assert ai_v is not None, "AI identity denial must be caught"

    def test_ai_denial_severity_critical(self):
        verdict = policy_engine.evaluate("I'm a human, not a bot.")
        ai_v = next((v for v in verdict.violations if v.rule_id == "AI_IDENTITY"), None)
        assert ai_v is not None
        assert ai_v.severity == RuleSeverity.CRITICAL

    def test_ai_denial_action_block(self):
        verdict = policy_engine.evaluate("I am not an AI — I am a person.")
        ai_v = next((v for v in verdict.violations if v.rule_id == "AI_IDENTITY"), None)
        assert ai_v is not None
        assert ai_v.action == RemediationAction.BLOCK

    def test_block_provides_safe_fallback(self):
        verdict = policy_engine.evaluate("I am not a bot. I am human.")
        assert verdict.safe_fallback is not None
        assert len(verdict.safe_fallback) > 50

    def test_truthful_ai_disclosure_passes(self):
        """Acknowledging being an AI should not trigger the rule."""
        verdict = policy_engine.evaluate(
            "I'm an AI assistant here to help you with your support request. "
            "Let me look into your billing issue right away."
        )
        ai_violations = [v for v in verdict.violations if v.rule_id == "AI_IDENTITY"]
        assert not ai_violations, "Truthful AI disclosure must not trigger the rule"


class TestCommitmentRule:
    """Definitive promises must be caught as VIOLATION severity."""

    def test_refund_promise_caught(self):
        verdict = policy_engine.evaluate(
            "We will refund the full amount to your account within 24 hours."
        )
        comm_v = next((v for v in verdict.violations if v.rule_id == "NO_COMMITMENTS"), None)
        assert comm_v is not None

    def test_guaranteed_caught(self):
        verdict = policy_engine.evaluate(
            "Your issue will be resolved, guaranteed by end of business today."
        )
        comm_v = next((v for v in verdict.violations if v.rule_id == "NO_COMMITMENTS"), None)
        assert comm_v is not None

    def test_commitment_severity_violation(self):
        verdict = policy_engine.evaluate("We will refund your payment.")
        comm_v = next((v for v in verdict.violations if v.rule_id == "NO_COMMITMENTS"), None)
        if comm_v:
            assert comm_v.severity == RuleSeverity.VIOLATION

    def test_soft_language_passes(self):
        """Hedged language should not trigger the commitment rule."""
        verdict = policy_engine.evaluate(
            "Our team will review your refund request and get back to you "
            "with an outcome within our standard processing timeframe."
        )
        comm_violations = [v for v in verdict.violations if v.rule_id == "NO_COMMITMENTS"]
        assert not comm_violations, "Hedged language should not trigger NO_COMMITMENTS"


class TestScopeRule:
    """Legal, medical, and financial advice must be blocked."""

    def test_legal_advice_caught(self):
        verdict = policy_engine.evaluate(
            "You should consult a lawyer about your contractual rights in this matter."
        )
        scope_v = next((v for v in verdict.violations if v.rule_id == "SCOPE_LIMITATION"), None)
        assert scope_v is not None

    def test_financial_advice_caught(self):
        verdict = policy_engine.evaluate(
            "Based on your financial situation, this could have tax implications."
        )
        scope_v = next((v for v in verdict.violations if v.rule_id == "SCOPE_LIMITATION"), None)
        assert scope_v is not None


class TestToxicityRule:
    """Harmful or disrespectful language must be blocked."""

    def test_abusive_language_caught(self):
        verdict = policy_engine.evaluate(
            "This error happens because your setup is completely stupid."
        )
        tox_v = next((v for v in verdict.violations if v.rule_id == "TOXICITY_GUARD"), None)
        assert tox_v is not None

    def test_blame_language_caught(self):
        verdict = policy_engine.evaluate(
            "This is entirely your fault for not reading the documentation."
        )
        tox_v = next((v for v in verdict.violations if v.rule_id == "TOXICITY_GUARD"), None)
        assert tox_v is not None

    def test_toxicity_severity_critical(self):
        verdict = policy_engine.evaluate("Your setup is completely stupid and moronic.")
        tox_v = next((v for v in verdict.violations if v.rule_id == "TOXICITY_GUARD"), None)
        if tox_v:
            assert tox_v.severity == RuleSeverity.CRITICAL


class TestLanguageConsistency:
    """Language mismatch should be flagged as a warning."""

    def test_english_response_to_german_ticket(self):
        long_english = (
            "Thank you for reaching out and contacting us about your issue. "
            "We can see that your account has a payment failure. Please try again "
            "with a different card and let us know if you have any other questions."
        )
        verdict = policy_engine.evaluate(
            long_english,
            context={"detected_language": "de"},
        )
        lang_flags = [
            v for v in verdict.warnings
            if v.rule_id == "LANGUAGE_CONSISTENCY"
        ]
        # Should flag as warning (not hard failure)
        assert lang_flags, "Long English response to German ticket should be flagged"
        assert lang_flags[0].severity == RuleSeverity.WARNING

    def test_english_ticket_english_response_no_flag(self):
        verdict = policy_engine.evaluate(
            "Please contact our billing team for a refund review.",
            context={"detected_language": "en"},
        )
        lang_flags = [v for v in verdict.warnings if v.rule_id == "LANGUAGE_CONSISTENCY"]
        assert not lang_flags


class TestScoring:
    """Score decreases proportionally with violations and warnings."""

    def test_clean_score_is_1(self):
        verdict = policy_engine.evaluate(
            "Our team will review your request and respond within our standard timeframe."
        )
        assert verdict.score >= 0.9

    def test_critical_violation_lowers_score(self):
        verdict = policy_engine.evaluate("I am not an AI — I am a human.")
        assert verdict.score <= 0.8

    def test_empty_response_fails(self):
        verdict = policy_engine.evaluate("")
        assert verdict.passed is False
        assert verdict.action == RemediationAction.BLOCK

    def test_has_critical_property(self):
        verdict = policy_engine.evaluate("I am not an AI.")
        assert verdict.has_critical is True

    def test_no_critical_when_clean(self):
        verdict = policy_engine.evaluate("Please hold while we review your account.")
        assert verdict.has_critical is False


class TestEngineCustomisation:
    """Rules can be added and removed at runtime."""

    def test_add_custom_rule(self):
        engine = ConstitutionalPolicyEngine()

        def check_all_caps(text, ctx):
            if text == text.upper() and len(text) > 20:
                return RuleViolation(
                    rule_id="NO_SHOUTING",
                    rule_name="No All-Caps Responses",
                    severity=RuleSeverity.WARNING,
                    action=RemediationAction.WARN,
                    evidence=text[:50],
                    explanation="Response is written in all caps.",
                )
            return None

        engine.add_rule(ConstitutionalRule(
            id="NO_SHOUTING",
            name="No All-Caps Responses",
            description="Do not respond in all caps.",
            severity=RuleSeverity.WARNING,
            action=RemediationAction.WARN,
            check_fn=check_all_caps,
        ))

        verdict = engine.evaluate("PLEASE CONTACT OUR TEAM FOR ASSISTANCE WITH YOUR ACCOUNT.")
        shouting_flags = [v for v in verdict.warnings if v.rule_id == "NO_SHOUTING"]
        assert shouting_flags

    def test_remove_rule(self):
        engine = ConstitutionalPolicyEngine()
        removed = engine.remove_rule("COMPETITOR_NEUTRAL")
        assert removed is True
        # Rule no longer in constitution
        ids = [r.id for r in engine.constitution]
        assert "COMPETITOR_NEUTRAL" not in ids

    def test_remove_nonexistent_rule(self):
        engine = ConstitutionalPolicyEngine()
        removed = engine.remove_rule("NONEXISTENT_RULE")
        assert removed is False


# ─────────────────────────────────────────────────────────────────────────────
# Langfuse Tracer Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestLangfuseTracerNoOp:
    """When Langfuse is not configured, tracer must work as no-op."""

    def test_is_langfuse_configured_false_without_keys(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        assert _is_langfuse_configured() is False

    def test_trace_start_returns_valid_object_without_keys(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        trace = TriageTrace.start(
            ticket_id="test-123",
            tenant_id="acme",
            customer_id="cust-001",
            customer_tier="enterprise",
            channel="api",
        )
        assert trace is not None
        assert trace.ticket_id == "test-123"

    def test_agent_span_context_manager_no_exception(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        trace = TriageTrace.start(
            ticket_id="test-456", tenant_id="acme",
            customer_id="c1", customer_tier="free", channel="api",
        )
        with trace.agent_span("test_agent") as span:
            span.update(output="test output")
        # No exception = pass

    def test_score_methods_no_exception(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        trace = TriageTrace.start(
            ticket_id="test-789", tenant_id="acme",
            customer_id="c2", customer_tier="growth", channel="api",
        )
        trace.score_constitutional(0.85, comment="test")
        trace.score_resolution_quality(0.9)
        trace.score_rag_grounding(0.75)
        trace.finish(status="complete", total_cost_usd=0.001)
        # No exception = pass

    def test_record_generation_no_exception(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        trace = TriageTrace.start(
            ticket_id="gen-test", tenant_id="t1",
            customer_id="c3", customer_tier="vip", channel="api",
        )
        from src.monitoring.langfuse_tracer import _NoOpSpan
        trace.record_generation(
            span=_NoOpSpan(),
            model="gemma3:4b",
            prompt_messages=[{"role": "user", "content": "test"}],
            completion="test response",
            prompt_tokens=100,
            completion_tokens=50,
            latency_ms=1200,
            cost_usd=0.0,
        )
        # No exception = pass
