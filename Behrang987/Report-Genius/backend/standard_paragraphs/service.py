"""Shared ingest for Word/PDF upload, Add to Memory, and operator seed."""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from backend.domain import section_bridge, template_discoverer
from backend.pii import scrubber as pii_scrubber
from backend.rag.store import (
    DOC_TYPE_ADD_TO_MEMORY,
    get_rag_store,
    is_add_to_memory_meta,
)
from backend.rag.types import (
    CONTENT_ROLE_BODY,
    TIER_REFERENCE,
    TIER_STANDARD_PARAGRAPHS,
    Chunk,
)
from backend.standard_paragraphs.models import IngestionSource
from backend.storage import tenant_store

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def content_hash(section_id: str, text: str) -> str:
    norm = re.sub(r"\s+", " ", (text or "")).strip().lower()
    payload = f"{(section_id or '').strip().upper()}\n{norm}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parent_id(subsection_id: str) -> str:
    s = (subsection_id or "").strip().upper()
    return s[0] if s and s[0].isalpha() else ""


def ingest_paragraphs(
    tenant_id: str,
    items: list[dict],
    *,
    doc_id: str,
    source_filename: str = "",
    ingestion_source: IngestionSource = "upload",
    replace_all: bool = False,
    blob_key: str = "",
) -> dict:
    """Embed and append paragraphs into the standard_paragraphs tier.

    Each item: ``{text, section_id, section_name?, paragraph_index?, parent_id?}``.
    When ``replace_all`` is True (operator full reseed), the tier is cleared first.
    """
    from backend.cost import tenant_scope

    with tenant_scope(tenant_id):
        return _ingest_paragraphs_impl(
            tenant_id,
            items,
            doc_id=doc_id,
            source_filename=source_filename,
            ingestion_source=ingestion_source,
            replace_all=replace_all,
            blob_key=blob_key,
        )


def _ingest_paragraphs_impl(
    tenant_id: str,
    items: list[dict],
    *,
    doc_id: str,
    source_filename: str = "",
    ingestion_source: IngestionSource = "upload",
    replace_all: bool = False,
    blob_key: str = "",
) -> dict:
    store = get_rag_store()
    if replace_all:
        store.clear_tier(tenant_id, TIER_STANDARD_PARAGRAPHS)

    created = _utcnow_iso()
    chunks: list[Chunk] = []
    for i, raw in enumerate(items):
        text = str(raw.get("text") or "").strip()
        section_id = str(raw.get("section_id") or "").strip()
        if not text or not section_id:
            continue
        ch = content_hash(section_id, text)
        chunks.append(
            Chunk(
                text=text,
                section_id=section_id,
                section_name=str(raw.get("section_name") or ""),
                parent_id=str(raw.get("parent_id") or _parent_id(section_id)),
                tier=TIER_STANDARD_PARAGRAPHS,
                is_scrubbed=False,
                chunk_id=str(raw.get("chunk_id") or f"{doc_id}:{i}"),
                source_filename=source_filename,
                paragraph_index=int(raw.get("paragraph_index") or i),
                ingestion_source=ingestion_source,
                content_hash=ch,
                created_at=created,
                blob_key=blob_key,
                doc_id=doc_id,
            )
        )

    if not chunks:
        return {"chunks": 0, "deduplicated": 0, "doc_id": doc_id}

    # Content-based topic mode: tag standard paragraphs by meaning too.
    from backend.content_based import tagging as content_tagging

    content_tagging.tag_chunks(chunks)

    count = store.ingest_document(
        tenant_id,
        doc_id=doc_id,
        chunks=chunks,
        tier=TIER_STANDARD_PARAGRAPHS,
        source_filename=source_filename,
    )
    skipped = len(chunks) - count
    return {
        "chunks": count,
        "deduplicated": max(0, skipped),
        "doc_id": doc_id,
        "attempted": len(chunks),
    }


