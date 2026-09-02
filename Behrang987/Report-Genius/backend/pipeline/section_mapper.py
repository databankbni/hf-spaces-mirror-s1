"""Generation orchestrator.

Every schema section is generated from the most comprehensive REFERENCE-tier block
retrieved from uploaded past reports. Surveyor notes trigger in-place fact updates
on that baseline only — no scratch prose generation. All interference levels share
the same text-anchored adaptation path.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeAlias

from backend.config import settings
from backend.domain import template_discoverer
from backend.domain.atomic_observations import split_atomic_observations
from backend.domain.interference import GenerationPolicy
from backend.domain.notes.parser import UNASSIGNED, parse_notes_to_sections
from backend.domain.notes.survey_notes import build_property_context, parse_notes
from backend.domain.rics_level3_schema import (
    mapping_units_for_parent,
    ordered_parent_sections,
    valid_leaf_section_ids,
)
from backend.domain.section_scope import section_accepts_notes, storage_section_id
from backend.domain.source_attribution import format_reference_attribution
from backend.domain.specified_resolver import resolve_specified_tokens
from backend.llm import openai_client
from backend.llm.vision import vision_observations_for_section
from backend.models.report import GeneratedSection, ReportResult
from backend.models.schema import TemplateSchema
from backend.models.section import SectionNote
from backend.models.validation_loop import (
    SectionValidationInput,
    SectionValidationResult,
)
from backend.observability import tracing as observability
from backend.pii import scrubber as pii_scrubber
from backend.pipeline.composition_output import sanitize_section_prose
from backend.pipeline.condition_rating_filter import apply_condition_rating_policy
from backend.pipeline.paragraph_merge import (
    append_missing_observations,
    find_uncovered_notes,
    prepare_baseline_for_mapping,
)
from backend.pipeline.reference_mapper import map_reference_paragraph
from backend.pipeline.validation_orchestrator import (
    run_validation_batch,
    stabilize_section,
)
from backend.prompts.notes_expander_prompt import build_expander_messages
from backend.rag.reference_filter import build_reference_allowlist
from backend.rag.retriever import (
    InterferenceLevel,
    ReferenceSourceBaseline,
    RetrievalLevel,
    _uses_reference_tier,
    assemble_reference_baselines_per_source,
    fetch_complete_section_baselines_per_source,
    find_paragraph_by_topic,
    guess_report_section_from_topic,
    report_section_for_paragraph_id,
    retrieve_paragraphs_for_mapping,
    retrieve_past_report_baselines_hybrid,
)
from backend.pipeline.knowledge_source import resolve_knowledge_source
from backend.rag.types import (
    KNOWLEDGE_SOURCE_BOTH,
    KNOWLEDGE_SOURCE_PAST_REPORT,
    KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH,
    TIER_MASTER,
    TIER_REFERENCE,
    SearchHit,
)
from backend.standard_paragraphs.generate import generate_from_standard_paragraphs
from backend.storage import photo_store
from backend.storage.tenant_store import path_safe_section_id

logger = logging.getLogger(__name__)

SectionCompleteCallback: TypeAlias = Callable[
    [GeneratedSection], Awaitable[None] | None
]
DEFAULT_SECTION_CONCURRENCY = 54  # upper bound; runtime default comes from settings


def _default_section_concurrency() -> int:
    return max(1, int(getattr(settings, "section_concurrency", 4) or 4))

# Debug / intermediate dumps must use section IDs only (F2, M, D1) — never labels
# such as "Gas/Oil" or "service and terms of engagement", which break Windows paths.


def section_debug_filename(section_id: str, ext: str = "txt") -> str:
    """Filesystem-safe debug basename — canonical section ID, never the human label."""
    sid = path_safe_section_id(section_id)
    suffix = ext.lstrip(".") or "txt"
    return f"section_{sid}.{suffix}"


_UNMATCHED_TAG_RE = re.compile(
    r"\[UNMATCHED_OBSERVATION:\s*(.*?)\]",
    re.IGNORECASE | re.DOTALL,
)
_UNMATCHED_LINE_RE = re.compile(
    r"^\s*UNMATCHED_OBSERVATION:\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)

_NO_RAG_PLACEHOLDER = (
    "[No past-report paragraph found for this section. Manual entry required.]"
)

_UNMATCHED_SECTION_HEADING = "### UNMATCHED_OBSERVATION"

_PHOTO_LIMITATIONS_PREFIX = "Photo limitations:"


def _photo_limitation_observations(photo_note: str | None) -> list[str]:
    """Extract vision limitation sentences from the photo analysis user note."""
    if not photo_note or _PHOTO_LIMITATIONS_PREFIX not in photo_note:
        return []
    raw = photo_note.split(_PHOTO_LIMITATIONS_PREFIX, 1)[1].strip()
    if not raw:
        return []
    parts = [part.strip() for part in raw.split(". ") if part.strip()]
    if not parts:
        return [raw]
    return [part if part.endswith(".") else f"{part}." for part in parts]


def _baseline_passthrough_result(
    section_id: str,
    baseline_paragraph: str,
) -> SectionValidationResult:
    """Skip semantic audit when no new observations were mapped."""
    return SectionValidationResult(
        section_id=section_id,
        status="STABILIZED",
        text=baseline_paragraph.strip(),
        iterations=0,
    )


def _section_has_selected_photos(
    tenant_id: str,
    draft_id: str | None,
    section_id: str,
) -> bool:
    if not draft_id:
        return False
    rows = photo_store.list_section_photos(tenant_id, draft_id, section_id)
    return any(r.selected_for_ai for r in rows)


def collect_active_section_ids(
    schema: TemplateSchema,
    by_id: dict[str, SectionNote],
    *,
    tenant_id: str,
    report_draft_id: str | None,
    only_section_ids: list[str] | None,
) -> list[str]:
    """Ordered canonical leaf IDs with surveyor notes and/or AI-selected photos."""
    active: set[str] = set()
    for sid, note in by_id.items():
        if sid.upper() == UNASSIGNED:
            continue
        if note.raw_observations or (note.text or "").strip():
            active.add(sid.upper())

    if report_draft_id:
        for parent in ordered_parent_sections(schema):
            for sec in mapping_units_for_parent(schema, parent.id):
                if _section_has_selected_photos(tenant_id, report_draft_id, sec.id):
                    active.add(sec.id.upper())

    allowed: set[str] | None = None
    if only_section_ids is not None:
        allowed = {
            (x or "").strip().upper() for x in only_section_ids if (x or "").strip()
        }

    ordered: list[str] = []
    for parent in ordered_parent_sections(schema):
        for sec in mapping_units_for_parent(schema, parent.id):
            sid = sec.id.upper()
            if sid not in active:
                continue
            if allowed is not None and sid not in allowed:
                continue
            ordered.append(sec.id)
    return ordered


def estimate_active_sections_from_generate_body(
    body: object,
    *,
    tenant_id: str,
    draft_id: str | None,
) -> list[str]:
    """Active subsection IDs for progress tracking before generation starts."""
    by_sec = getattr(body, "bullets_by_section", None) or {}
    template_id = (getattr(body, "template_id", None) or "").strip()
    bullets = list(getattr(body, "bullets", None) or [])
    template_ids = list(getattr(body, "template_ids", None) or [])

    def _has_bullets(section_code: str) -> bool:
        items = by_sec.get(section_code) or by_sec.get(section_code.upper()) or []
        if items and any((i or "").strip() for i in items):
            return True
        return section_code == template_id and any((b or "").strip() for b in bullets)

    codes: set[str] = set()
    if by_sec:
        for code, items in by_sec.items():
            c = (code or "").strip().upper()
            if c and any((i or "").strip() for i in items):
                codes.add(c)
    elif bullets and template_id:
        codes.add(template_id.upper())

    for code in template_ids:
        c = (code or "").strip()
        if c and _has_bullets(c):
            codes.add(c.upper())

    scan = set(codes)
    for code in template_ids:
        c = (code or "").strip().upper()
        if c:
            scan.add(c)
    if template_id:
        scan.add(template_id.upper())

    if draft_id:
        for sid in scan:
            if _section_has_selected_photos(tenant_id, draft_id, sid):
                codes.add(sid.upper())

    if template_ids:
        ordered: list[str] = []
        seen: set[str] = set()
        for code in template_ids:
            c = (code or "").strip().upper()
            if c in codes and c not in seen:
                seen.add(c)
                ordered.append(c)
        ordered.extend(sorted(codes - seen))
        return ordered
    return sorted(codes)


@dataclass
class _MapOutcome:
    text: str
    hits: list[SearchHit]
    no_rag_match: bool
    unmatched_observations: list[str] | None = None
    baseline_paragraph: str = ""
    # Retrieval/prompt telemetry for the per-section manifest.
    prompt_messages: list[dict[str, str]] | None = None
    retrieved_count: int = 0
    prompt_chunk_count: int = 0
    retrieval_issues: list[str] = field(default_factory=list)
    llm_usage: dict | None = None
    style_sample_count: int = 0
    add_to_memory_hits: list[SearchHit] = field(default_factory=list)
    # Dual-path audit (past + SP) for manifests / UI run packs.
    dual_path_merged: bool = False
    dual_path_past_draft: str = ""
    dual_path_sp_draft: str = ""
    dual_path_past_hits: list[SearchHit] = field(default_factory=list)
    dual_path_sp_hits: list[SearchHit] = field(default_factory=list)
    dual_path_sp_findings: list[str] = field(default_factory=list)
    dual_path_sp_baseline: str = ""


@dataclass
class _PendingValidatedSection:
    """Mapped draft awaiting judge-editor validation before payload commit."""

    section: GeneratedSection
    baseline_paragraph: str
    draft_text: str
    observations: list[str]
    template_paragraphs: list[str] = field(default_factory=list)


@dataclass
class _SectionMappingResult:
    """Outcome of the synchronous map phase for one section."""

    section: GeneratedSection | None = None
    pending: _PendingValidatedSection | None = None
    unmatched: list[str] = field(default_factory=list)


def _expand_notes(
    schema: TemplateSchema,
    notes_text: str,
    *,
    interference_level: InterferenceLevel,
) -> str:
    if not settings.notes_expansion_enabled or not openai_client.is_available():
        return notes_text
    try:
        return (
            openai_client.chat_text(
                build_expander_messages(
                    schema,
                    notes_text,
                    interference_level=interference_level,
                ),
                model=settings.mapping_model,
                max_tokens=settings.max_tokens_mapping,
                call_label="notes_expander",
            )
            or notes_text
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Notes expansion failed (%s); using raw notes.", exc)
        return notes_text


def _observations_after_expand(
    raw_observations: list[str],
    notes_text: str,
    expanded_text: str,
) -> list[str]:
    if expanded_text.strip() != notes_text.strip():
        lines = [
            line.strip().lstrip("•-*·▸▹◆►").strip()
            for line in expanded_text.split("\n")
            if line.strip()
        ]
        return lines or raw_observations
    return raw_observations


def _reroute_unassigned_via_rag(
    tenant_id: str,
    schema: TemplateSchema,
    unassigned: SectionNote | None,
    by_id: dict[str, SectionNote],
    *,
    interference_level: InterferenceLevel,
    allowed_doc_keys: frozenset[str] | None = None,
) -> list[str]:
    """Match orphan note lines to REFERENCE paragraphs by topic (secondary gate).

    Notes bucketed as ``UNASSIGNED`` by anchor similarity in :mod:`notes_parser`
    may be promoted here when the top REFERENCE hit scores >=
    ``settings.confidence_threshold`` (0.72).
    """
    if unassigned is None or not unassigned.raw_observations:
        return []

    still_orphan: list[str] = []
    for block in unassigned.raw_observations:
        hits = find_paragraph_by_topic(
            tenant_id,
            [block],
            interference_level=interference_level,
            allowed_doc_keys=allowed_doc_keys,
            paragraph_section_id="",
        )
        if not hits or hits[0].score < settings.confidence_threshold:
            still_orphan.append(block)
            continue
        report_sid = report_section_for_paragraph_id(schema, hits[0].section_id)
        if report_sid is None:
            report_sid = guess_report_section_from_topic(schema, [block], hits[0].text)
        if report_sid is None or report_sid.upper() not in valid_leaf_section_ids():
            still_orphan.append(block)
            continue
        if not section_accepts_notes(report_sid):
            # Orphans may only be promoted into notes-bearing sections (D–I);
            # scaffold-only parents never receive rerouted observations.
            still_orphan.append(block)
            continue
        if report_sid in by_id:
            by_id[report_sid].raw_observations.append(block)
            by_id[report_sid].text = "\n".join(
                by_id[report_sid].raw_observations
            ).strip()
        else:
            by_id[report_sid] = SectionNote(
                section_id=report_sid,
                raw_observations=[block],
                text=block,
            )
    return still_orphan


def _map_section(
    schema: TemplateSchema,
    tenant_id: str,
    section_title: str,
    section_id: str,
    observations: list[str],
    rating_value: str | None,
    *,
    interference_level: InterferenceLevel,
    retrieval_level: RetrievalLevel = "paragraph",
    allowed_doc_keys: frozenset[str] | None = None,
    property_context: dict | None = None,
    policy: GenerationPolicy | None = None,
    knowledge_source: str = KNOWLEDGE_SOURCE_PAST_REPORT,
) -> _MapOutcome:
    alias_id = schema.paragraph_section_id(section_id)
    # Candidate leaf ids for both past-report and standard-paragraph retrieval.
    candidate_ids = [section_id]
    stored_id = storage_section_id(section_id)
    if stored_id and stored_id != section_id:
        candidate_ids.append(stored_id)
    if alias_id and alias_id != section_id:
        candidate_ids.append(alias_id)

    # ── Standard-paragraph generation path (dedicated prompt) ──────────────
    if (knowledge_source or "").strip().lower() == KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH:
        # Match dual-path Assist runners (e.g. run_dual_path_house_notes_merge.py):
        # always decompose notes into findings for per-issue SP retrieve.
        text, hits, messages, guidance, issues, llm_usage, style_sample_count = (
            generate_from_standard_paragraphs(
                tenant_id=tenant_id,
                schema=schema,
                section_id=section_id,
                section_title=section_title,
                observations=observations,
                candidate_ids=candidate_ids,
                rating_value=rating_value,
                allowed_doc_keys=allowed_doc_keys,
                force_decompose=True,
                force_decompose_llm=True,
            )
        )
        if not text.strip():
            return _MapOutcome(text=_NO_RAG_PLACEHOLDER, hits=[], no_rag_match=True)
        # Findings-only write (no strong SP matches) is still a successful SP map.
        return _MapOutcome(
            text=text,
            hits=hits,
            no_rag_match=False,
            # Manifest baseline = retrieved catalogue SPs (not the LLM rewrite).
            baseline_paragraph=guidance or text,
            retrieved_count=len(hits),
            prompt_chunk_count=len(hits),
            prompt_messages=messages,
            retrieval_issues=list(issues or []),
            llm_usage=llm_usage,
            style_sample_count=int(style_sample_count or 0),
        )

    # ── Past-report mapping path (existing behaviour) ──────────────────────
    # The section_alias_map redirects report codes to the standard-paragraph
    # codes (e.g. firm bundle uses E-codes where canonical uses D-codes). An uploaded
    # past report may be authored with EITHER numbering, so for the reference tier we
    # try the canonical report code first and fall back to the alias. Applying only
    # the alias misroutes correctly-tagged references (e.g. D2 Roof -> E2 Walls).
    # Parents A/B/C/K/L/M/N have no real leaf codes in live reports, so their
    # PARENT-level storage id is also tried (new ingest stores them parent-level).
    if _uses_reference_tier(interference_level):
        pass  # candidate_ids already built above
    else:
        candidate_ids = [alias_id]
    query_obs = observations or [section_title]

    tier = TIER_REFERENCE if _uses_reference_tier(interference_level) else TIER_MASTER
    paragraph_id = candidate_ids[0]
    hits: list[SearchHit] = []
    baseline_text, baseline_hits = "", []
    # Each past report that holds this subsection is kept as its OWN block here and
    # fed to the prompt separately — never merged into a single baseline.
    source_blocks: list[ReferenceSourceBaseline] = []

    def _metadata_first() -> bool:
        """Exact-subsection fetch from the user's own docs; True when found."""
        nonlocal paragraph_id, hits, baseline_text, baseline_hits, source_blocks
        for cid in candidate_ids:
            blocks = fetch_complete_section_baselines_per_source(
                tenant_id,
                paragraph_section_id=cid,
                tier=tier,
                allowed_doc_keys=allowed_doc_keys,
                property_context=property_context,
            )
            if blocks:
                paragraph_id = cid
                source_blocks = blocks
                hits = [h for b in blocks for h in b.hits]
                baseline_hits = list(hits)
                baseline_text = "\n\n".join(b.text for b in blocks)
                return True
        return False

    # Past reports (REFERENCE): always section∩property_type hybrid similarity
    # (dense + BM25, same Approach B as standard paragraphs), then expand the
    # top-K sources to complete subsection scaffolds. Metadata dump is only a
    # last-resort fallback when hybrid returns nothing.
    if _uses_reference_tier(interference_level):
        for cid in candidate_ids:
            cand_blocks, cand_hits = retrieve_past_report_baselines_hybrid(
                tenant_id,
                section_label=section_title,
                paragraph_section_id=cid,
                observations=query_obs,
                tier=tier,
                allowed_doc_keys=allowed_doc_keys,
                property_context=property_context,
            )
            if cand_blocks:
                paragraph_id = cid
                hits = cand_hits
                source_blocks = cand_blocks
                baseline_hits = [h for b in cand_blocks for h in b.hits]
                baseline_text = "\n\n".join(b.text for b in cand_blocks)
                break
        if not hits or not baseline_text.strip():
            _metadata_first()
    else:
        # MASTER / non-reference: keep legacy metadata-first then similarity.
        if settings.metadata_first_retrieval_enabled:
            _metadata_first()

        if not hits or not baseline_text.strip():
            for cid in candidate_ids:
                cand_hits = retrieve_paragraphs_for_mapping(
                    tenant_id,
                    section_label=section_title,
                    paragraph_section_id=cid,
                    observations=query_obs,
                    interference_level=interference_level,
                    retrieval_level=retrieval_level,
                    allowed_doc_keys=allowed_doc_keys,
                    property_context=property_context,
                )
                if not cand_hits:
                    continue
                cand_blocks = assemble_reference_baselines_per_source(
                    cand_hits,
                    paragraph_section_id=cid,
                    tenant_id=tenant_id,
                    tier=tier,
                    allowed_doc_keys=allowed_doc_keys,
                    property_context=property_context,
                )
                if cand_blocks:
                    paragraph_id = cid
                    hits = cand_hits
                    source_blocks = cand_blocks
                    baseline_hits = [h for b in cand_blocks for h in b.hits]
                    baseline_text = "\n\n".join(b.text for b in cand_blocks)
                    break

        if (not hits or not baseline_text.strip()) and (
            not settings.metadata_first_retrieval_enabled
        ):
            _metadata_first()

    if not hits or not baseline_text.strip():
        return _MapOutcome(text=_NO_RAG_PLACEHOLDER, hits=[], no_rag_match=True)

    # Similarity retrieve is the only pre-LLM filter: pass retrieved past-report
    # blocks + surveyor notes straight to the mapping prompt (no match gate, no
    # deterministic foreign-fact strip). Prompt + optional grounding audit own fidelity.
    reference_blocks = [
        block.text.strip() for block in source_blocks if (block.text or "").strip()
    ]
    if not reference_blocks:
        return _MapOutcome(text=_NO_RAG_PLACEHOLDER, hits=[], no_rag_match=True)
    baseline_for_prompt = "\n\n".join(reference_blocks)

    # Add-to-Memory: section-scoped similarity vs notes (separate from past scaffolds).
    add_to_memory_hits: list[SearchHit] = []
    try:
        from backend.standard_paragraphs.service import (
            retrieve_add_to_memory_for_notes,
        )

        add_to_memory_hits = list(
            retrieve_add_to_memory_for_notes(
                tenant_id,
                paragraph_id or section_id,
                observations,
                section_label=section_title,
                candidate_ids=candidate_ids,
            )
            or []
        )
    except Exception:  # noqa: BLE001 — memory retrieve must not abort mapping
        logger.warning(
            "add_to_memory_retrieve_failed section=%s",
            section_id,
            exc_info=True,
        )
        add_to_memory_hits = []
    memory_blocks = [
        (h.text or "").strip() for h in add_to_memory_hits if (h.text or "").strip()
    ]

    captured: list[dict[str, str]] = []
    with observability.span(
        "map", section_id=section_id, observations=len(observations or [])
    ):
        mapped, llm_usage = map_reference_paragraph(
            baseline_for_prompt,
            observations,
            schema,
            interference_level,
            section_id=section_id,
            section_title=section_title,
            rating_value=rating_value,
            reference_blocks=reference_blocks,
            add_to_memory_blocks=memory_blocks or None,
            mode=policy.mode if policy else None,
            preferences=policy.preferences if policy else None,
            tenant_id=tenant_id,
            capture_messages=captured,
        )
    text = append_missing_observations(mapped or baseline_for_prompt, observations)

    return _MapOutcome(
        text=text,
        hits=baseline_hits or hits[:1],
        no_rag_match=False,
        unmatched_observations=[],
        baseline_paragraph=baseline_for_prompt,
        prompt_messages=captured or None,
        retrieved_count=len(hits),
        prompt_chunk_count=len(baseline_hits) if captured else 0,
        llm_usage=llm_usage,
        add_to_memory_hits=add_to_memory_hits,
    )


