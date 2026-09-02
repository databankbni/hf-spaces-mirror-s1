"""Async multi-pass RICS report validation orchestrator (judge-editor loop).

Processes mapped section drafts through an Auditor LLM pass and optional Repair LLM
pass until stabilized or circuit-broken back to the immutable baseline paragraph.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from backend.config import settings
from backend.llm import openai_client
from backend.models.validation_loop import (
    MAX_VALIDATION_ITERATIONS,
    AuditorPayload,
    AuditorViolation,
    SectionValidationInput,
    SectionValidationResult,
    ValidationFailureMetadata,
)
from backend.observability import tracing as observability
from backend.pipeline.composition_output import sanitize_section_prose
from backend.pipeline.paragraph_merge import _content_tokens
from backend.prompts.grounding_prompt import build_grounding_messages
from backend.prompts.repair_prompt import build_repair_messages

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex pre-filters (deterministic edge-guard)
# ---------------------------------------------------------------------------

_LEAKAGE_PATTERN_SPECS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("XXX", re.compile(r"\bXXX\b")),
    ("TBC", re.compile(r"\bTBC\b", re.IGNORECASE)),
    ("TBD", re.compile(r"\bTBD\b", re.IGNORECASE)),
    ("[REDACTED]", re.compile(r"\[REDACTED\]", re.IGNORECASE)),
    ("{placeholder}", re.compile(r"\{[^{}]+\}")),
    ("[UNMATCHED_OBSERVATION", re.compile(r"\[UNMATCHED_OBSERVATION:", re.IGNORECASE)),
    ("[Source:", re.compile(r"\[Source:", re.IGNORECASE)),
    ("[Grounding review", re.compile(r"\[Grounding\s+review", re.IGNORECASE)),
    ("???", re.compile(r"\?\?\?")),
    ("___", re.compile(r"_{3,}")),
)


def detect_leakage_tokens(text: str) -> list[str]:
    """Return deduplicated leakage token labels found in *text*."""
    if not (text or "").strip():
        return []
    found: list[str] = []
    seen: set[str] = set()
    for label, pattern in _LEAKAGE_PATTERN_SPECS:
        if pattern.search(text) and label not in seen:
            seen.add(label)
            found.append(label)
    return found


def has_leakage(text: str) -> bool:
    """True when deterministic edge-guard detects forbidden leakage tokens."""
    return bool(detect_leakage_tokens(text))


# ---------------------------------------------------------------------------
# Violation severity (convergence gate)
# ---------------------------------------------------------------------------

# Cosmetic/register faults that must NOT block stabilisation. They do not assert
# a false property-specific fact, so a section whose only remaining objections
# are these is grounded and may ship. Blocking on them was the dominant cause of
# the production circuit-breaker storm (judge re-raised fresh style nits each
# pass and the loop never converged). They are still surfaced for repair when a
# repair pass runs for other reasons.
_SOFT_VIOLATION_TYPES = frozenset(
    {
        "non_british_english",
        "unsupported_monitoring",
        # Surveyor rating metadata (note.rating_value) is not an LLM invention or a
        # foreign property fact. The adversarial auditor flags legacy rating labels as
        # stale, but they carry no content tokens for
        # the note-shield to protect and the repair pass cannot delete a structurally
        # required line — so as a must-fix it burned every iteration and quarantined
        # the majority of sections (the production circuit-breaker storm). It now
        # ships for surveyor review instead of blocking stabilisation.
        "stale_condition_rating",
    }
)


def _split_violations(
    violations: list[AuditorViolation],
    relaxed_types: frozenset[str] = frozenset(),
) -> tuple[list[AuditorViolation], list[AuditorViolation]]:
    """Partition into (must_fix, soft). Must-fix = any ungrounded property fact.

    ``relaxed_types`` (Expert-mode preference policy) demotes the matching
    violation types to soft for this section. Identity-fact types can never be
    relaxed — they are subtracted here regardless of what the caller passed,
    so a mis-configured policy cannot open the invention gate.
    """
    from backend.domain.interference import HARD_VIOLATION_TYPES

    effective_relaxed = frozenset(t.strip().lower() for t in relaxed_types) - (
        HARD_VIOLATION_TYPES
    )
    must_fix: list[AuditorViolation] = []
    soft: list[AuditorViolation] = []
    for v in violations:
        vtype = (v.violation_type or "").strip().lower()
        is_soft = vtype in _SOFT_VIOLATION_TYPES or vtype in effective_relaxed
        (soft if is_soft else must_fix).append(v)
    return must_fix, soft


def _violation_substantiated_by_notes(
    violation: AuditorViolation, observations: list[str]
) -> bool:
    """True when the auditor flagged text that the surveyor's notes actually support.

    Matches the flagged phrase against EACH note individually rather than the pooled
    note union. The old union-based ratio was size-dependent: on a section with many
    notes, a single genuinely-grounded fact (e.g. an asbestos hazard among a dozen
    other findings) covered far less than 45% of the union and was wrongly amputated
    as ``invented_*`` by the repair pass — the root cause of dropped facts. A claim is
    substantiated when, for any one note, that note is largely about the claim (note
    covered by the phrase) OR the claim's specifics are largely present in that note
    (phrase covered by the note). Per-note matching makes recall independent of how
    many notes the section carries.
    """
    offending = (violation.offending_text or "").strip()
    if not offending or not observations:
        return False
    off_tokens = _content_tokens(offending)
    if not off_tokens:
        return False
    for obs in observations:
        note_tokens = _content_tokens(obs)
        if not note_tokens:
            continue
        overlap = note_tokens & off_tokens
        if len(overlap) < 2:
            continue
        if (
            len(overlap) / len(note_tokens) >= 0.45
            or len(overlap) / len(off_tokens) >= 0.6
        ):
            return True
    return False


def _filter_note_substantiated_violations(
    violations: list[AuditorViolation], observations: list[str]
) -> list[AuditorViolation]:
    """Drop auditor flags the repair pass would wrongly amputate."""
    if not violations:
        return []
    filtered = [
        v for v in violations if not _violation_substantiated_by_notes(v, observations)
    ]
    dropped = len(violations) - len(filtered)
    if dropped:
        logger.info(
            "Validation shielded %d note-substantiated violation(s) from repair",
            dropped,
        )
    return filtered


def _summarize_violations(violations: list[AuditorViolation]) -> str:
    """Compact ``type xN`` summary (most frequent first) for log diagnostics."""
    if not violations:
        return "none"
    counts: dict[str, int] = {}
    for v in violations:
        vtype = (v.violation_type or "unknown").strip().lower() or "unknown"
        counts[vtype] = counts.get(vtype, 0) + 1
    return ", ".join(
        f"{vtype} x{n}"
        for vtype, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    )


@dataclass
class _Candidate:
    """An audited draft state, ranked for best-of-loop selection."""

    text: str
    iteration: int
    must_fix: list[AuditorViolation]
    soft: list[AuditorViolation]
    leakage: list[str]

    @property
    def is_grounded(self) -> bool:
        """No ungrounded property facts and no placeholder leakage (style may remain)."""
        return not self.must_fix and not self.leakage

    @property
    def rank(self) -> tuple[int, int, int]:
        """Lower is better: fewest must-fix, then leakage, then soft faults."""
        return (len(self.must_fix), len(self.leakage), len(self.soft))


# ---------------------------------------------------------------------------
# LLM adapters (async wrappers over sync OpenAI client)
# ---------------------------------------------------------------------------

# Auditors may optionally accept ``prior_violations`` (keyword) for re-audit
# anchoring; the loop introspects the signature and only passes it when supported,
# so legacy 2-arg auditors (and test doubles) keep working unchanged.
AuditorCallable = Callable[..., Awaitable[AuditorPayload | None]]
RepairCallable = Callable[
    [SectionValidationInput, str, AuditorPayload], Awaitable[str | None]
]


def _auditor_accepts_prior(fn: AuditorCallable) -> bool:
    """True when *fn* accepts a ``prior_violations`` keyword (or **kwargs)."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return "prior_violations" in params or any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
    )