def ingest_runtime_memory(
    tenant_id: str,
    *,
    subsection_id: str,
    text: str,
    section_id: str | None = None,
    section_name: str | None = None,
) -> dict:
    """Add a single paragraph from the UI 'Add to Memory' control.

    Stored in the REFERENCE (past-report) FAISS index with
    ``document_type=add_to_memory`` so callers can filter these chunks when
    injecting them into prompts, without mixing them into past-report baselines.
    """
    from backend.cost import tenant_scope

    with tenant_scope(tenant_id):
        return _ingest_runtime_memory_impl(
            tenant_id,
            subsection_id=subsection_id,
            text=text,
            section_id=section_id,
            section_name=section_name,
        )


def _ingest_runtime_memory_impl(
    tenant_id: str,
    *,
    subsection_id: str,
    text: str,
    section_id: str | None = None,
    section_name: str | None = None,
) -> dict:
    sid = (subsection_id or "").strip()
    body = (text or "").strip()
    if not sid or not body:
        raise ValueError("subsection_id and text are required")

    pii_scrubber.assert_no_pii(body, context=f"add to memory {sid}")

    parent = (section_id or "").strip() or _parent_id(sid)
    doc_id = f"runtime:{uuid.uuid4().hex[:12]}"
    ch = content_hash(sid, body)
    chunk_id = f"{doc_id}:0"
    created = _utcnow_iso()

    # Fast path: if identical hash already present among Add-to-Memory rows, skip.
    store = get_rag_store()
    for row in store.list_meta(tenant_id, TIER_REFERENCE, section_id=sid):
        if not is_add_to_memory_meta(row):
            continue
        if str(row.get("content_hash") or "") == ch or content_hash(
            sid, str(row.get("text") or "")
        ) == ch:
            return {
                "chunk_id": row.get("chunk_id") or "",
                "deduplicated": True,
                "chunks": 0,
                "doc_id": row.get("doc_id") or "",
                "document_type": DOC_TYPE_ADD_TO_MEMORY,
                "tier": TIER_REFERENCE,
            }

    # assert_no_pii already gated; mark scrubbed so REFERENCE ingest skips
    # report-style redaction that would rewrite firm wording.
    chunk = Chunk(
        text=body,
        section_id=sid,
        section_name=section_name or "",
        parent_id=parent,
        tier=TIER_REFERENCE,
        is_scrubbed=True,
        chunk_id=chunk_id,
        source_filename="add_to_memory",
        paragraph_index=0,
        document_type=DOC_TYPE_ADD_TO_MEMORY,
        content_role=CONTENT_ROLE_BODY,
        ingestion_source="runtime",
        content_hash=ch,
        created_at=created,
        doc_id=doc_id,
    )
    from backend.content_based import tagging as content_tagging

    content_tagging.tag_chunks([chunk])
    count = store.ingest_document(
        tenant_id,
        doc_id=doc_id,
        chunks=[chunk],
        tier=TIER_REFERENCE,
        source_filename="add_to_memory",
    )
    return {
        "chunk_id": chunk_id if count else "",
        "deduplicated": count == 0,
        "chunks": count,
        "doc_id": doc_id,
        "document_type": DOC_TYPE_ADD_TO_MEMORY,
        "tier": TIER_REFERENCE,
    }


def list_memory_paragraphs(
    tenant_id: str,
    *,
    subsection_id: str | None = None,
) -> list[dict]:
    """List Add-to-Memory paragraphs from the REFERENCE index only."""
    store = get_rag_store()
    rows = store.list_meta(
        tenant_id,
        TIER_REFERENCE,
        section_id=subsection_id,
    )
    out: list[dict] = []
    for r in rows:
        if not is_add_to_memory_meta(r):
            continue
        sid = str(r.get("section_id") or "")
        out.append(
            {
                "chunk_id": r.get("chunk_id") or "",
                "subsection_id": sid,
                "section_id": r.get("parent_id") or _parent_id(sid),
                "section_name": r.get("section_name") or "",
                "text": r.get("text") or "",
                "ingestion_source": r.get("ingestion_source") or "runtime",
                "document_type": r.get("document_type") or DOC_TYPE_ADD_TO_MEMORY,
                "tier": TIER_REFERENCE,
                "created_at": r.get("created_at") or "",
                "content_hash": r.get("content_hash") or "",
                "doc_id": r.get("doc_id") or "",
                "source_filename": r.get("source_filename") or "add_to_memory",
                "paragraph_index": int(r.get("paragraph_index") or 0),
            }
        )
    return out


