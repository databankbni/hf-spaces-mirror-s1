"""Orchestrate legacy generate / proofread / enhance for compat routes."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.compat.legacy_api_adapter import (
    bullets_to_raw_notes,
    interference_for_mode,
    result_to_sections_payload,
    section_notes_from_bullets_by_section,
    section_to_payload,
)
from backend.domain import template_discoverer
from backend.domain.interference import resolve_interference_level
from backend.domain.style_profile import StyleProfile, get_style_profile
from backend.domain.text_modes import enhance_text, proofread_text
from backend.models.report import GeneratedSection
from backend.pipeline import section_mapper
from backend.rag.reference_filter import build_reference_allowlist
from backend.rag.retriever import retrieve_paragraphs_for_mapping
from backend.storage.report_session import ReportSession, load_session, save_session

logger = logging.getLogger(__name__)


def _persist_partial(session: ReportSession, payloads: dict[str, dict]) -> None:
    """Flush completed section payloads while generation is still running."""
    merged = dict(session.sections_payload)
    merged.update(payloads)
    session.sections_payload = merged
    save_session(session)


def _target_section_codes(body: Any) -> list[str]:
    codes = [body.template_id] if body.template_id else []
    codes.extend(body.template_ids or [])
    seen: set[str] = set()
    out: list[str] = []
    for code in codes:
        c = (code or "").strip()
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _bullets_for_section(body: Any, section_code: str) -> list[str]:
    by_sec = body.bullets_by_section or {}
    if section_code in by_sec and by_sec[section_code]:
        return list(by_sec[section_code])
    if section_code == body.template_id:
        return list(body.bullets or [])
    return []


def _existing_section_text(session: ReportSession, section_code: str, body: Any) -> str:
    payload = session.sections_payload.get(section_code, {})
    text = (payload.get("text") or "").strip()
    if text:
        return text
    if section_code == body.template_id and body.draft_paragraph:
        return body.draft_paragraph.strip()
    return ""


def _retrieval_filter(body: Any) -> tuple[list[str] | None, bool]:
    ref_ids = list(body.reference_document_ids or [])
    strict = bool(body.strict_uploaded_only)
    return (ref_ids or None), strict


def _seed_section(
    tenant_id: str,
    session: ReportSession,
    section_code: str,
    bullets: list[str],
    *,
    interference_level: str,
    retrieval_level: str,
    reference_document_ids: list[str] | None = None,
    strict_uploaded_only: bool = False,
) -> GeneratedSection | None:
    raw_notes = bullets_to_raw_notes(section_code, bullets, None)
    result = section_mapper.generate_report(
        tenant_id,
        raw_notes,
        property_type=session.property_type,
        tenure=session.tenure,
        interference_level=interference_level,  # type: ignore[arg-type]
        report_draft_id=session.draft_id,
        retrieval_level=retrieval_level,
        only_section_ids=[section_code],
        reference_document_ids=reference_document_ids,
        strict_uploaded_only=strict_uploaded_only,
    )
    for sec in result.sections:
        if sec.section_id == section_code:
            return sec
    return None


def _proofread_section_payload(
    tenant_id: str,
    session: ReportSession,
    section_code: str,
    body: Any,
    *,
    interference_level: str,
    retrieval_level: str,
    style: StyleProfile,
    reference_document_ids: list[str] | None = None,
    strict_uploaded_only: bool = False,
) -> dict:
    bullets = _bullets_for_section(body, section_code)
    existing = _existing_section_text(session, section_code, body)
    if not existing:
        seeded = _seed_section(
            tenant_id,
            session,
            section_code,
            bullets,
            interference_level=interference_level,
            retrieval_level=retrieval_level,
            reference_document_ids=reference_document_ids,
            strict_uploaded_only=strict_uploaded_only,
        )
        if seeded is None:
            existing = ""
        else:
            existing = seeded.text or ""

    final_text = proofread_text(existing, bullets, style_profile=style)
    section = GeneratedSection(
        section_id=section_code,
        title=section_code,
        text=final_text,
        status="OK",
        grounding_passed=True,
        notes="Proofread pass applied.",
    )
    return section_to_payload(
        section,
        interference_level=interference_level,
        mode="proofread",
        style_profile=style,
    )


def _enhance_section_payload(
    tenant_id: str,
    session: ReportSession,
    section_code: str,
    body: Any,
    *,
    interference_level: str,
    retrieval_level: str,
    style: StyleProfile,
    allowed_doc_keys: frozenset[str] | None = None,
    reference_document_ids: list[str] | None = None,
    strict_uploaded_only: bool = False,
) -> dict:
    schema = template_discoverer.ensure_canonical_schema(tenant_id)
    bullets = _bullets_for_section(body, section_code)
    existing = _existing_section_text(session, section_code, body)
    force = bool(body.force_regenerate)

    if not existing or force:
        seeded = _seed_section(
            tenant_id,
            session,
            section_code,
            bullets,
            interference_level=interference_level,
            retrieval_level=retrieval_level,
            reference_document_ids=reference_document_ids,
            strict_uploaded_only=strict_uploaded_only,
        )
        existing = seeded.text if seeded else existing

    sec_title = section_code
    paragraph_id = section_code
    if schema:
        sec = schema.get_section(section_code)
        if sec:
            sec_title = sec.title
            paragraph_id = schema.paragraph_section_id(section_code)

    hits = retrieve_paragraphs_for_mapping(
        tenant_id,
        section_label=sec_title,
        paragraph_section_id=paragraph_id,
        observations=bullets or [sec_title],
        interference_level=interference_level,  # type: ignore[arg-type]
        retrieval_level=retrieval_level,
        top_k=8,
        allowed_doc_keys=allowed_doc_keys,
    )
    snippets = [h.text for h in hits]

    final_text = enhance_text(
        existing,
        bullets,
        snippets,
        style_profile=style,
        schema=schema,
    )
    section = GeneratedSection(
        section_id=section_code,
        title=sec_title,
        text=final_text,
        status="OK",
        grounding_passed=True,
        notes="Enhance pass applied with reference evidence.",
    )
    return section_to_payload(
        section,
        interference_level=interference_level,
        mode="enhance",
        style_profile=style,
    )


def run_legacy_generation(tenant_id: str, report_id: str, body: Any) -> None:
    session = load_session(tenant_id, report_id)
    if session is None:
        return

    try:
        structure_mode = (
            getattr(body, "structure_mode", None)
            or getattr(session, "structure_mode", None)
            or "rics"
        ).strip().lower()
        if structure_mode not in ("rics", "content"):
            structure_mode = "rics"
        knowledge_source = (
            getattr(body, "knowledge_source", None) or "past_report"
        ).strip().lower()
        if knowledge_source == "past_report":
            from backend.domain.property_type import (
                PropertyTypeError,
                normalize_property_type,
            )

            raw_pt = getattr(body, "property_type", None) or session.property_type
            try:
                session.property_type = normalize_property_type(raw_pt)
            except PropertyTypeError as exc:
                session.status = "failed"
                session.error_message = str(exc)
                save_session(session)
                return
            save_session(session)

        if body.interference_level:
            il = resolve_interference_level(
                body.interference_level, session.survey_level
            )
        elif body.mode == "generate":
            il = resolve_interference_level(None, session.survey_level)
        else:
            il = interference_for_mode(body.mode, None)
        retrieval_level = (body.retrieval_level or "paragraph").strip().lower()
        ref_ids, strict_only = _retrieval_filter(body)
        allowed_doc_keys = build_reference_allowlist(
            tenant_id,
            ref_ids,
            strict_uploaded_only=strict_only,
            session_document_ids=session.document_ids,
            primary_document_id=session.primary_document_id,
        )
        style = get_style_profile(tenant_id)
        targets = _target_section_codes(body)
        payloads: dict[str, dict] = {}
        result = None

        if body.mode == "proofread":
            for code in targets:
                payloads[code] = _proofread_section_payload(
                    tenant_id,
                    session,
                    code,
                    body,
                    interference_level=il,
                    retrieval_level=retrieval_level,
                    style=style,
                    reference_document_ids=ref_ids,
                    strict_uploaded_only=strict_only,
                )
                _persist_partial(session, {code: payloads[code]})
        elif body.mode == "enhance":
            for code in targets:
                payloads[code] = _enhance_section_payload(
                    tenant_id,
                    session,
                    code,
                    body,
                    interference_level=il,
                    retrieval_level=retrieval_level,
                    style=style,
                    allowed_doc_keys=allowed_doc_keys,
                    reference_document_ids=ref_ids,
                    strict_uploaded_only=strict_only,
                )
                _persist_partial(session, {code: payloads[code]})
        else:
            # Content mode: Stage A filing is the note source of truth. Prefer
            # stored assignments over request bullets so generation does not
            # depend on (or get overridden by) manually typed textareas.
            effective_bbs = body.bullets_by_section or None
            if structure_mode == "content":
                from backend.content_based import stage_dump

                effective_bbs = stage_dump.resolve_content_mode_notes(
                    tenant_id, body.bullets_by_section or None
                )

            raw_notes = bullets_to_raw_notes(
                body.template_id,
                body.bullets,
                effective_bbs,
            )
            pinned_notes = section_notes_from_bullets_by_section(effective_bbs)
            # Single-section generate (template_id + bullets only, no map).
            if not pinned_notes and body.template_id and body.bullets:
                pinned_notes = section_notes_from_bullets_by_section(
                    {body.template_id: list(body.bullets or [])}
                )
            if body.draft_paragraph and body.template_id:
                prefix = f"{body.template_id}: "
                if raw_notes.strip():
                    raw_notes = f"{prefix}{body.draft_paragraph.strip()}\n\n{raw_notes}"
                else:
                    raw_notes = f"{prefix}{body.draft_paragraph.strip()}"
                # Keep draft_paragraph in the pinned blob for that section.
                sid = (body.template_id or "").strip().upper()
                if sid:
                    from backend.models.section import SectionNote

                    draft = body.draft_paragraph.strip()
                    existing = pinned_notes.get(sid)
                    if existing and (existing.text or "").strip():
                        blob = f"{draft}\n\n{existing.text.strip()}".strip()
                    else:
                        blob = draft
                    pinned_notes[sid] = SectionNote(
                        section_id=sid,
                        raw_observations=[blob],
                        text=blob,
                    )

            only_ids = targets if targets else None

            async def _run_generate() -> Any:
                async def on_section(section: GeneratedSection) -> None:
                    payload = section_to_payload(
                        section,
                        interference_level=il,
                        mode=body.mode,
                        style_profile=style,
                    )
                    await asyncio.to_thread(
                        _persist_partial,
                        session,
                        {section.section_id: payload},
                    )

                return await section_mapper.generate_report_async(
                    tenant_id,
                    raw_notes,
                    property_type=session.property_type,
                    tenure=session.tenure,
                    interference_level=il,  # type: ignore[arg-type]
                    survey_level=session.survey_level,
                    report_draft_id=session.draft_id,
                    retrieval_level=retrieval_level,
                    only_section_ids=only_ids,
                    reference_document_ids=ref_ids,
                    strict_uploaded_only=strict_only,
                    session_document_ids=session.document_ids,
                    primary_document_id=session.primary_document_id,
                    on_section_complete=on_section,
                    knowledge_source=getattr(
                        body, "knowledge_source", None
                    )
                    or "past_report",
                    structure_mode=structure_mode,
                )

            result = section_mapper._run_coroutine_sync(_run_generate())
            payloads = result_to_sections_payload(
                result,
                interference_level=il,
                mode=body.mode,
                style_profile=style,
            )
            try:
                from backend.storage.generation_run_export import (
                    export_ui_generation_run,
                )

                export_ui_generation_run(
                    tenant_id=tenant_id,
                    draft_id=session.draft_id or report_id,
                    property_type=session.property_type or "",
                    knowledge_source=str(
                        getattr(body, "knowledge_source", None) or "both"
                    ),
                    interference_level=str(il or ""),
                    raw_notes=raw_notes,
                    sections=list(getattr(result, "sections", None) or []),
                )
            except Exception:  # noqa: BLE001 — export must not fail generate
                logger.warning(
                    "generation run export failed report=%s",
                    report_id,
                    exc_info=True,
                )

        merged = dict(session.sections_payload)
        if targets:
            allowed = set(targets)
            merged.update({k: v for k, v in payloads.items() if k in allowed})
        else:
            merged.update(payloads)

        session.sections_payload = merged
        session.interference_level = il
        session.evaluation = getattr(result, "evaluation", None)
        session.status = "complete"
        session.error_message = None
    except Exception as exc:  # noqa: BLE001
        logger.exception("Generation failed for report %s: %s", report_id, exc)
        session.status = "failed"
        session.error_message = str(exc)

    save_session(session)