def _parse_auditor_payload(raw: dict[str, Any]) -> AuditorPayload | None:
    """Parse and validate auditor JSON; return None on contract/serialization failure."""
    try:
        violations_raw = raw.get("violations") or []
        violations: list[dict[str, str]] = []
        for item in violations_raw:
            if isinstance(item, dict):
                violations.append(
                    {
                        "violation_type": str(item.get("violation_type") or ""),
                        "offending_text": str(item.get("offending_text") or ""),
                        "reason": str(item.get("reason") or ""),
                    }
                )
            elif str(item).strip():
                violations.append(
                    {
                        "violation_type": "invented_defect",
                        "offending_text": str(item),
                        "reason": "Legacy ungrounded entry.",
                    }
                )

        payload = AuditorPayload(
            passed=bool(raw.get("passed", not violations)),
            audit_summary=str(
                raw.get("_audit_summary") or raw.get("audit_summary") or ""
            ),
            violations=violations,
            cleaned_text=str(raw.get("cleaned_text") or ""),
        )
        return payload
    except (ValidationError, TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Auditor payload validation failed: %s", exc)
        return None


def _deterministic_auditor_payload(draft_text: str) -> AuditorPayload:
    """Local, network-free grounding fallback.

    Used both when no LLM is configured and when the auditor LLM call fails for
    infrastructure reasons (auth/network/timeout). An infrastructure failure must
    not be conflated with a genuine grounding failure — otherwise a flaky or
    rate-limited LLM would downgrade every section to manual review and produce an
    unpresentable report. The deterministic merge that produced ``draft_text`` is
    already baseline-grounded, so we only block on hard leakage tokens.
    """
    cleaned = sanitize_section_prose(draft_text)
    leakage = detect_leakage_tokens(cleaned)
    return AuditorPayload(passed=not leakage, violations=[], cleaned_text=cleaned)


async def default_auditor_call(
    section: SectionValidationInput,
    draft_text: str,
    *,
    prior_violations: list[AuditorViolation] | None = None,
) -> AuditorPayload | None:
    """Run the grounding auditor LLM pass in a worker thread.

    ``prior_violations`` (2nd+ iteration) anchors the re-audit so the judge
    confirms earlier faults are fixed instead of raising fresh stylistic nits.
    """
    if not openai_client.is_available():
        return _deterministic_auditor_payload(draft_text)

    prior_payload = (
        [v.model_dump() for v in prior_violations] if prior_violations else None
    )
    messages = build_grounding_messages(
        draft_text,
        section.observations,
        section.template_paragraphs or None,
        baseline_paragraph=section.baseline_paragraph,
        prior_violations=prior_payload,
    )

    try:
        raw = await openai_client.chat_json_async(
            messages,
            model=settings.grounding_model,
            max_tokens=settings.max_tokens_grounding,
            temperature=float(settings.grounding_temperature),
            timeout=settings.validation_call_timeout_seconds,
            call_label="auditor",
            reasoning_effort=settings.grounding_reasoning_effort,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Auditor LLM unavailable for section %s (%s); using deterministic grounding fallback.",
            section.section_id,
            exc,
        )
        return _deterministic_auditor_payload(draft_text)

    if not isinstance(raw, dict):
        logger.warning(
            "Auditor LLM returned non-dict for section %s", section.section_id
        )
        return _deterministic_auditor_payload(draft_text)

    return _parse_auditor_payload(raw)


async def default_repair_call(
    section: SectionValidationInput,
    draft_text: str,
    audit_payload: AuditorPayload,
) -> str | None:
    """Run the repair-editor LLM pass in a worker thread."""
    if not openai_client.is_available():
        return sanitize_section_prose(draft_text) or None

    violations_payload = [v.model_dump() for v in audit_payload.violations]
    messages = build_repair_messages(
        mutated_paragraph=draft_text,
        observations=section.observations,
        violations=violations_payload,
    )

    try:
        repaired = await openai_client.chat_text_async(
            messages,
            model=settings.repair_model,
            max_tokens=settings.max_tokens_repair,
            temperature=float(settings.repair_temperature),
            timeout=settings.validation_call_timeout_seconds,
            call_label="repair",
            reasoning_effort=settings.repair_reasoning_effort,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Repair LLM network failure for section %s: %s",
            section.section_id,
            exc,
        )
        return None

    cleaned = sanitize_section_prose((repaired or "").strip())
    return cleaned or None


# ---------------------------------------------------------------------------
# Judge-editor state machine
# ---------------------------------------------------------------------------


def _rollback_result(
    section: SectionValidationInput,
    *,
    reason: str,
    iterations: int,
    last_error: str | None = None,
    leakage_tokens: list[str] | None = None,
    violations: list[AuditorViolation] | None = None,
    preserve_draft: bool = False,
    preserve_text: str | None = None,
) -> SectionValidationResult:
    """Circuit-breaker: restore baseline, or keep a mapped draft when requested.

    When ``preserve_draft`` is True the woven mapped prose is kept for surveyor
    review rather than silently reverting to an unwoven past-report paragraph.
    ``preserve_text`` (the best *audited* candidate from the loop) takes priority
    over the raw original draft so we never ship un-audited or worse-than-best
    prose, while still retaining note coverage for the human reviewer.
    """
    baseline = section.baseline_paragraph.strip()
    candidate = sanitize_section_prose((preserve_text or section.draft_text).strip())
    if preserve_draft and candidate and candidate != baseline:
        text = candidate
    else:
        text = baseline
    failure = ValidationFailureMetadata(
        section_id=section.section_id,
        reason=reason,
        iterations=iterations,
        last_error=last_error,
        leakage_tokens=leakage_tokens or [],
        violation_count=len(violations or []),
    )
    blocking = list(violations or [])
    logger.error(
        "Validation circuit breaker section=%s reason=%s iterations=%s "
        "must_fix=[%s] leakage=%s error=%s sample=%r",
        section.section_id,
        reason,
        iterations,
        _summarize_violations(blocking),
        leakage_tokens or [],
        last_error,
        (blocking[0].offending_text[:140] if blocking else ""),
    )
    return SectionValidationResult(
        section_id=section.section_id,
        status="ROLLED_BACK",
        text=text,
        iterations=iterations,
        leakage_tokens=leakage_tokens or [],
        failure=failure,
        final_violations=violations or [],
    )


def _stabilized_result(
    section: SectionValidationInput,
    text: str,
    *,
    iterations: int,
) -> SectionValidationResult:
    clean = sanitize_section_prose(text)
    return SectionValidationResult(
        section_id=section.section_id,
        status="STABILIZED",
        text=clean,
        iterations=iterations,
        leakage_tokens=[],
        failure=None,
        final_violations=[],
    )


async def stabilize_section(
    section: SectionValidationInput,
    *,
    max_iterations: int = MAX_VALIDATION_ITERATIONS,
    auditor: AuditorCallable | None = None,
    repair: RepairCallable | None = None,
) -> SectionValidationResult:
    """Run the judge-editor loop for a single section.

    Convergence policy:
      * Accept (STABILIZED) as soon as an *audited* candidate is grounded — no
        ungrounded property facts and no placeholder leakage. Cosmetic/register
        faults (British-English, defensive monitoring) are allowed to remain so
        the loop is not circuit-broken over style.
      * Re-audits are anchored with the prior must-fix register so the judge
        confirms fixes instead of raising fresh stylistic nits.
      * On exhaustion the best *audited* candidate (fewest must-fix → leakage →
        soft faults) is shipped for surveyor review — never un-audited prose and
        never a worse draft than one already seen.

    When ``GROUNDING_ENABLED`` is false, skip auditor/repair and accept the
    mapped draft (or baseline if the draft is empty).
    """
    baseline = section.baseline_paragraph.strip()
    draft = sanitize_section_prose(section.draft_text.strip() or baseline)

    if not settings.grounding_enabled:
        if not draft and not baseline:
            return _rollback_result(
                section,
                reason="missing_baseline_paragraph",
                iterations=0,
                last_error="baseline_paragraph is empty",
            )
        logger.info(
            "Grounding disabled — skipping auditor/repair for section %s",
            section.section_id,
        )
        return _stabilized_result(section, draft or baseline, iterations=0)

    auditor_fn = auditor or default_auditor_call
    repair_fn = repair or default_repair_call
    auditor_takes_prior = _auditor_accepts_prior(auditor_fn)

    if not baseline:
        return _rollback_result(
            section,
            reason="missing_baseline_paragraph",
            iterations=0,
            last_error="baseline_paragraph is empty",
        )

    current = draft
    best: _Candidate | None = None
    prior_must_fix: list[AuditorViolation] = []
    last_error: str | None = None

    for iteration in range(1, max_iterations + 1):
        try:
            with observability.span(
                "audit", section_id=section.section_id, iteration=iteration
            ):
                if auditor_takes_prior:
                    audit_payload = await auditor_fn(
                        section, current, prior_violations=prior_must_fix or None
                    )
                else:
                    audit_payload = await auditor_fn(section, current)
        except Exception as exc:  # noqa: BLE001
            last_error = f"auditor_exception:{exc}"
            return _rollback_result(
                section,
                reason="auditor_exception",
                iterations=iteration,
                last_error=last_error,
                leakage_tokens=best.leakage if best else [],
                violations=best.must_fix if best else [],
            )

        if audit_payload is None:
            return _rollback_result(
                section,
                reason="auditor_json_failure",
                iterations=iteration,
                last_error="auditor JSON parse/validation failed",
                leakage_tokens=best.leakage if best else [],
                violations=best.must_fix if best else [],
            )

        candidate_text = sanitize_section_prose(current)
        must_fix, soft = _split_violations(
            list(audit_payload.violations),
            frozenset(section.relaxed_violation_types or []),
        )
        must_fix = _filter_note_substantiated_violations(must_fix, section.observations)
        soft = _filter_note_substantiated_violations(soft, section.observations)
        leakage = detect_leakage_tokens(candidate_text)
        cand = _Candidate(
            text=candidate_text,
            iteration=iteration,
            must_fix=must_fix,
            soft=soft,
            leakage=leakage,
        )
        if best is None or cand.rank < best.rank:
            best = cand

        if cand.is_grounded:
            if soft:
                logger.info(
                    "Validation stabilized-with-soft section=%s iteration=%s soft=[%s]",
                    section.section_id,
                    iteration,
                    _summarize_violations(soft),
                )
            return _stabilized_result(section, candidate_text, iterations=iteration)

        # No value in repairing text we will not get to re-audit.
        if iteration == max_iterations:
            break

        prior_must_fix = must_fix
        repair_payload = audit_payload.model_copy(
            update={"violations": must_fix + soft, "passed": not (must_fix or soft)}
        )
        try:
            with observability.span(
                "repair", section_id=section.section_id, iteration=iteration
            ):
                repaired = await repair_fn(section, current, repair_payload)
        except Exception as exc:  # noqa: BLE001
            last_error = f"repair_exception:{exc}"
            return _rollback_result(
                section,
                reason="repair_exception",
                iterations=iteration,
                last_error=last_error,
                leakage_tokens=leakage,
                violations=must_fix,
            )

        if repaired is None:
            last_error = "repair_empty_response"
            current = candidate_text
            continue

        current = sanitize_section_prose(repaired)

    assert best is not None  # loop runs >=1 iteration; best is always set
    if best.is_grounded:
        return _stabilized_result(section, best.text, iterations=best.iteration)
    return _rollback_result(
        section,
        reason="loop_limit_exceeded",
        iterations=max_iterations,
        last_error=last_error or "failed_to_stabilize_within_iteration_budget",
        leakage_tokens=best.leakage,
        violations=best.must_fix,
        preserve_draft=True,
        preserve_text=best.text,
    )


# ---------------------------------------------------------------------------
# Concurrent batch runner
# ---------------------------------------------------------------------------


async def run_validation_batch(
    sections: list[SectionValidationInput],
    *,
    concurrency: int = 54,
    max_iterations: int = MAX_VALIDATION_ITERATIONS,
    auditor: AuditorCallable | None = None,
    repair: RepairCallable | None = None,
) -> list[SectionValidationResult]:
    """Validate all sections concurrently without blocking the event loop."""
    if not sections:
        return []

    limit = max(1, min(concurrency, len(sections)))
    semaphore = asyncio.Semaphore(limit)

    async def _run_one(item: SectionValidationInput) -> SectionValidationResult:
        async with semaphore:
            try:
                return await stabilize_section(
                    item,
                    max_iterations=max_iterations,
                    auditor=auditor,
                    repair=repair,
                )
            except Exception as exc:  # noqa: BLE001 — isolate section failures
                logger.exception(
                    "Unhandled validation failure for section %s",
                    item.section_id,
                )
                return _rollback_result(
                    item,
                    reason="unhandled_orchestrator_exception",
                    iterations=0,
                    last_error=str(exc),
                )

    return list(await asyncio.gather(*[_run_one(section) for section in sections]))


def run_validation_batch_sync(
    sections: list[SectionValidationInput],
    **kwargs: Any,
) -> list[SectionValidationResult]:
    """Synchronous entrypoint for scripts and non-async callers."""
    return asyncio.run(run_validation_batch(sections, **kwargs))