def fetch_add_to_memory_for_section(
    tenant_id: str,
    section_id: str,
) -> list:
    """Retrieve Add-to-Memory chunks for one subsection (for prompt injection)."""
    store = get_rag_store()
    return store.fetch_section_chunks(
        tenant_id,
        tier=TIER_REFERENCE,
        section_id=section_id,
        document_type=DOC_TYPE_ADD_TO_MEMORY,
    )


def retrieve_add_to_memory_for_notes(
    tenant_id: str,
    section_id: str,
    observations: list[str],
    *,
    section_label: str = "",
    candidate_ids: list[str] | None = None,
    top_k: int | None = None,
    min_score: float | None = None,
) -> list:
    """Similarity-rank Add-to-Memory paragraphs for one subsection vs notes.

    Past-report hybrid retrieve intentionally excludes ATM from scaffolds; this
    path fetches them explicitly (``document_type=add_to_memory``) via the same
    section-scoped hybrid search (parent-chunk cosine + BM25 RRF) — not the
    general ``search()`` path that builds REFERENCE subchunk windows.
    """
    from backend.config import settings
    from backend.rag.retriever import build_retrieval_query
    from backend.rag.types import SearchHit

    sid = (section_id or "").strip().upper()
    if not sid:
        return []

    ids: list[str] = []
    seen_ids: set[str] = set()
    for raw in [sid, *(candidate_ids or [])]:
        cid = (raw or "").strip().upper()
        if not cid or cid in seen_ids:
            continue
        seen_ids.add(cid)
        ids.append(cid)

    k = int(top_k if top_k is not None else settings.add_to_memory_top_k)
    k = max(1, k)
    floor = float(
        min_score
        if min_score is not None
        else settings.add_to_memory_min_score
    )
    query = build_retrieval_query(
        section_label or sid,
        list(observations or []),
        section_id=sid,
    )
    store = get_rag_store()
    merged: dict[str, SearchHit] = {}
    for cid in ids:
        hits = store.search_section_scoped_hybrid(
            tenant_id,
            query,
            tier=TIER_REFERENCE,
            section_id=cid,
            top_k=k,
            document_type=DOC_TYPE_ADD_TO_MEMORY,
        )
        for hit in hits or []:
            if not isinstance(hit, SearchHit):
                continue
            text = (hit.text or "").strip()
            if not text:
                continue
            score = float(
                hit.fusion_score
                or hit.rerank_score
                or hit.similarity_score
                or hit.score
                or 0.0
            )
            if score < floor:
                continue
            key = (hit.chunk_id or hit.content_hash or text).strip()
            if not key:
                continue
            prev = merged.get(key)
            prev_score = (
                float(
                    prev.fusion_score
                    or prev.rerank_score
                    or prev.similarity_score
                    or prev.score
                    or 0.0
                )
                if prev is not None
                else -1.0
            )
            if prev is None or score > prev_score:
                merged[key] = hit

    ranked = sorted(
        merged.values(),
        key=lambda h: float(
            h.fusion_score
            or h.rerank_score
            or h.similarity_score
            or h.score
            or 0.0
        ),
        reverse=True,
    )
    return ranked[:k]


