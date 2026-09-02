"""Operator bundle ingest: report template (PDF) + standard paragraphs (Word).

* **Report template (PDF)** — schema discovery only (section order, titles, ratings).
  Defines how the finished report is structured.
* **Standard paragraphs (Word)** — firm-approved boilerplate per section, ingested
  into the MASTER RAG tier (not scrubbed; gated by ``assert_no_pii``).
* **Reference uploads** — optional past completed reports, scrubbed, style only.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from backend.config import settings
from backend.domain import template_discoverer
from backend.domain.rics_level3_schema import PARENT_SECTION_COUNT
from backend.ingest import doc_extractor
from backend.pii import scrubber as pii_scrubber
from backend.rag.store import get_rag_store
from backend.rag.types import TIER_MASTER, TIER_REFERENCE, Chunk

logger = logging.getLogger(__name__)


def _chunk_text(text: str) -> list[str]:
    min_c = settings.paragraph_min_chars
    max_c = settings.paragraph_max_chars
    overlap = settings.chunk_overlap
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        return []

    merged: list[str] = []
    buf = ""
    for para in paras:
        if not buf:
            buf = para
        else:
            buf = f"{buf}\n\n{para}"
        if len(buf) >= min_c:
            merged.append(buf)
            buf = ""
    if buf:
        if merged and len(buf) < min_c:
            merged[-1] = f"{merged[-1]}\n\n{buf}"
        else:
            merged.append(buf)

    chunks: list[str] = []
    for block in merged:
        if len(block) <= max_c:
            chunks.append(block)
            continue
        step = max(max_c - overlap, 1)
        for i in range(0, len(block), step):
            piece = block[i : i + max_c].strip()
            if piece:
                chunks.append(piece)
    return [c for c in chunks if c.strip()]


def _chunk_reference_text(text: str) -> list[str]:
    """Split REFERENCE past-report text into long-form chunks (heading-aware)."""
    from backend.config import settings

    min_c = settings.paragraph_min_chars
    max_c = settings.reference_paragraph_max_chars
    overlap = settings.reference_chunk_overlap
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        return []

    merged: list[str] = []
    buf = ""
    for para in paras:
        if not buf:
            buf = para
        else:
            buf = f"{buf}\n\n{para}"
        if len(buf) >= min_c:
            merged.append(buf)
            buf = ""
    if buf:
        if merged and len(buf) < min_c:
            merged[-1] = f"{merged[-1]}\n\n{buf}"
        else:
            merged.append(buf)

    chunks: list[str] = []
    for block in merged:
        if len(block) <= max_c:
            chunks.append(block)
            continue
        step = max(max_c - overlap, 1)
        for i in range(0, len(block), step):
            piece = block[i : i + max_c].strip()
            if piece:
                chunks.append(piece)
    return [c for c in chunks if c.strip()]


def _operator_filenames_lower() -> frozenset[str]:
    return frozenset(
        {
            settings.report_template_filename.lower(),
            settings.standard_paragraphs_filename.lower(),
            settings.master_template_filename.lower(),
        }
    )


def ingest_report_template(tenant_id: str, path: Path) -> dict:
    """Discover and persist schema from the report template PDF/DOCX."""
    if not path.is_file():
        raise FileNotFoundError(f"Report template not found: {path}")

    schema = template_discoverer.discover_report_template_schema(path)
    schema.report_template_source = path.name
    schema.source_filename = path.name
    template_discoverer.save_schema(tenant_id, schema)

    logger.info(
        "Report template ingested for tenant=%s: %d parent sections from %s",
        tenant_id,
        PARENT_SECTION_COUNT,
        path.name,
    )
    return {
        "sections": PARENT_SECTION_COUNT,
        "schema_version": schema.version,
        "report_template": path.name,
    }


def ingest_standard_paragraphs(tenant_id: str, path: Path) -> dict:
    """Ingest standard paragraph wording into the standard_paragraphs RAG tier."""
    from backend.standard_paragraphs.service import operator_ingest_word

    if not path.is_file():
        raise FileNotFoundError(f"Standard paragraphs file not found: {path}")

    result = operator_ingest_word(tenant_id, path)
    schema = template_discoverer.load_schema(tenant_id)
    alias_count = 0
    if schema is not None:
        alias_count = sum(1 for k, v in schema.section_alias_map.items() if k != v)

    logger.info(
        "Standard paragraphs ingested for tenant=%s: %d chunks, %d aliases from %s",
        tenant_id,
        result.get("chunks", 0),
        alias_count,
        path.name,
    )
    return {
        "chunks": result.get("chunks", 0),
        "standard_paragraphs": path.name,
        "section_aliases": alias_count,
    }


def ingest_operator_bundle(tenant_id: str) -> dict:
    """Ingest report template (schema) + standard paragraphs (MASTER RAG)."""
    template_res = ingest_report_template(tenant_id, settings.report_template_path)
    paragraphs_res = ingest_standard_paragraphs(
        tenant_id, settings.standard_paragraphs_path
    )
    return {
        "sections": template_res["sections"],
        "schema_version": template_res["schema_version"],
        "report_template": template_res["report_template"],
        "standard_paragraphs": paragraphs_res["standard_paragraphs"],
        "paragraph_chunks": paragraphs_res["chunks"],
    }


def ingest_master(tenant_id: str, path: Path) -> dict:
    """Legacy/admin helper: treat a single file as both template and paragraphs."""
    schema, discovered = template_discoverer.discover_schema(path)
    full_text = doc_extractor.extract_text(path)
    pii_scrubber.assert_no_pii(full_text, context=f"master template {path.name}")
    template_discoverer.save_schema(tenant_id, schema)

    store = get_rag_store()
    store.clear_tier(tenant_id, TIER_MASTER)
    total = 0
    for dc in discovered:
        chunks = [
            Chunk(
                text=t,
                section_id=dc.section_id,
                tier=TIER_MASTER,
                is_scrubbed=False,
                source_filename=path.name,
            )
            for t in _chunk_text(dc.text)
        ]
        total += store.ingest_document(
            tenant_id,
            doc_id=f"master:{schema.source_filename}",
            chunks=chunks,
            tier=TIER_MASTER,
            source_filename=path.name,
        )
    return {
        "sections": len(schema.sections),
        "chunks": total,
        "schema_version": schema.version,
        "source": schema.source_filename,
    }


def ingest_reference(
    tenant_id: str, path: Path, *, property_type: str = ""
) -> int:
    """Ingest a past report into REFERENCE tier; PII scrubbed per chunk in RagStore."""
    return ingest_reference_report(
        tenant_id, path, property_type=property_type
    )["chunks"]


def ingest_reference_report(
    tenant_id: str,
    path: Path,
    *,
    source_filename: str | None = None,
    property_type: str = "",
) -> dict:
    """Ingest a past report and return chunk count + per-subsection verification.

    Segmentation prefers the LLM path (canonical storage units: leaf ids for
    D–I/J, parent-level bodies for A/B/C/K/L/M/N, explicit parent-intro
    buckets) and falls back to the regex heading chunker when the LLM is
    unavailable or fails. The verification report is surfaced to the caller so
    mis-tagged uploads are caught at upload time, not in the generated report.

    ``source_filename`` is the human-readable original upload name stamped onto
    chunk metadata / manifests / chunk_ids. Disk storage may still use a
    UUID-based ``path.name`` for path safety — that hashed name must NOT leak
    into JSON ``source_filename`` fields when the original is known.

    Extracted text is always written to
    ``tenants/<id>/reference_extracts/<original_filename>.extracted.md`` first;
    chunking then reads that markdown so the operator can inspect exactly what
    was read.
    """
    from backend.cost import tenant_scope

    with tenant_scope(tenant_id):
        return _ingest_reference_report_impl(
            tenant_id,
            path,
            source_filename=source_filename,
            property_type=property_type,
        )


def _ingest_reference_report_impl(
    tenant_id: str,
    path: Path,
    *,
    source_filename: str | None = None,
    property_type: str = "",
) -> dict:
    from backend.ingest import llm_segmenter
    from backend.ingest.verification import build_ingest_verification
    from backend.storage.photo_layout import merge_layout_from_reference_docx

    label = (source_filename or "").strip() or path.name
    raw_text = doc_extractor.extract_text(path)
    extraction_method = "docx"
    if path.suffix.lower() == ".pdf":
        from backend.ingest.pdf_extractors import resolve_pdf_extractor

        extraction_method = resolve_pdf_extractor()

    md_path = _write_reference_extract_markdown(
        tenant_id,
        source_filename=label,
        extraction_method=extraction_method,
        text=raw_text,
        document_id=path.stem,
    )
    text = _read_reference_extract_markdown(md_path)
    schema = template_discoverer.load_schema(tenant_id)
    valid = set(schema.section_ids()) if schema else None

    segmentation_method = "regex"
    chunks = llm_segmenter.llm_segment_reference_text(text, source_filename=label)
    if chunks:
        segmentation_method = "llm"
    else:
        from backend.rag.reference_chunker import build_reference_chunks

        chunks = build_reference_chunks(
            text,
            source_filename=label,
            valid_section_ids=valid,
        )

    from backend.domain.property_type import try_canonical_property_type

    canonical_pt = try_canonical_property_type(property_type) or ""
    if canonical_pt:
        for chunk in chunks:
            chunk.property_type = canonical_pt

    # Content-based topic mode: classify each chunk by meaning (topic + sub-topic)
    # so non-RICS reports become usable in topic mode without re-ingest.
    from backend.content_based import tagging as content_tagging

    topic_coverage = content_tagging.tag_chunks(chunks)

    verification = build_ingest_verification(
        chunks,
        source_filename=label,
        segmentation_method=segmentation_method,
    )
    embedded = bool(settings.ingest_embed_enabled)
    count = get_rag_store().ingest_document(
        tenant_id,
        doc_id=f"reference:{path.name}",
        chunks=chunks,
        tier=TIER_REFERENCE,
        source_filename=label,
    )
    if path.suffix.lower() in (".docx", ".docm"):
        section_ids = set(schema.section_ids()) if schema else None
        merge_layout_from_reference_docx(tenant_id, path, valid_section_ids=section_ids)
    logger.info(
        "Reference ingest %s (stored as %s): extraction=%s md=%s segmentation=%s chunks=%d embedded=%s",
        label,
        path.name,
        extraction_method,
        md_path.name,
        segmentation_method,
        count,
        embedded,
    )
    return {
        "chunks": count,
        "verification": verification,
        "embedded": embedded,
        "segmentation_method": segmentation_method,
        "extraction_method": extraction_method,
        "extract_markdown_path": str(md_path),
        "property_type": canonical_pt,
        "topic_coverage": topic_coverage,
    }


_EXTRACT_MD_HEADER_RE = re.compile(
    r"(?s)\A<!--\s*rics-extract\b.*?-->\s*",
    re.IGNORECASE,
)


def _write_reference_extract_markdown(
    tenant_id: str,
    *,
    source_filename: str,
    extraction_method: str,
    text: str,
    document_id: str = "",
) -> Path:
    """Persist extractor output as markdown for inspection + chunking source of truth."""
    from backend.storage import tenant_store

    path = tenant_store.reference_extract_md_path(tenant_id, source_filename)
    safe_source = (source_filename or "").replace("-->", "->")
    doc_bit = f" document_id={document_id}" if document_id else ""
    header = (
        f"<!-- rics-extract source={safe_source!r} "
        f"extractor={extraction_method}{doc_bit} -->\n\n"
    )
    path.write_text(header + (text or "").strip() + "\n", encoding="utf-8")
    return path


def _read_reference_extract_markdown(path: Path) -> str:
    """Load extract markdown and strip the machine header before chunking."""
    raw = path.read_text(encoding="utf-8")
    return _EXTRACT_MD_HEADER_RE.sub("", raw).strip()


def auto_ingest_reference_dir(tenant_id: str) -> dict:
    """Pre-seed optional reference docs; never ingests the operator bundle files."""
    folder = settings.reference_dir_path
    if not folder.is_dir():
        return {"documents": 0, "chunks": 0}

    globs = [
        g.strip() for g in settings.reference_auto_ingest_globs.split(",") if g.strip()
    ]
    skip = _operator_filenames_lower()
    seen: set[Path] = set()
    docs = 0
    total = 0
    for pattern in globs:
        for f in sorted(folder.glob(pattern)):
            if f.name.lower() in skip or f in seen:
                continue
            seen.add(f)
            try:
                total += ingest_reference(tenant_id, f)
                docs += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("Reference auto-ingest failed for %s (%s).", f.name, exc)

    logger.info(
        "Reference auto-ingest for tenant=%s: %d docs, %d chunks",
        tenant_id,
        docs,
        total,
    )
    return {"documents": docs, "chunks": total}
