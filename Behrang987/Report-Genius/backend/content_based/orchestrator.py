"""Topic-driven report generation (content-based mode).

Parallel to :func:`backend.pipeline.section_mapper.generate_report_async`, but the
unit of work is a content topic/sub-topic (see :mod:`backend.content_based.taxonomy`)
rather than a RICS Level 3 section. Notes are bucketed by meaning, each bucket is
retrieved topic-scoped and written by the LLM, and the result is assembled into a
topic-ordered :class:`ReportResult`.
"""

from __future__ import annotations

import asyncio
import inspect
import logging

from backend.config import settings
from backend.content_based import (
    prompts,
    retriever,
    review_taxonomy,
    router,
    taxonomy,
)
from backend.content_based.models import TopicBucket
from backend.llm import openai_client
from backend.models.report import GeneratedSection, ReferenceSource, ReportResult
from backend.pii import scrubber as pii_scrubber
from backend.pipeline.composition_output import sanitize_section_prose
from backend.rag.reference_filter import build_reference_allowlist
from backend.rag.types import (
    KNOWLEDGE_SOURCE_PAST_REPORT,
    KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH,
    TIER_REFERENCE,
    TIER_STANDARD_PARAGRAPHS,
)

logger = logging.getLogger(__name__)


def _default_concurrency() -> int:
    try:
        from backend.pipeline.section_mapper import _default_section_concurrency

        return _default_section_concurrency()
    except Exception:  # noqa: BLE001
        return 4


async def _emit(cb, section: GeneratedSection) -> None:
    if cb is None:
        return
    res = cb(section)
    if inspect.isawaitable(res):
        await res


def _generate_bucket_section(
    tenant_id: str,
    bucket: TopicBucket,
    *,
    knowledge_source: str,
    property_type: str,
    allowed_doc_keys: frozenset[str] | None,
) -> GeneratedSection:
    """Retrieve topic-scoped baselines and write one topic/sub-topic section."""
    tier = (
        TIER_STANDARD_PARAGRAPHS
        if knowledge_source == KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH
        else TIER_REFERENCE
    )
    scope_pt = property_type if knowledge_source == KNOWLEDGE_SOURCE_PAST_REPORT else None

    hits = retriever.retrieve_topic_hits(
        tenant_id,
        tier=tier,
        topic_id=bucket.topic_id,
        subtopic_id=bucket.subtopic_id,
        observations=bucket.observations,
        top_k=int(settings.retrieval_top_k),
        property_type=scope_pt or None,
        allowed_doc_keys=allowed_doc_keys if tier == TIER_REFERENCE else None,
    )
    style_paragraphs = [h.text for h in hits if (h.text or "").strip()]

    messages = prompts.build_topic_messages(
        topic_label=bucket.topic_label,
        subtopic_label=bucket.subtopic_label,
        observations=bucket.observations,
        style_paragraphs=style_paragraphs,
        rating_value=bucket.rating_value,
    )

    text = ""
    if openai_client.is_available():
        try:
            temperature = (
                float(settings.mapping_temperature)
                if knowledge_source == KNOWLEDGE_SOURCE_PAST_REPORT
                else float(settings.standard_paragraphs_temperature)
            )
            out, _usage = openai_client.chat_text_with_usage(
                messages,
                model=settings.mapping_model,
                max_tokens=settings.max_tokens_mapping,
                temperature=temperature,
                call_label="content_topic_mapping",
            )
            text = sanitize_section_prose((out or "").strip())
        except Exception:  # noqa: BLE001 - one topic failing must not kill the report
            logger.exception("content_topic_generation_failed code=%s", bucket.code)
    if not text:
        # LLM unavailable/failed — fall back to the raw observations so nothing is lost.
        text = "\n".join(bucket.observations).strip()

    reference_sources: list[ReferenceSource] = []
    rag_sources: list[str] = []
    if tier == TIER_REFERENCE:
        seen: set[tuple[str, int]] = set()
        for h in hits:
            fname = (h.source_filename or h.doc_id or "").strip()
            if fname.startswith("reference:"):
                fname = fname.split(":", 1)[-1]
            if not fname:
                continue
            key = (fname, h.paragraph_index or 0)
            if key in seen:
                continue
            seen.add(key)
            reference_sources.append(
                ReferenceSource(
                    report_filename=fname,
                    section_id=h.section_id or "",
                    paragraph_index=h.paragraph_index or 0,
                )
            )
            rag_sources.append(fname)

    status = "OK" if style_paragraphs else "NOTES_ONLY"
    return GeneratedSection(
        section_id=bucket.code,
        title=bucket.subtopic_label or bucket.topic_label,
        text=text,
        rating_value=bucket.rating_value,
        status=status,
        rag_sources=rag_sources,
        reference_sources=reference_sources,
        grounding_passed=True,
        topic_id=bucket.topic_id,
        topic_label=bucket.topic_label,
        subtopic_id=bucket.subtopic_id,
    )