def build_word_extraction_payload(
    discovered: list,
    *,
    source_filename: str,
    document_id: str,
) -> dict:
    """Group discovered Word chunks into a debugable section/subsection JSON.

    Shape mirrors ``grouped_responses_full.json`` so operators can spot mis-assigned
    subsections before relying on FAISS retrieval.
    """
    # Preserve discovery order while grouping.
    by_parent: dict[str, dict] = {}
    parent_order: list[str] = []
    sub_order: dict[str, list[str]] = {}

    for dc in discovered:
        sid = str(getattr(dc, "section_id", "") or "").strip()
        if not sid:
            continue
        parent = str(getattr(dc, "parent_id", "") or "").strip() or _parent_id(sid)
        sname = str(getattr(dc, "section_name", "") or sid)
        text = str(getattr(dc, "text", "") or "").strip()
        if not text:
            continue
        pidx = int(getattr(dc, "paragraph_index", 0) or 0)

        if parent not in by_parent:
            by_parent[parent] = {
                "section_id": parent,
                "section_name": parent,
                "subsections": {},
            }
            parent_order.append(parent)
            sub_order[parent] = []

        subs = by_parent[parent]["subsections"]
        if sid not in subs:
            subs[sid] = {
                "section_id": parent,
                "subsection_id": sid,
                "subsection_name": sname,
                "standard_paragraphs": [],
            }
            sub_order[parent].append(sid)
        elif sname and not subs[sid].get("subsection_name"):
            subs[sid]["subsection_name"] = sname

        subs[sid]["standard_paragraphs"].append(
            {
                "label": "",
                "text": text,
                "paragraph_index": pidx,
            }
        )

    sections_out = []
    total_sps = 0
    total_subs = 0
    for parent in parent_order:
        sec = by_parent[parent]
        sub_list = []
        for sid in sub_order[parent]:
            entry = sec["subsections"][sid]
            total_sps += len(entry["standard_paragraphs"])
            total_subs += 1
            sub_list.append(entry)
        sections_out.append(
            {
                "section_id": sec["section_id"],
                "section_name": sec["section_name"],
                "subsections": sub_list,
            }
        )

    return {
        "source": source_filename,
        "document_id": document_id,
        "extracted_at": _utcnow_iso(),
        "stats": {
            "sections": len(sections_out),
            "subsections": total_subs,
            "standard_paragraphs": total_sps,
        },
        "sections": sections_out,
    }