def _format_unmatched_section_block(unmatched: list[str]) -> str:
    """Append structured unmatched block for template-schema export."""
    items = [u.strip() for u in unmatched if u.strip()]
    if not items:
        return ""
    bullets = "\n".join(f"* {item}" for item in items)
    return f"\n\n{_UNMATCHED_SECTION_HEADING}\n{bullets}"


def _extract_unmatched(mapped: str) -> tuple[str, list[str]]:
    tag_matches = [m.strip() for m in _UNMATCHED_TAG_RE.findall(mapped)]
    line_matches = [m.strip() for m in _UNMATCHED_LINE_RE.findall(mapped)]
    unmatched = tag_matches + line_matches
    cleaned = _UNMATCHED_TAG_RE.sub("", mapped)
    cleaned = _UNMATCHED_LINE_RE.sub("", cleaned).strip()
    return cleaned, unmatched


def _run_coroutine_sync(coro):
    """Execute an async coroutine from sync callers (tests, threadpool workers)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Nested inside a running loop (e.g. async test harness): isolate with a fresh loop.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _quarantine_safe_text(baseline: str, observations: list[str]) -> str:
    """Deterministic, contamination-free fallback when grounding fails to converge.

    Never ships the LLM's failed last attempt (which the auditor flagged) or a raw
    foreign baseline. Applies the legacy reducer chain
    (``prepare_baseline_for_mapping``) then appends uncovered notes so quarantined
    text is contamination-trimmed and complete on the surveyor's facts. The live
    map path no longer strips before the LLM — this is grounding-failure only.
    """
    safe = prepare_baseline_for_mapping(baseline or "", observations or [])
    return append_missing_observations(safe, observations or [])


def _apply_validation_outcome(
    item: _PendingValidatedSection,
    outcome: SectionValidationResult | None,
) -> None:
    """Commit stabilized prose, or quarantine to a safe reconstruction on failure."""
    if outcome is None:
        logger.error(
            "validation_batch_missing_result section=%s — quarantining to safe baseline",
            item.section.section_id,
        )
        item.section.text = _quarantine_safe_text(
            item.baseline_paragraph, item.observations or []
        )
        item.section.status = "GROUNDING_REVIEW"
        item.section.grounding_passed = False
        observability.record_quarantine(item.section.section_id)
        return

    if outcome.final_violations:
        observability.record_violations(
            item.section.section_id,
            [v.violation_type for v in outcome.final_violations],
        )

    if outcome.status == "STABILIZED":
        item.section.text = append_missing_observations(
            outcome.text, item.observations or []
        )
        item.section.status = "OK"
        item.section.grounding_passed = True
    else:
        # Grounding did not converge: gate the failed LLM attempt and ship the
        # deterministic safe reconstruction instead of silently shipping unverified
        # (potentially contaminated) prose.
        item.section.text = _quarantine_safe_text(
            item.baseline_paragraph, item.observations or []
        )
        item.section.status = "GROUNDING_REVIEW"
        item.section.grounding_passed = False
        observability.record_quarantine(item.section.section_id)
        if outcome.failure:
            logger.warning(
                "validation_circuit_breaker section=%s reason=%s iterations=%s "
                "— quarantined to safe reconstruction",
                item.section.section_id,
                outcome.failure.reason,
                outcome.iterations,
            )


async def _invoke_section_complete(
    callback: SectionCompleteCallback | None,
    section: GeneratedSection,
) -> None:
    if callback is None:
        return
    try:
        maybe_awaitable = callback(section)
        if asyncio.iscoroutine(maybe_awaitable):
            await maybe_awaitable
    except Exception:  # noqa: BLE001 — callback must not abort sibling sections
        logger.exception(
            "on_section_complete failed section=%s",
            section.section_id,
        )


def _usable_map_text(outcome: _MapOutcome) -> str:
    """Return mapped prose, or empty when the path produced no usable draft."""
    text = (outcome.text or "").strip()
    if (
        not text
        or outcome.no_rag_match
        or text == _NO_RAG_PLACEHOLDER.strip()
        or text == _NO_RAG_PLACEHOLDER
    ):
        return ""
    return text


def _stamp_dual_path_audit(
    outcome: _MapOutcome,
    *,
    past_outcome: _MapOutcome,
    sp_outcome: _MapOutcome,
    past_text: str,
    sp_text: str,
    merged: bool,
) -> _MapOutcome:
    """Attach past/SP drafts + hits for manifests and UI generate-run packs."""
    outcome.dual_path_merged = merged
    outcome.dual_path_past_draft = past_text
    outcome.dual_path_sp_draft = sp_text
    outcome.dual_path_past_hits = list(past_outcome.hits or [])
    outcome.dual_path_sp_hits = list(sp_outcome.hits or [])
    outcome.dual_path_sp_findings = [
        i for i in (sp_outcome.retrieval_issues or []) if str(i).strip()
    ]
    outcome.dual_path_sp_baseline = (sp_outcome.baseline_paragraph or "").strip()
    return outcome


def _combine_dual_path_outcomes(
    *,
    section_id: str,
    section_title: str,
    observations: list[str],
    past_outcome: _MapOutcome,
    sp_outcome: _MapOutcome,
) -> _MapOutcome:
    """Merge past + SP drafts when both exist; otherwise keep the survivor."""
    past_text = _usable_map_text(past_outcome)
    sp_text = _usable_map_text(sp_outcome)
    notes_blob = "\n".join(o for o in observations if (o or "").strip())
    merged_flag = False

    if past_text and sp_text and settings.dual_path_merge_enabled:
        from backend.merge_agent import DualPathDraft, merge_dual_path_drafts

        merged = merge_dual_path_drafts(
            DualPathDraft(
                section_id=section_id,
                section_title=section_title,
                past_report_draft=past_text,
                standard_paragraph_draft=sp_text,
                inspection_notes=notes_blob,
            )
        )
        final = (merged.merged_text or "").strip() or past_text
        hits = list(past_outcome.hits or []) or list(sp_outcome.hits or [])
        usage = merged.llm_usage or past_outcome.llm_usage or sp_outcome.llm_usage
        merged_flag = True
        outcome = _MapOutcome(
            text=final,
            hits=hits,
            no_rag_match=False,
            unmatched_observations=list(past_outcome.unmatched_observations or [])
            or list(sp_outcome.unmatched_observations or []),
            baseline_paragraph=(
                past_outcome.baseline_paragraph or sp_outcome.baseline_paragraph
            ),
            prompt_messages=past_outcome.prompt_messages or sp_outcome.prompt_messages,
            retrieved_count=max(
                past_outcome.retrieved_count, sp_outcome.retrieved_count
            ),
            prompt_chunk_count=max(
                past_outcome.prompt_chunk_count, sp_outcome.prompt_chunk_count
            ),
            retrieval_issues=list(sp_outcome.retrieval_issues or []),
            llm_usage=usage,
            style_sample_count=max(
                past_outcome.style_sample_count, sp_outcome.style_sample_count
            ),
            add_to_memory_hits=list(past_outcome.add_to_memory_hits or []),
        )
    elif past_text:
        outcome = past_outcome
    elif sp_text:
        outcome = sp_outcome
    else:
        # Neither path produced prose — keep past outcome for NO_RAG / notes-only.
        outcome = past_outcome

    return _stamp_dual_path_audit(
        outcome,
        past_outcome=past_outcome,
        sp_outcome=sp_outcome,
        past_text=past_text,
        sp_text=sp_text,
        merged=merged_flag,
    )


def _prepare_section_mapping_sync(
    sec_id: str,
    *,
    schema: TemplateSchema,
    tenant_id: str,
    by_id: dict[str, SectionNote],
    id_to_unit: dict[str, object],
    report_draft_id: str | None,
    interference_level: InterferenceLevel,
    retrieval_level: RetrievalLevel,
    allowed_doc_keys: frozenset[str] | None,
    property_context: dict | None = None,
    policy: GenerationPolicy | None = None,
    knowledge_source: str = KNOWLEDGE_SOURCE_BOTH,
) -> _SectionMappingResult:
    """Blocking map phase for one section (safe to run in ``asyncio.to_thread``)."""
    _t_start = time.perf_counter()
    sec = id_to_unit[sec_id]
    note = by_id.get(sec.id)  # type: ignore[union-attr]
    observations: list[str] = []
    rating_value: str | None = None
    shorthand_expanded: str | None = None
    raw_observations: list[str] = []

    if note and note.text.strip():
        notes_text = _expand_notes(
            schema, note.text, interference_level=interference_level
        )
        if notes_text.strip() != note.text.strip():
            shorthand_expanded = notes_text
        observations = _observations_after_expand(
            note.raw_observations, note.text, notes_text
        )
        rating_value = note.rating_value
        raw_observations = list(note.raw_observations)

    photo_obs, photo_note = vision_observations_for_section(
        tenant_id, report_draft_id, sec.id, sec.title  # type: ignore[union-attr]
    )
    limitation_obs = _photo_limitation_observations(photo_note)
    combined_observations = [*observations, *photo_obs, *limitation_obs]

    map_kwargs = dict(
        interference_level=interference_level,
        retrieval_level=retrieval_level,
        allowed_doc_keys=allowed_doc_keys,
        property_context=property_context,
        policy=policy,
    )
    ks = (knowledge_source or KNOWLEDGE_SOURCE_PAST_REPORT).strip().lower()
    if ks == KNOWLEDGE_SOURCE_BOTH:
        past_outcome = _map_section(
            schema,
            tenant_id,
            sec.title,  # type: ignore[union-attr]
            sec.id,  # type: ignore[union-attr]
            combined_observations,
            rating_value,
            knowledge_source=KNOWLEDGE_SOURCE_PAST_REPORT,
            **map_kwargs,
        )
        sp_outcome = _map_section(
            schema,
            tenant_id,
            sec.title,  # type: ignore[union-attr]
            sec.id,  # type: ignore[union-attr]
            combined_observations,
            rating_value,
            knowledge_source=KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH,
            **map_kwargs,
        )
        outcome = _combine_dual_path_outcomes(
            section_id=sec.id,  # type: ignore[union-attr]
            section_title=sec.title,  # type: ignore[union-attr]
            observations=combined_observations,
            past_outcome=past_outcome,
            sp_outcome=sp_outcome,
        )
    else:
        outcome = _map_section(
            schema,
            tenant_id,
            sec.title,  # type: ignore[union-attr]
            sec.id,  # type: ignore[union-attr]
            combined_observations,
            rating_value,
            knowledge_source=ks,
            **map_kwargs,
        )

    if outcome.hits:
        top_conf = max((h.rerank_score or h.score or 0.0) for h in outcome.hits)
        observability.record_retrieval_confidence(sec.id, top_conf)  # type: ignore[union-attr]

    def _record_retrieval(*, status: str, generated_text: str) -> None:
        if not report_draft_id:
            return
        from backend.storage import retrieval_manifest

        elapsed_ms = round((time.perf_counter() - _t_start) * 1000.0, 2)
        dual_path = None
        if (
            outcome.dual_path_past_draft
            or outcome.dual_path_sp_draft
            or outcome.dual_path_past_hits
            or outcome.dual_path_sp_hits
        ):
            dual_path = {
                "merged": bool(outcome.dual_path_merged),
                "past_report_draft": outcome.dual_path_past_draft,
                "standard_paragraph_draft": outcome.dual_path_sp_draft,
                "sp_findings": list(outcome.dual_path_sp_findings or []),
                "sp_baseline_text": outcome.dual_path_sp_baseline,
                "past_report_hits": list(outcome.dual_path_past_hits or []),
                "standard_paragraph_hits": list(outcome.dual_path_sp_hits or []),
            }
        retrieval_manifest.record_section_retrieval(
            tenant_id,
            report_draft_id,
            section_id=sec.id,  # type: ignore[union-attr]
            section_title=sec.title,  # type: ignore[union-attr]
            observations=combined_observations,
            baseline_text=outcome.baseline_paragraph,
            hits=outcome.hits,
            status=status,
            prompt_messages=outcome.prompt_messages,
            retrieved_count=outcome.retrieved_count,
            prompt_chunk_count=outcome.prompt_chunk_count,
            elapsed_ms=elapsed_ms,
            knowledge_source=knowledge_source,
            generated_text=generated_text,
            retrieval_issues=list(outcome.retrieval_issues or []),
            llm_usage=outcome.llm_usage,
            style_sample_count=outcome.style_sample_count,
            add_to_memory_hits=list(outcome.add_to_memory_hits or []),
            dual_path=dual_path,
        )

    if outcome.no_rag_match:
        # Notes-first fallback: when no past-report baseline was retrieved but the
        # surveyor recorded findings for this section, author a clean paragraph
        # from those findings instead of leaving a dead tombstone. This only runs
        # on the otherwise-empty path, so it cannot affect sections that already
        # map successfully.
        notes_authored = _author_from_findings(combined_observations)
        if notes_authored:
            notes_authored = apply_condition_rating_policy(
                notes_authored,
                notes_text=" ".join(combined_observations),
                rating_value=rating_value,
            )
            notes_authored = resolve_specified_tokens(
                notes_authored,
                section_code=sec.id,  # type: ignore[union-attr]
                property_context=property_context,
            )
            _record_retrieval(status="NOTES_ONLY", generated_text=notes_authored)
            return _SectionMappingResult(
                section=GeneratedSection(
                    section_id=sec.id,  # type: ignore[union-attr]
                    title=sec.title,  # type: ignore[union-attr]
                    text=notes_authored,
                    rating_value=(
                        rating_value if schema.rating_system.detected else None
                    ),
                    status="NOTES_ONLY",
                    notes=(
                        "Authored from surveyor notes — no past-report baseline was "
                        "retrieved and no grounding audit was performed. Requires "
                        "surveyor review before issue."
                    ),
                    # Not grounding-audited against a baseline: keep False so no
                    # downstream path can treat notes-authored prose as verified.
                    grounding_passed=False,
                    shorthand_expanded=shorthand_expanded,
                ),
            )
        _record_retrieval(status="NO_RAG_MATCH", generated_text=outcome.text)
        return _SectionMappingResult(
            section=GeneratedSection(
                section_id=sec.id,  # type: ignore[union-attr]
                title=sec.title,  # type: ignore[union-attr]
                text=outcome.text,
                rating_value=rating_value if schema.rating_system.detected else None,
                status="NO_RAG_MATCH",
                notes=(
                    "; ".join(raw_observations)
                    if raw_observations
                    else "No past-report paragraph retrieved for this section."
                ),
                unmatched_observations=raw_observations,
                grounding_passed=False,
                shorthand_expanded=shorthand_expanded,
            ),
        )

    mapped, unmatched = _extract_unmatched(outcome.text)
    section_unmatched = list(outcome.unmatched_observations or []) + unmatched

    reference_paragraphs = [h.text for h in outcome.hits]
    ref_sources, rag_sources = format_reference_attribution(
        outcome.hits,
        schema,
        max_sources=int(settings.retrieval_top_k),
    )
    mappable_observations = [
        o for o in combined_observations if o not in section_unmatched
    ]
    for lim in limitation_obs:
        if lim.strip() and lim not in mappable_observations:
            mappable_observations.append(lim)
    draft_text = sanitize_section_prose(mapped)
    draft_text = apply_condition_rating_policy(
        draft_text,
        notes_text=" ".join(combined_observations),
        rating_value=rating_value,
    )
    draft_text = resolve_specified_tokens(
        draft_text,
        section_code=sec.id,  # type: ignore[union-attr]
        property_context=property_context,
    )
    _record_retrieval(status="MAPPED", generated_text=draft_text)
    fallback_reference = reference_paragraphs[0] if reference_paragraphs else ""
    baseline_paragraph = (
        outcome.baseline_paragraph or fallback_reference or ""
    ).strip()

    section_notes_msg = ""
    if section_unmatched:
        section_notes_msg = "; ".join(section_unmatched)
    elif photo_note:
        section_notes_msg = photo_note
    elif not observations and not photo_obs:
        section_notes_msg = (
            "Past-report paragraph unchanged (no surveyor notes — complete manually)."
        )
    elif photo_obs and not observations:
        section_notes_msg = (
            f"Content mapped from {len(photo_obs)} photo observation(s)."
        )

    rating = rating_value if schema.rating_system.detected else None
    generated = GeneratedSection(
        section_id=sec.id,  # type: ignore[union-attr]
        title=sec.title,  # type: ignore[union-attr]
        text=draft_text,
        rating_value=rating,
        status="OK",
        notes=section_notes_msg,
        rag_sources=rag_sources,
        reference_sources=ref_sources,
        grounding_passed=True,
        unmatched_observations=section_unmatched,
        shorthand_expanded=shorthand_expanded,
    )
    return _SectionMappingResult(
        pending=_PendingValidatedSection(
            section=generated,
            baseline_paragraph=baseline_paragraph,
            draft_text=draft_text,
            observations=mappable_observations,
            template_paragraphs=reference_paragraphs,
        ),
        unmatched=section_unmatched,
    )


def _author_from_findings(observations: list[str]) -> str:
    """Reformat surveyor observation lines into clean prose without inventing content.

    Used only on the otherwise-tombstone path (no past-report baseline). Every
    word originates from the surveyor's own notes — nothing is added.
    """
    items = [o.strip().strip("-*•·").strip() for o in observations if o and o.strip()]
    sentences: list[str] = []
    for item in items:
        if not item:
            continue
        sentence = item[0].upper() + item[1:]
        if sentence[-1] not in ".!?":
            sentence += "."
        sentences.append(sentence)
    return " ".join(sentences).strip()


def _failed_section(
    sec_id: str,
    *,
    title: str,
    error: str,
) -> GeneratedSection:
    return GeneratedSection(
        section_id=sec_id,
        title=title,
        text=_NO_RAG_PLACEHOLDER,
        status="GROUNDING_REVIEW",
        notes=f"Section generation failed: {error}",
        grounding_passed=False,
    )


async def _process_one_section(
    sec_id: str,
    *,
    schema: TemplateSchema,
    tenant_id: str,
    by_id: dict[str, SectionNote],
    id_to_unit: dict[str, object],
    report_draft_id: str | None,
    interference_level: InterferenceLevel,
    retrieval_level: RetrievalLevel,
    allowed_doc_keys: frozenset[str] | None,
    property_context: dict | None = None,
    policy: GenerationPolicy | None = None,
    knowledge_source: str = KNOWLEDGE_SOURCE_BOTH,
) -> tuple[GeneratedSection, list[str]]:
    """Map and validate one section; errors are isolated to a fallback section."""
    sec = id_to_unit.get(sec_id)
    title = sec.title if sec is not None else sec_id  # type: ignore[union-attr]
    with observability.section_scope(sec_id):
        try:
            mapping = await asyncio.to_thread(
                _prepare_section_mapping_sync,
                sec_id,
                schema=schema,
                tenant_id=tenant_id,
                by_id=by_id,
                id_to_unit=id_to_unit,
                report_draft_id=report_draft_id,
                interference_level=interference_level,
                retrieval_level=retrieval_level,
                allowed_doc_keys=allowed_doc_keys,
                property_context=property_context,
                policy=policy,
                knowledge_source=knowledge_source,
            )
            if mapping.section is not None:
                return mapping.section, mapping.unmatched

            pending = mapping.pending
            if pending is None:
                return (
                    _failed_section(sec_id, title=title, error="missing_map_result"),
                    [],
                )

            if not pending.observations:
                logger.info(
                    "baseline_passthrough_no_observations section=%s — skipping semantic audit",
                    pending.section.section_id,
                )
                outcome = _baseline_passthrough_result(
                    pending.section.section_id,
                    pending.baseline_paragraph,
                )
            else:
                validation_input = SectionValidationInput(
                    section_id=pending.section.section_id,
                    section_label=pending.section.title,
                    baseline_paragraph=pending.baseline_paragraph,
                    draft_text=pending.draft_text,
                    observations=pending.observations,
                    template_paragraphs=pending.template_paragraphs,
                    relaxed_violation_types=(
                        sorted(policy.relaxed_violation_types) if policy else []
                    ),
                )
                with observability.span(
                    "validate", section_id=pending.section.section_id
                ):
                    outcome = await stabilize_section(validation_input)
            _apply_validation_outcome(pending, outcome)
            return pending.section, mapping.unmatched
        except Exception as exc:  # noqa: BLE001
            logger.exception("section_processing_failed section=%s", sec_id)
            return _failed_section(sec_id, title=title, error=str(exc)), []


async def _apply_validation_batch(
    pending: list[_PendingValidatedSection],
) -> None:
    """Run the judge-editor loop over mapped drafts and commit stabilized prose."""
    if not pending:
        return

    to_validate: list[_PendingValidatedSection] = []
    stabilized_count = 0
    circuit_breaker_count = 0

    for item in pending:
        if not item.observations:
            logger.info(
                "baseline_passthrough_no_observations section=%s — skipping semantic audit",
                item.section.section_id,
            )
            _apply_validation_outcome(
                item,
                _baseline_passthrough_result(
                    item.section.section_id,
                    item.baseline_paragraph,
                ),
            )
            stabilized_count += 1
            continue
        to_validate.append(item)

    results: list[SectionValidationResult] = []
    if to_validate:
        inputs = [
            SectionValidationInput(
                section_id=item.section.section_id,
                section_label=item.section.title,
                baseline_paragraph=item.baseline_paragraph,
                draft_text=item.draft_text,
                observations=item.observations,
                template_paragraphs=item.template_paragraphs,
            )
            for item in to_validate
        ]
        results = await run_validation_batch(inputs, concurrency=54)

    by_id = {r.section_id.upper(): r for r in results}

    for item in to_validate:
        outcome = by_id.get(item.section.section_id.upper())
        _apply_validation_outcome(item, outcome)
        if outcome is not None and outcome.status == "STABILIZED":
            stabilized_count += 1
        else:
            circuit_breaker_count += 1

    total = len(pending)
    logger.info(
        "validation_batch_complete total_sections=%d stabilized=%d "
        "circuit_breaker_triggered=%d",
        total,
        stabilized_count,
        circuit_breaker_count,
    )


async def _generate_report_impl(
    tenant_id: str,
    raw_notes: str,
    *,
    property_type: str = "",
    tenure: str = "",
    interference_level: str | None = None,
    survey_level: int = 3,
    retrieval_level: RetrievalLevel = "paragraph",
    report_draft_id: str | None = None,
    only_section_ids: list[str] | None = None,
    reference_document_ids: list[str] | None = None,
    strict_uploaded_only: bool = False,
    session_document_ids: list[str] | None = None,
    primary_document_id: str | None = None,
    on_section_complete: SectionCompleteCallback | None = None,
    section_concurrency: int | None = None,
    expert_preferences: dict | None = None,
    knowledge_source: str = KNOWLEDGE_SOURCE_PAST_REPORT,
    structure_mode: str = "rics",
) -> ReportResult:
    # Content-based topic mode: understand + generate by topic, not RICS structure.
    if (structure_mode or "rics").strip().lower() == "content":
        from backend.content_based.orchestrator import generate_content_report

        return await generate_content_report(
            tenant_id,
            raw_notes,
            property_type=property_type,
            tenure=tenure,
            knowledge_source=knowledge_source,
            only_section_ids=only_section_ids,
            reference_document_ids=reference_document_ids,
            strict_uploaded_only=strict_uploaded_only,
            session_document_ids=session_document_ids,
            primary_document_id=primary_document_id,
            on_section_complete=on_section_complete,
            section_concurrency=section_concurrency,
            report_draft_id=report_draft_id,
        )

    section_concurrency = section_concurrency or _default_section_concurrency()
    schema = template_discoverer.ensure_canonical_schema(tenant_id)

    # ``interference_level`` accepts the new mode values ("assist"/"expert") as
    # well as the legacy tiers; the resolved policy carries the mode, Expert
    # preference flags and the auditor relaxation set through the pipeline.
    policy = GenerationPolicy.resolve(
        interference_level, survey_level, expert_preferences=expert_preferences
    )
    interference_level = policy.interference_level
    ks = resolve_knowledge_source(tenant_id, knowledge_source)
    if ks == KNOWLEDGE_SOURCE_BOTH and not settings.dual_path_merge_enabled:
        # Flag off: still prefer past when both exist; SP-only tenants keep SP.
        from backend.pipeline.knowledge_source import (
            tenant_has_past_reports,
            tenant_has_standard_paragraphs,
        )

        if tenant_has_past_reports(tenant_id):
            ks = KNOWLEDGE_SOURCE_PAST_REPORT
        elif tenant_has_standard_paragraphs(tenant_id):
            ks = KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH
    logger.info(
        "generate_report knowledge_source requested=%s resolved=%s tenant=%s",
        knowledge_source,
        ks,
        tenant_id,
    )

    allowed_doc_keys = build_reference_allowlist(
        tenant_id,
        reference_document_ids,
        strict_uploaded_only=strict_uploaded_only,
        session_document_ids=session_document_ids,
        primary_document_id=primary_document_id,
    )

    # UI / dual-path script parity: when the caller already pinned notes per
    # section (one blob each), do not re-split via keyword routing.
    unassigned_note = None
    if pinned_section_notes:
        by_id = {
            sid: note
            for sid, note in pinned_section_notes.items()
            if sid
            and sid.upper() != UNASSIGNED
            and section_accepts_notes(sid)
            and (
                note.raw_observations
                or (note.text or "").strip()
            )
        }
        out_of_scope = [
            note
            for sid, note in pinned_section_notes.items()
            if sid
            and sid.upper() != UNASSIGNED
            and not section_accepts_notes(sid)
            and (note.raw_observations or (note.text or "").strip())
        ]
    else:
        section_notes = parse_notes_to_sections(raw_notes, schema)
        # Notes contract: surveyor observations drive D–J leaves and D–J parent
        # intros. Notes routed to A/B/C or K/L/M/N never drive mapping —
        # those sections are scaffold / manual only.
        # The excluded observations are not dropped: the zero-note-loss
        # reconciliation below surfaces them in the Unassigned appendix.
        by_id = {
            n.section_id: n
            for n in section_notes
            if n.section_id != UNASSIGNED and section_accepts_notes(n.section_id)
        }
        out_of_scope = [
            n
            for n in section_notes
            if n.section_id != UNASSIGNED and not section_accepts_notes(n.section_id)
        ]
        unassigned_note = next(
            (n for n in section_notes if n.section_id == UNASSIGNED), None
        )
    if out_of_scope:
        logger.info(
            "notes_out_of_scope sections=%s — scaffold-only parents never take notes",
            ",".join(
                getattr(n, "section_id", "?") for n in out_of_scope
            ),
        )

    # Structured note extraction → property context for the retrieval guard (Fix 1/3).
    survey_notes = parse_notes(raw_notes)
    property_context = build_property_context(
        survey_notes, property_type=property_type, tenure=tenure
    )

    orphan = _reroute_unassigned_via_rag(
        tenant_id,
        schema,
        unassigned_note,
        by_id,
        interference_level=interference_level,
        allowed_doc_keys=allowed_doc_keys,
    )

    result = ReportResult(
        tenant_id=tenant_id,
        schema_version=schema.version,
        property_type=property_type,
        tenure=tenure,
    )
    unmatched_global: list[str] = []

    active_section_ids = collect_active_section_ids(
        schema,
        by_id,
        tenant_id=tenant_id,
        report_draft_id=report_draft_id,
        only_section_ids=only_section_ids,
    )
    result.active_section_count = len(active_section_ids)

    id_to_unit = {
        sec.id: sec
        for parent in ordered_parent_sections(schema)
        for sec in mapping_units_for_parent(schema, parent.id)
    }

    if active_section_ids:
        limit = max(1, min(section_concurrency, len(active_section_ids)))
        semaphore = asyncio.Semaphore(limit)
        progress_lock = asyncio.Lock()

        async def _run_one(sec_id: str) -> tuple[str, GeneratedSection, list[str]]:
            async with semaphore:
                try:
                    section, unmatched = await _process_one_section(
                        sec_id,
                        schema=schema,
                        tenant_id=tenant_id,
                        by_id=by_id,
                        id_to_unit=id_to_unit,
                        report_draft_id=report_draft_id,
                        interference_level=interference_level,
                        retrieval_level=retrieval_level,
                        allowed_doc_keys=allowed_doc_keys,
                        property_context=property_context,
                        policy=policy,
                        knowledge_source=ks,
                    )
                    await _invoke_section_complete(on_section_complete, section)
                    async with progress_lock:
                        result.processed_section_count += 1
                    return sec_id, section, unmatched
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "unhandled_section_task_failure section=%s", sec_id
                    )
                    sec = id_to_unit.get(sec_id)
                    fallback = _failed_section(
                        sec_id,
                        title=sec.title if sec is not None else sec_id,  # type: ignore[union-attr]
                        error=str(exc),
                    )
                    await _invoke_section_complete(on_section_complete, fallback)
                    async with progress_lock:
                        result.processed_section_count += 1
                    return sec_id, fallback, []

        gathered = await asyncio.gather(
            *[_run_one(sec_id) for sec_id in active_section_ids],
            return_exceptions=True,
        )

        for index, item in enumerate(gathered):
            sec_id = active_section_ids[index]
            if isinstance(item, Exception):
                logger.exception(
                    "section_gather_failure section=%s",
                    sec_id,
                    exc_info=item,
                )
                sec = id_to_unit.get(sec_id)
                fallback = _failed_section(
                    sec_id,
                    title=sec.title if sec is not None else sec_id,  # type: ignore[union-attr]
                    error=str(item),
                )
                await _invoke_section_complete(on_section_complete, fallback)
                async with progress_lock:
                    result.processed_section_count += 1
                result.sections.append(fallback)
                continue

            _sec_id, section, unmatched = item
            unmatched_global.extend(unmatched)
            result.sections.append(section)

    # ── Zero-note-loss reconciliation ────────────────────────────────────────────
    # Every atomic observation from the messy notes must appear somewhere in the
    # assembled report. Anything missing (misrouted, reducer-dropped, or lost by the
    # LLM) is surfaced in the Unassigned appendix rather than silently dropped.
    report_haystack = "\n".join(
        [s.text or "" for s in result.sections]
        + [u for s in result.sections for u in (s.unmatched_observations or [])]
        + orphan
        + unmatched_global
    )
    all_atomic_notes: list[str] = []
    # Prefer ``by_id`` (+ out-of-scope / unassigned) so pinned UI notes work
    # without a ``section_notes`` list from ``parse_notes_to_sections``.
    notes_for_reconcile = list(by_id.values()) + list(out_of_scope or [])
    if unassigned_note is not None:
        notes_for_reconcile.append(unassigned_note)
    for note in notes_for_reconcile:
        for block in note.raw_observations or []:
            all_atomic_notes.extend(split_atomic_observations([block]) or [block])
    leftover_notes = find_uncovered_notes(all_atomic_notes, report_haystack)
    if leftover_notes:
        logger.warning(
            "note_reconciliation surfaced %d uncovered observation(s) to unassigned: %s",
            len(leftover_notes),
            "; ".join(leftover_notes)[:500],
        )

    result.unassigned_text = "\n".join(
        p for p in orphan + unmatched_global + leftover_notes if p
    ).strip()

    if orphan or leftover_notes:
        result.sections.append(
            GeneratedSection(
                section_id=UNASSIGNED,
                title="Unassigned Observations",
                text=(
                    "[These observations could not be matched to any template paragraph. "
                    "Manual review required.]"
                ),
                status="UNASSIGNED",
                unmatched_observations=orphan + leftover_notes,
                grounding_passed=False,
            )
        )

    full = "\n".join(s.text for s in result.sections) + "\n" + result.unassigned_text
    try:
        pii_scrubber.assert_no_pii(full, context="generated report")
    except pii_scrubber.PiiDetectedError:
        logger.warning("Residual PII in generated output; redacting before export.")
        from backend.pii import audit as pii_scrub_audit

        output_session = pii_scrubber.ScrubSession()
        audit_chunks: list[dict] = []
        for s in result.sections:
            scrubbed = pii_scrubber.scrub(s.text, session=output_session)
            s.text = scrubbed.text
            audit_chunks.append(
                {
                    "section_id": s.section_id,
                    "paragraph_index": 0,
                    "chunk_id": f"section:{s.section_id}",
                    "redacted_text": scrubbed.text,
                    "redactions": scrubbed.redactions,
                    "whitelisted": scrubbed.whitelisted,
                    "dropped": False,
                    "residual_leaks": {},
                }
            )
            s.unmatched_observations = [
                pii_scrubber.scrub(u, session=output_session).text
                for u in s.unmatched_observations
            ]
        unassigned_scrub = pii_scrubber.scrub(
            result.unassigned_text, session=output_session
        )
        result.unassigned_text = unassigned_scrub.text
        if unassigned_scrub.redactions or unassigned_scrub.text.strip():
            audit_chunks.append(
                {
                    "section_id": "UNASSIGNED",
                    "paragraph_index": 0,
                    "chunk_id": "unassigned",
                    "redacted_text": unassigned_scrub.text,
                    "redactions": unassigned_scrub.redactions,
                    "whitelisted": unassigned_scrub.whitelisted,
                    "dropped": False,
                    "residual_leaks": {},
                }
            )
        pii_scrub_audit.write_output_mapping(
            tenant_id=tenant_id,
            context_id=report_draft_id or "report",
            chunks=audit_chunks,
        )

    # ── Advisory post-generation evaluation (LLM Approach 2 / optional 3) ────
    # Does not block DOCX; failures become SKIPPED. Token-overlap helpers are
    # intentionally NOT used as evaluation scores.
    try:
        from backend.evaluation import evaluate_report

        evaluation = await evaluate_report(
            result,
            report_id=report_draft_id,
            by_id=by_id,
        )
        if evaluation is not None:
            result.evaluation = evaluation.model_dump()
    except Exception:  # noqa: BLE001 — advisory only
        logger.exception(
            "post_generation_evaluation_failed report=%s",
            report_draft_id,
        )

    return result


async def generate_report_async(
    tenant_id: str,
    raw_notes: str,
    *,
    property_type: str = "",
    tenure: str = "",
    interference_level: str | None = None,
    survey_level: int = 3,
    retrieval_level: RetrievalLevel = "paragraph",
    report_draft_id: str | None = None,
    only_section_ids: list[str] | None = None,
    reference_document_ids: list[str] | None = None,
    strict_uploaded_only: bool = False,
    session_document_ids: list[str] | None = None,
    primary_document_id: str | None = None,
    on_section_complete: SectionCompleteCallback | None = None,
    section_concurrency: int | None = None,
    expert_preferences: dict | None = None,
    knowledge_source: str = KNOWLEDGE_SOURCE_PAST_REPORT,
    structure_mode: str = "rics",
) -> ReportResult:
    """Generate a report under a per-report observability trace.

    Binds a :class:`observability.ReportTrace` (and the parent OTel span) for the
    whole generation so LLM calls, retrieval confidence, violations and quarantines
    made in the concurrent section workers attribute to this report, then rolls up
    and persists the per-report metrics record on completion.
    """
    with observability.report_trace(report_draft_id or "", tenant_id) as trace:
        result = await _generate_report_impl(
            tenant_id,
            raw_notes,
            property_type=property_type,
            tenure=tenure,
            interference_level=interference_level,
            survey_level=survey_level,
            retrieval_level=retrieval_level,
            report_draft_id=report_draft_id,
            only_section_ids=only_section_ids,
            reference_document_ids=reference_document_ids,
            strict_uploaded_only=strict_uploaded_only,
            session_document_ids=session_document_ids,
            primary_document_id=primary_document_id,
            on_section_complete=on_section_complete,
            section_concurrency=section_concurrency or _default_section_concurrency(),
            expert_preferences=expert_preferences,
            knowledge_source=knowledge_source,
            structure_mode=structure_mode,
        )
        trace.finalize(result)
        return result


def generate_report(
    tenant_id: str,
    raw_notes: str,
    *,
    property_type: str = "",
    tenure: str = "",
    interference_level: str | None = None,
    survey_level: int = 3,
    retrieval_level: RetrievalLevel = "paragraph",
    report_draft_id: str | None = None,
    only_section_ids: list[str] | None = None,
    reference_document_ids: list[str] | None = None,
    strict_uploaded_only: bool = False,
    session_document_ids: list[str] | None = None,
    primary_document_id: str | None = None,
    expert_preferences: dict | None = None,
    knowledge_source: str = KNOWLEDGE_SOURCE_PAST_REPORT,
    structure_mode: str = "rics",
) -> ReportResult:
    """Synchronous entrypoint — delegates to :func:`generate_report_async`."""
    return _run_coroutine_sync(
        generate_report_async(
            tenant_id,
            raw_notes,
            property_type=property_type,
            tenure=tenure,
            interference_level=interference_level,
            survey_level=survey_level,
            retrieval_level=retrieval_level,
            report_draft_id=report_draft_id,
            only_section_ids=only_section_ids,
            reference_document_ids=reference_document_ids,
            strict_uploaded_only=strict_uploaded_only,
            session_document_ids=session_document_ids,
            primary_document_id=primary_document_id,
            expert_preferences=expert_preferences,
            knowledge_source=knowledge_source,
            structure_mode=structure_mode,
        )
    )