def _scrub_result(tenant_id: str, result: ReportResult, report_draft_id: str | None) -> None:
    full = "\n".join(s.text for s in result.sections)
    try:
        pii_scrubber.assert_no_pii(full, context="generated content report")
        return
    except pii_scrubber.PiiDetectedError:
        logger.warning("Residual PII in content-mode output; redacting before export.")
    session = pii_scrubber.ScrubSession()
    for s in result.sections:
        s.text = pii_scrubber.scrub(s.text, session=session).text


async def generate_content_report(
    tenant_id: str,
    raw_notes: str,
    *,
    property_type: str = "",
    tenure: str = "",
    knowledge_source: str = KNOWLEDGE_SOURCE_PAST_REPORT,
    only_section_ids: list[str] | None = None,
    reference_document_ids: list[str] | None = None,
    strict_uploaded_only: bool = False,
    session_document_ids: list[str] | None = None,
    primary_document_id: str | None = None,
    on_section_complete=None,
    section_concurrency: int | None = None,
    report_draft_id: str | None = None,
    schema_version: int = 2,
) -> ReportResult:
    """Generate a topic-structured report from messy notes."""
    ks = (knowledge_source or KNOWLEDGE_SOURCE_PAST_REPORT).strip().lower()
    if ks not in (KNOWLEDGE_SOURCE_PAST_REPORT, KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH):
        ks = KNOWLEDGE_SOURCE_PAST_REPORT

    from backend.domain.property_type import try_canonical_property_type

    canonical_pt = try_canonical_property_type(property_type) or ""

    allowed_doc_keys = build_reference_allowlist(
        tenant_id,
        reference_document_ids,
        strict_uploaded_only=strict_uploaded_only,
        session_document_ids=session_document_ids,
        primary_document_id=primary_document_id,
    )

    buckets = router.bucket_notes_by_topic(raw_notes)
    if only_section_ids:
        # The client speaks review codes (see content_based.review_taxonomy) while
        # buckets are keyed by v2 sub-topic, so "heating" and "water_heating" both
        # have to select the merged heating_hot_water bucket.
        raw_wanted = {c.strip() for c in only_section_ids if c and c.strip()}
        wanted = raw_wanted | review_taxonomy.v2_subtopic_ids(raw_wanted)
        buckets = [b for b in buckets if b.code in wanted]

    result = ReportResult(
        tenant_id=tenant_id,
        schema_version=schema_version,
        property_type=property_type,
        tenure=tenure,
    )
    result.active_section_count = len(buckets)
    if not buckets:
        return result

    limit = max(1, min(section_concurrency or _default_concurrency(), len(buckets)))
    semaphore = asyncio.Semaphore(limit)
    progress_lock = asyncio.Lock()

    async def _run_one(bucket: TopicBucket) -> GeneratedSection:
        async with semaphore:
            section = await asyncio.to_thread(
                _generate_bucket_section,
                tenant_id,
                bucket,
                knowledge_source=ks,
                property_type=canonical_pt,
                allowed_doc_keys=allowed_doc_keys,
            )
            await _emit(on_section_complete, section)
            async with progress_lock:
                result.processed_section_count += 1
            return section

    gathered = await asyncio.gather(
        *[_run_one(b) for b in buckets], return_exceptions=True
    )
    for bucket, item in zip(buckets, gathered):
        if isinstance(item, Exception):
            logger.exception("content_bucket_failure code=%s", bucket.code, exc_info=item)
            result.sections.append(
                GeneratedSection(
                    section_id=bucket.code,
                    title=bucket.subtopic_label or bucket.topic_label,
                    text="\n".join(bucket.observations).strip(),
                    status="NOTES_ONLY",
                    topic_id=bucket.topic_id,
                    topic_label=bucket.topic_label,
                    subtopic_id=bucket.subtopic_id,
                    grounding_passed=False,
                )
            )
        else:
            result.sections.append(item)

    result.sections.sort(
        key=lambda s: (taxonomy.topic_order(s.topic_id), s.subtopic_id)
    )
    _scrub_result(tenant_id, result, report_draft_id)
    return result