def write_word_extraction_json(
    tenant_id: str,
    document_id: str,
    payload: dict,
) -> Path:
    """Persist extraction debug JSON under ``standard_paragraph_extracts/``."""
    import json

    path = tenant_store.standard_paragraph_extract_json_path(tenant_id, document_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info(
        "Wrote SP extraction JSON tenant=%s doc=%s path=%s sps=%s",
        tenant_id,
        document_id,
        path,
        (payload.get("stats") or {}).get("standard_paragraphs"),
    )
    return path


def ingest_from_word(
    tenant_id: str,
    path: Path,
    *,
    document_id: str | None = None,
    source_filename: str | None = None,
    ingestion_source: IngestionSource = "upload",
    replace_all: bool = False,
    blob_key: str = "",
    update_schema_aliases: bool = False,
) -> dict:
    """Parse a Word or PDF standard-paragraphs file and ingest into FAISS.

    Always writes an extraction debug JSON (section → subsection → paragraphs)
    before embedding, so mis-mapped headings are inspectable on disk.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Standard paragraphs file not found: {path}")

    suffix = path.suffix.lower()
    if suffix not in {".docx", ".docm", ".doc", ".pdf"}:
        raise ValueError(
            f"Unsupported standard-paragraphs type '{suffix}'. "
            "Allowed: .docx, .docm, .doc, .pdf"
        )

    label = source_filename or path.name
    full_text = path.read_bytes()  # existence check; PII on extracted text
    del full_text

    from backend.ingest import doc_extractor

    extracted = doc_extractor.extract_text(path)
    pii_scrubber.assert_no_pii(extracted, context=f"standard paragraphs {label}")

    discovered = template_discoverer.discover_standard_paragraph_chunks(path)
    doc_id = document_id or f"paragraphs:{uuid.uuid4().hex[:12]}"

    extraction_payload = build_word_extraction_payload(
        discovered,
        source_filename=label,
        document_id=doc_id,
    )
    extraction_path = write_word_extraction_json(
        tenant_id, doc_id, extraction_payload
    )

    items = [
        {
            "text": dc.text,
            "section_id": dc.section_id,
            "section_name": getattr(dc, "section_name", "") or "",
            "parent_id": getattr(dc, "parent_id", "") or _parent_id(dc.section_id),
            "paragraph_index": int(getattr(dc, "paragraph_index", 0) or 0),
        }
        for dc in discovered
    ]
    result = ingest_paragraphs(
        tenant_id,
        items,
        doc_id=doc_id,
        source_filename=label,
        ingestion_source=ingestion_source,
        replace_all=replace_all,
        blob_key=blob_key,
    )

    if update_schema_aliases:
        schema = template_discoverer.load_schema(tenant_id)
        if schema is not None:
            schema.standard_paragraphs_source = label
            ptitles = section_bridge.paragraph_titles_from_word(path)
            schema.paragraph_section_titles = ptitles
            schema.section_alias_map = section_bridge.build_section_alias_map(
                schema.sections, ptitles
            )
            template_discoverer.save_schema(tenant_id, schema)

    result["standard_paragraphs"] = label
    result["discovered"] = len(discovered)
    result["extraction_json"] = str(extraction_path)
    result["extraction_stats"] = extraction_payload.get("stats") or {}
    return result


# Backward-compatible alias — Word and PDF use the same ingest path.
ingest_from_document = ingest_from_word


def list_paragraphs(
    tenant_id: str,
    *,
    subsection_id: str | None = None,
) -> list[dict]:
    """List firm SP catalogue chunks plus Add-to-Memory rows.

    Word/operator standard paragraphs remain on the SP tier; Add-to-Memory
    rows are read from REFERENCE filtered by ``document_type=add_to_memory``.
    """
    store = get_rag_store()
    rows = store.list_meta(
        tenant_id,
        TIER_STANDARD_PARAGRAPHS,
        section_id=subsection_id,
    )
    out: list[dict] = []
    for r in rows:
        sid = str(r.get("section_id") or "")
        out.append(
            {
                "chunk_id": r.get("chunk_id") or "",
                "subsection_id": sid,
                "section_id": r.get("parent_id") or _parent_id(sid),
                "section_name": r.get("section_name") or "",
                "text": r.get("text") or "",
                "ingestion_source": r.get("ingestion_source") or "",
                "document_type": r.get("document_type") or "",
                "tier": TIER_STANDARD_PARAGRAPHS,
                "created_at": r.get("created_at") or "",
                "content_hash": r.get("content_hash") or "",
                "doc_id": r.get("doc_id") or "",
                "source_filename": r.get("source_filename") or "",
                "paragraph_index": int(r.get("paragraph_index") or 0),
            }
        )
    out.extend(list_memory_paragraphs(tenant_id, subsection_id=subsection_id))
    return out


def remove_chunk(tenant_id: str, chunk_id: str) -> int:
    """Remove a chunk from SP catalogue or Add-to-Memory (REFERENCE)."""
    store = get_rag_store()
    removed = store.remove_chunks_by_ids(
        tenant_id, TIER_STANDARD_PARAGRAPHS, [chunk_id]
    )
    if removed:
        return removed
    return store.remove_chunks_by_ids(tenant_id, TIER_REFERENCE, [chunk_id])


def remove_document_paragraphs(tenant_id: str, document_id: str) -> int:
    store = get_rag_store()
    removed = store.remove_document(
        tenant_id,
        TIER_STANDARD_PARAGRAPHS,
        doc_id=document_id,
    )
    if removed:
        return removed
    # runtime:* Add-to-Memory docs live on REFERENCE.
    return store.remove_document(
        tenant_id,
        TIER_REFERENCE,
        doc_id=document_id,
    )


def operator_ingest_word(tenant_id: str, path: Path) -> dict:
    """Operator/full replace seed used by startup and admin."""
    return ingest_from_word(
        tenant_id,
        path,
        document_id=f"paragraphs:{path.name}",
        source_filename=path.name,
        ingestion_source="operator",
        replace_all=True,
        update_schema_aliases=True,
    )


def flatten_grouped_responses_json(payload: dict) -> list[dict]:
    """Flatten ``grouped_responses_full.json`` into ingest items.

    Each catalogue response becomes one chunk. ``subsection_id`` is the FAISS
    ``section_id`` (e.g. ``D1`` or ``field_264``). Labels are prefixed onto the
    embedded text so variant names participate in similarity search.
    """
    items: list[dict] = []
    sections = payload.get("sections") or []
    idx = 0
    for sec in sections:
        parent = str(sec.get("section_id") or "").strip().upper()
        for sub in sec.get("subsections") or []:
            sid = str(sub.get("subsection_id") or "").strip()
            if not sid:
                continue
            sname = str(sub.get("subsection_name") or sid)
            parent_id = str(sub.get("section_id") or parent or _parent_id(sid))
            for sp in sub.get("standard_paragraphs") or []:
                body = str(sp.get("text") or "").strip()
                if not body:
                    continue
                label = str(sp.get("label") or "").strip()
                text = f"{label}. {body}" if label else body
                items.append(
                    {
                        "text": text,
                        "section_id": sid,
                        "section_name": sname,
                        "parent_id": parent_id,
                        "paragraph_index": idx,
                        "chunk_id": "",  # assigned at ingest
                    }
                )
                idx += 1
    return items


def ingest_from_grouped_json(
    tenant_id: str,
    path: Path,
    *,
    document_id: str | None = None,
    source_filename: str | None = None,
    ingestion_source: IngestionSource = "operator",
    replace_document: bool = True,
    batch_size: int = 64,
) -> dict:
    """Embed a grouped-responses JSON export into the standard_paragraphs tier.

    Replaces any prior chunks for the same ``document_id`` (default
    ``json:<filename>``) so re-running is idempotent without wiping runtime
    Add-to-Memory chunks.
    """
    import json

    if not path.is_file():
        raise FileNotFoundError(f"Grouped responses JSON not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Grouped responses JSON must be an object")

    items = flatten_grouped_responses_json(payload)
    label = source_filename or path.name
    doc_id = document_id or f"json:{path.stem}"

    if replace_document:
        remove_document_paragraphs(tenant_id, doc_id)

    total_chunks = 0
    total_deduped = 0
    total_attempted = 0
    bs = max(1, int(batch_size))
    for start in range(0, len(items), bs):
        batch = items[start : start + bs]
        for i, it in enumerate(batch):
            it["chunk_id"] = f"{doc_id}:{start + i}"
            it["paragraph_index"] = start + i
        result = ingest_paragraphs(
            tenant_id,
            batch,
            doc_id=doc_id,
            source_filename=label,
            ingestion_source=ingestion_source,
            replace_all=False,
        )
        total_chunks += int(result.get("chunks") or 0)
        total_deduped += int(result.get("deduplicated") or 0)
        total_attempted += int(result.get("attempted") or len(batch))
        logger.info(
            "Grouped JSON ingest batch %d-%d: +%s chunks (tenant=%s doc=%s)",
            start,
            start + len(batch) - 1,
            result.get("chunks"),
            tenant_id,
            doc_id,
        )

    return {
        "chunks": total_chunks,
        "deduplicated": total_deduped,
        "attempted": total_attempted,
        "discovered": len(items),
        "doc_id": doc_id,
        "standard_paragraphs": label,
        "source": payload.get("source") or label,
    }
