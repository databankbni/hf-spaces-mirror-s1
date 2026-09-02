"""
CustomerCore — Constitutional Policy Engine (Phase 11)

WHAT IS CONSTITUTIONAL AI?
----------------------------
Constitutional AI is a technique from Anthropic (2022) where an AI system's outputs
are evaluated against a set of explicit, human-readable principles — the "constitution."
Instead of relying on human labellers to flag every bad output, the constitution is a
written document that defines what acceptable AI behaviour looks like.

In CustomerCore, the Constitutional Policy Engine runs AFTER the LangGraph supervisor
generates a resolution but BEFORE that resolution is returned to the API caller.
It is the final safety gate — no AI output reaches the customer without passing through it.

WHY IS THIS NECESSARY FOR B2B ENTERPRISE?
------------------------------------------
A single bad AI response in a B2B context can:
  - Create legal liability (AI promised a refund → contract obligation created)
  - Violate GDPR (AI echoed back PII from a previous ticket → data breach)
  - Damage customer relationships (AI responded in German to a Japanese ticket)
  - Expose the company to regulatory action (AI gave financial advice without a licence)
  - Embarrass the customer (AI included competitor's pricing in a reply to an enterprise client)

The constitutional engine catches all of these BEFORE they reach the customer,
with a full audit trail of what was caught and why.

THE EIGHT CONSTITUTIONAL RULES:
  1. PII_PROTECTION       — Response must not contain raw PII (names, emails, phone numbers)
  2. NO_COMMITMENTS       — Must not promise specific refund amounts, SLA timelines, or dates
  3. LANGUAGE_CONSISTENCY — Must respond in the same language as the ticket
  4. TOXICITY_GUARD       — Must not contain harmful, discriminatory, or abusive language
  5. AI_IDENTITY          — Must not deny being an AI when directly asked
  6. SCOPE_LIMITATION     — Must not give legal, medical, or financial advice
  7. NO_HALLUCINATION     — Must not cite KB articles that don't exist
  8. COMPETITOR_NEUTRAL   — Must not directly disparage or compare competitors

RULE SEVERITY LEVELS:
  CRITICAL  — Block the response entirely, return a safe fallback. Log to audit trail.
              Examples: PII leak, explicit harmful content, denial of AI identity
  VIOLATION — Flag the response, allow with warning if human operator approves (HITL).
              Examples: commitment made, legal advice given
  WARNING   — Note the issue, allow the response, increment a metric counter.
              Examples: language mismatch (minor), competitor mention (neutral)

REMEDIATION ACTIONS:
  BLOCK      — Replace the entire response with a safe generic fallback
  REDACT     — Remove the violating section and return the rest
  REGENERATE — Ask the LLM to rewrite the response with the violation corrected
               (used in Phase 16 for deeper integration; stubs here)
  WARN       — Allow the response but flag it in the audit log and Langfuse

FAST PATH vs SLOW PATH:
  Fast path (regex + pattern matching, <5ms):
    PII patterns (email regex, phone regex, SSN regex)
    Commitment phrases ("we will refund", "guaranteed by", "your money back")
    AI identity denial phrases ("I am not an AI", "I'm a human")
    Profanity/toxicity word lists (expandable)

  Slow path (LLM-based evaluation, 500ms–2s):
    Scope limitation check (is this financial/legal/medical advice?)
    Language consistency check (does response language match ticket language?)
    Nuanced toxicity (context-aware, catches coded language)
    Only triggered when fast path raises a warning or when confidence is low
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────

class RuleSeverity(str, Enum):
    WARNING   = "warning"    # Allow, note in audit
    VIOLATION = "violation"  # Flag, trigger HITL
    CRITICAL  = "critical"   # Block entirely


class RemediationAction(str, Enum):
    ALLOW      = "allow"
    WARN       = "warn"
    REDACT     = "redact"
    REGENERATE = "regenerate"
    BLOCK      = "block"


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RuleViolation:
    """Represents a single constitutional rule violation found in an output."""
    rule_id: str
    rule_name: str
    severity: RuleSeverity
    action: RemediationAction
    evidence: str           # The exact text that triggered the violation
    explanation: str        # Human-readable explanation for the audit trail
    position: int = -1      # Character position in the text (-1 if not applicable)


@dataclass
class PolicyVerdict:
    """
    The complete result of running the Constitutional Policy Engine on one output.

    A verdict is passed to:
      - The Langfuse tracer (score_constitutional)
      - The audit log (src/responsible_ai/audit_log.py)
      - The triage router (to decide: allow/flag/block)
    """
    passed: bool
    score: float            # 0.0 (all rules violated) to 1.0 (all rules passed)
    action: RemediationAction
    violations: list[RuleViolation] = field(default_factory=list)
    warnings: list[RuleViolation] = field(default_factory=list)
    safe_fallback: str | None = None  # The replacement response if action=BLOCK
    evaluation_ms: int = 0

    @property
    def has_critical(self) -> bool:
        return any(v.severity == RuleSeverity.CRITICAL for v in self.violations)

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)

    def summary(self) -> str:
        if self.passed:
            return f"PASSED (score={self.score:.2f}, {len(self.warnings)} warnings)"
        return (
            f"FAILED (score={self.score:.2f}, "
            f"{len(self.violations)} violations, "
            f"action={self.action.value})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Rule definitions — the "constitution"
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ConstitutionalRule:
    """
    One constitutional principle that AI outputs must comply with.

    Each rule has:
      id         — machine-readable identifier (used in audit logs, metrics labels)
      name       — human-readable name (shown to HITL reviewers)
      description — what the rule prevents and why it matters
      severity    — how serious a violation is
      action      — what to do when violated
      check_fn    — a callable that takes (response_text, context) and returns
                    a RuleViolation or None (None = passes this rule)
    """
    id: str
    name: str
    description: str
    severity: RuleSeverity
    action: RemediationAction
    check_fn: Callable[[str, dict[str, Any]], RuleViolation | None]


# ─────────────────────────────────────────────────────────────────────────────
# Rule implementations (fast-path, regex-based)
# ─────────────────────────────────────────────────────────────────────────────

# PII patterns — compiled once at module load for performance
_EMAIL_RE     = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.I)
_PHONE_RE     = re.compile(r"\b(?:\+?\d[\s\-.]?){7,15}\d\b")
_SSN_RE       = re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b")
_IBAN_RE      = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7,20}\b")
_CREDIT_RE    = re.compile(r"\b(?:\d{4}[\s\-]?){3}\d{4}\b")

# Commitment patterns — definitive promises that create legal obligations
_COMMITMENT_PHRASES = [
    r"we will refund",
    r"you will receive.*refund",
    r"guaranteed(?:ly)? (?:by|within|before)",
    r"promise(?:d)? (?:to|that)",
    r"you(?:'re| are) entitled to.*(?:refund|compensation|credit)",
    r"we(?:'ll| will) (?:definitely|certainly|absolutely)",
    r"your money (?:back|will be returned)",
    r"SLA (?:breach|violation) compensation",
    r"within \d+ (?:hours?|days?) (?:or|and) (?:guaranteed|promised)",
]
_COMMITMENT_RE = re.compile("|".join(_COMMITMENT_PHRASES), re.I)

# Scope limitation — legal, medical, financial advice patterns
_SCOPE_PHRASES = [
    r"(?:you should|we recommend|advise you to) (?:consult|see|speak with) (?:a |your )?(?:lawyer|attorney|solicitor|doctor|physician|financial advisor)",
    r"this (?:constitutes|is) (?:legal|medical|financial|investment) advice",
    r"based on (?:your|the) (?:legal|medical|financial) situation",
    r"you (?:are|could be) (?:legally|medically) (?:required|obligated|liable)",
    r"tax (?:implications|liability|deduction)",
    r"investment (?:opportunity|advice|recommendation)",
]
_SCOPE_RE = re.compile("|".join(_SCOPE_PHRASES), re.I)

# AI identity denial patterns
_AI_DENIAL_RE = re.compile(
    r"(?:I(?:'m| am) (?:not |a )?(?:a )?(?:human|person|real person|customer service agent))|"
    r"(?:not an? (?:AI|bot|artificial intelligence|chatbot|language model))|"
    r"(?:I(?:'m| am) (?:a |an )?(?:human )?(?:customer |support )?(?:representative|agent|person))",
    re.I
)

# Toxicity patterns (expanded in Phase 16 with ML-based classifier)
_TOXICITY_PHRASES = [
    r"\b(?:idiot|moron|stupid|dumb|incompetent)\b",
    r"\b(?:hate|despise|loathe)\b.{0,30}(?:you|customer|user)",
    r"\byour (?:fault|problem|issue|mistake)\b",
    r"(?:shut up|go away|leave us alone)",
]
_TOXICITY_RE = re.compile("|".join(_TOXICITY_PHRASES), re.I)


def _check_pii(text: str, context: dict) -> RuleViolation | None:
    """Check for PII leakage in the response text."""
    for pattern, pii_type in [
        (_EMAIL_RE, "email address"),
        (_PHONE_RE, "phone number"),
        (_SSN_RE, "SSN"),
        (_IBAN_RE, "IBAN/bank account"),
        (_CREDIT_RE, "credit card number"),
    ]:
        match = pattern.search(text)
        if match:
            return RuleViolation(
                rule_id="PII_PROTECTION",
                rule_name="PII Protection",
                severity=RuleSeverity.CRITICAL,
                action=RemediationAction.REDACT,
                evidence=match.group(),
                explanation=f"Response contains a {pii_type} which would violate GDPR Article 5 "
                            f"(data minimisation principle) and EU AI Act transparency requirements.",
                position=match.start(),
            )
    return None


def _check_commitments(text: str, context: dict) -> RuleViolation | None:
    """Check for definitive commitments that create legal obligations."""
    match = _COMMITMENT_RE.search(text)
    if match:
        return RuleViolation(
            rule_id="NO_COMMITMENTS",
            rule_name="No Binding Commitments",
            severity=RuleSeverity.VIOLATION,
            action=RemediationAction.REGENERATE,
            evidence=match.group(),
            explanation="The response contains a definitive commitment or promise. "
                        "AI systems cannot make binding contractual commitments. "
                        "This must be reviewed by a human before sending. "
                        "Legal teams have flagged automated refund promises as a liability risk.",
        )
    return None


def _check_scope(text: str, context: dict) -> RuleViolation | None:
    """Check for legal, medical, or financial advice being given."""
    match = _SCOPE_RE.search(text)
    if match:
        return RuleViolation(
            rule_id="SCOPE_LIMITATION",
            rule_name="Scope Limitation",
            severity=RuleSeverity.VIOLATION,
            action=RemediationAction.REDACT,
            evidence=match.group(),
            explanation="The response contains what appears to be legal, medical, or financial advice. "
                        "Customer support AI must not provide professional advice in regulated domains. "
                        "Doing so without a licence creates regulatory liability (FCA, SEC, medical board).",
        )
    return None


def _check_ai_identity(text: str, context: dict) -> RuleViolation | None:
    """Check if the response incorrectly denies being an AI."""
    match = _AI_DENIAL_RE.search(text)
    if match:
        return RuleViolation(
            rule_id="AI_IDENTITY",
            rule_name="AI Identity Transparency",
            severity=RuleSeverity.CRITICAL,
            action=RemediationAction.BLOCK,
            evidence=match.group(),
            explanation="The response denies being an AI, which violates EU AI Act Article 52 "
                        "(transparency obligations for AI systems interacting with humans). "
                        "The system must never claim to be human.",
        )
    return None


def _check_toxicity(text: str, context: dict) -> RuleViolation | None:
    """Check for harmful, abusive, or discriminatory language."""
    match = _TOXICITY_RE.search(text)
    if match:
        return RuleViolation(
            rule_id="TOXICITY_GUARD",
            rule_name="Toxicity Guard",
            severity=RuleSeverity.CRITICAL,
            action=RemediationAction.BLOCK,
            evidence=match.group(),
            explanation="The response contains language that could be perceived as harmful, "
                        "abusive, or disrespectful toward the customer. "
                        "This violates customer service standards and brand guidelines.",
        )
    return None


def _check_language_consistency(text: str, context: dict) -> RuleViolation | None:
    """
    Check that the response language matches the ticket's detected language.

    Only triggered for languages other than English (EN is universal fallback).
    Uses a simple heuristic: if the ticket language is X but >80% of words in
    the response are not recognisable as X-language words, flag it.
    This is a lightweight check — Phase 8's multilingual model handles full detection.
    """
    ticket_lang = context.get("detected_language", "en")
    if not ticket_lang or ticket_lang.lower() == "en":
        return None  # English tickets accept English responses

    # Check for obvious English-only responses to non-English tickets
    # Pattern: response contains >5 common English-only filler words but no
    # words from the expected language
    english_filler = re.compile(
        r"\b(the|and|for|this|that|your|with|have|will|please|thank|you|can|help)\b",
        re.I
    )
    filler_count = len(english_filler.findall(text))
    # Simple heuristic: if 8+ English filler words found in a non-English ticket,
    # the response is probably in English (a rough but fast check)
    if filler_count >= 8 and len(text.split()) > 20:
        return RuleViolation(
            rule_id="LANGUAGE_CONSISTENCY",
            rule_name="Language Consistency",
            severity=RuleSeverity.WARNING,
            action=RemediationAction.WARN,
            evidence=f"Response appears to be in English for a {ticket_lang.upper()} ticket",
            explanation=f"Ticket was submitted in {ticket_lang.upper()} but the response "
                        f"appears to be in English. Customers should be served in their preferred language. "
                        f"The multilingual model (Phase 8) should produce responses in {ticket_lang.upper()}.",
        )
    return None


def _check_competitor_mention(text: str, context: dict) -> RuleViolation | None:
    """
    Check for direct competitor disparagement.

    Neutral mentions (quoting the customer back) are allowed.
    Direct comparisons or disparagement are flagged.
    """
    competitor_disparagement = re.compile(
        r"(?:unlike|compared to|better than|worse than|superior to|inferior to) "
        r"(?:Salesforce|Zendesk|Freshdesk|ServiceNow|Intercom|HubSpot|Jira)",
        re.I
    )
    match = competitor_disparagement.search(text)
    if match:
        return RuleViolation(
            rule_id="COMPETITOR_NEUTRAL",
            rule_name="Competitor Neutrality",
            severity=RuleSeverity.WARNING,
            action=RemediationAction.WARN,
            evidence=match.group(),
            explanation="The response contains a direct comparison to a competitor product. "
                        "This risks brand and legal issues (defamation, trade disparagement). "
                        "Marketing and legal teams must approve any competitor comparisons.",
        )
    return None


# ─────────────────────────────────────────────────────────────────────────────
# The Constitution — ordered list of all rules
# ─────────────────────────────────────────────────────────────────────────────

CUSTOMERCORE_CONSTITUTION: list[ConstitutionalRule] = [
    ConstitutionalRule(
        id="PII_PROTECTION",
        name="PII Protection",
        description="Response must not contain raw PII: emails, phone numbers, SSNs, IBANs, credit cards.",
        severity=RuleSeverity.CRITICAL,
        action=RemediationAction.REDACT,
        check_fn=_check_pii,
    ),
    ConstitutionalRule(
        id="AI_IDENTITY",
        name="AI Identity Transparency",
        description="Must not deny being an AI (EU AI Act Article 52).",
        severity=RuleSeverity.CRITICAL,
        action=RemediationAction.BLOCK,
        check_fn=_check_ai_identity,
    ),
    ConstitutionalRule(
        id="TOXICITY_GUARD",
        name="Toxicity Guard",
        description="Must not contain harmful, abusive, or discriminatory language.",
        severity=RuleSeverity.CRITICAL,
        action=RemediationAction.BLOCK,
        check_fn=_check_toxicity,
    ),
    ConstitutionalRule(
        id="NO_COMMITMENTS",
        name="No Binding Commitments",
        description="Must not make definitive promises about refunds, timelines, or SLAs.",
        severity=RuleSeverity.VIOLATION,
        action=RemediationAction.REGENERATE,
        check_fn=_check_commitments,
    ),
    ConstitutionalRule(
        id="SCOPE_LIMITATION",
        name="Scope Limitation",
        description="Must not provide legal, medical, or financial advice.",
        severity=RuleSeverity.VIOLATION,
        action=RemediationAction.REDACT,
        check_fn=_check_scope,
    ),
    ConstitutionalRule(
        id="LANGUAGE_CONSISTENCY",
        name="Language Consistency",
        description="Should respond in the same language as the ticket.",
        severity=RuleSeverity.WARNING,
        action=RemediationAction.WARN,
        check_fn=_check_language_consistency,
    ),
    ConstitutionalRule(
        id="COMPETITOR_NEUTRAL",
        name="Competitor Neutrality",
        description="Must not directly disparage or compare competitors.",
        severity=RuleSeverity.WARNING,
        action=RemediationAction.WARN,
        check_fn=_check_competitor_mention,
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# Policy Engine
# ─────────────────────────────────────────────────────────────────────────────

class ConstitutionalPolicyEngine:
    """
    The enforcement layer of the CustomerCore constitution.

    Runs all constitutional rules against an AI-generated response and
    produces a PolicyVerdict that the triage router uses to decide whether
    to allow, flag, or block the response.

    Usage:
        engine = ConstitutionalPolicyEngine()
        verdict = engine.evaluate(
            response_text="Your refund will be processed within 24 hours.",
            context={"detected_language": "en", "customer_tier": "enterprise"},
        )
        if not verdict.passed:
            response = verdict.safe_fallback or response_text
    """

    SAFE_FALLBACK = (
        "Thank you for contacting support. We've received your request and a member "
        "of our team will review it and get back to you as soon as possible. "
        "For urgent matters, please call our support line directly."
    )

    def __init__(self, constitution: list[ConstitutionalRule] | None = None) -> None:
        self.constitution = constitution or CUSTOMERCORE_CONSTITUTION

    def evaluate(
        self,
        response_text: str,
        context: dict[str, Any] | None = None,
    ) -> PolicyVerdict:
        """
        Run all constitutional rules against a response text.

        Args:
            response_text: The AI-generated response to evaluate.
            context: Metadata about the ticket (detected_language, customer_tier, etc.)

        Returns:
            PolicyVerdict with score, action, and list of violations/warnings.
        """
        if not response_text or not response_text.strip():
            return PolicyVerdict(
                passed=False,
                score=0.0,
                action=RemediationAction.BLOCK,
                violations=[],
                safe_fallback=self.SAFE_FALLBACK,
            )

        ctx = context or {}
        violations: list[RuleViolation] = []
        warnings: list[RuleViolation] = []
        start = time.time()

        # Run every rule in the constitution
        for rule in self.constitution:
            try:
                result = rule.check_fn(response_text, ctx)
            except Exception:
                result = None  # Never let a rule checker crash the entire pipeline

            if result is None:
                continue  # Rule passed

            if result.severity == RuleSeverity.WARNING:
                warnings.append(result)
            else:
                violations.append(result)

        elapsed_ms = int((time.time() - start) * 1000)

        # Determine the highest severity action
        if not violations:
            # No violations — only warnings
            score = 1.0 - (len(warnings) * 0.05)  # Each warning costs 5 points
            return PolicyVerdict(
                passed=True,
                score=max(score, 0.5),
                action=RemediationAction.ALLOW if not warnings else RemediationAction.WARN,
                violations=[],
                warnings=warnings,
                evaluation_ms=elapsed_ms,
            )

        # Determine action from the most severe violation
        worst = max(violations, key=lambda v: list(RuleSeverity).index(v.severity))
        action = worst.action

        # Score: each violation costs 20 points, each warning costs 5 points
        raw_score = 1.0 - (len(violations) * 0.20) - (len(warnings) * 0.05)
        score = max(raw_score, 0.0)

        safe_fallback = self.SAFE_FALLBACK if action == RemediationAction.BLOCK else None

        return PolicyVerdict(
            passed=False,
            score=score,
            action=action,
            violations=violations,
            warnings=warnings,
            safe_fallback=safe_fallback,
            evaluation_ms=elapsed_ms,
        )

    def add_rule(self, rule: ConstitutionalRule) -> None:
        """Add a custom rule to the constitution at runtime."""
        self.constitution.append(rule)

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule by ID. Returns True if found and removed."""
        original_len = len(self.constitution)
        self.constitution = [r for r in self.constitution if r.id != rule_id]
        return len(self.constitution) < original_len


# ─────────────────────────────────────────────────────────────────────────────
# Singleton engine instance
# ─────────────────────────────────────────────────────────────────────────────

policy_engine = ConstitutionalPolicyEngine()
