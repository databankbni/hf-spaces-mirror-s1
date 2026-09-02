"""Per-tenant, two-tier FAISS vector store.

Tiers:

* ``TIER_STANDARD_PARAGRAPHS`` (legacy alias ``TIER_MASTER``) — firm/user standard
  paragraph memory. **Not** scrubbed at ingest (property-agnostic boilerplate);
  carries approved wording for the standard-paragraph generation path.
* ``TIER_REFERENCE`` — past completed reports. **Always** scrubbed at ingest;
  used only for style/terminology. A read-time scrub backstop guards against any
  chunk that slipped through unscrubbed.

Each (tenant, tier) pair is an independent ``IndexFlatIP`` over L2-normalised
embeddings (so inner product == cosine similarity), persisted to disk alongside a
JSON metadata sidecar.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from backend.config import settings
from backend.llm.embeddings import Embedder, get_embedder
from backend.pii import scrubber as pii_scrubber
from backend.rag import lexical_index
from backend.rag.reference_filter import (
    build_reference_allowlist,
    meta_matches_allowlist,
)
from backend.rag.types import (
    CONTENT_ROLE_BODY,
    CONTENT_ROLE_PARENT_INTRO,
    TIER_MASTER,
    TIER_REFERENCE,
    TIER_STANDARD_PARAGRAPHS,
    Chunk,
    SearchHit,
)
from backend.domain.section_scope import PARENT_INTRO_SECTION_IDS
from backend.storage import tenant_store

logger = logging.getLogger(__name__)


# Coarse document-type tags for metadata filtering. Reference past-reports are
# tagged at ingest; other producers may set their own value (default "" = untyped,
# which the optional retrieval filter never excludes).
DOC_TYPE_REFERENCE_REPORT = "reference_report"
# UI "Add to Memory" paragraphs live in the REFERENCE FAISS index alongside
# past reports, distinguished by this document_type for filtered retrieve.
DOC_TYPE_ADD_TO_MEMORY = "add_to_memory"


def is_add_to_memory_meta(meta: dict | None) -> bool:
    """True when a meta row is an Add-to-Memory chunk (not a past report)."""
    if not meta:
        return False
    return (meta.get("document_type") or "").strip() == DOC_TYPE_ADD_TO_MEMORY


def _meta_matches_section(meta: dict, section_id: str) -> bool:
    """True when a FAISS row belongs to this mapping unit.

    Parent-intro chunks are stored as ``section_id`` = D…J. Legacy rows may only
    have ``content_role=parent_intro`` + ``parent_id``; treat those as the parent
    unit so already-ingested reports still retrieve.
    """
    sid = (section_id or "").strip().upper()
    if not sid:
        return False
    row_sid = str(meta.get("section_id") or "").strip().upper()
    if row_sid == sid:
        return True
    if sid not in PARENT_INTRO_SECTION_IDS:
        return False
    role = (meta.get("content_role") or CONTENT_ROLE_BODY).strip().lower()
    parent = str(meta.get("parent_id") or "").strip().upper()
    return role == CONTENT_ROLE_PARENT_INTRO and parent == sid


def _dedupe_key(section_id: str, text: str) -> tuple[str, str]:
    """Identity for duplicate detection: (upper section id, whitespace-normalised text).

    Whitespace normalisation collapses runs of spaces/newlines so chunks that
    differ only in formatting are still recognised as the same content.
    """
    norm = re.sub(r"\s+", " ", (text or "")).strip()
    return ((section_id or "").strip().upper(), norm)


def _subchunk_text(text: str, *, words: int, overlap: int) -> list[str]:
    """Split ``text`` into overlapping whitespace-token windows.

    Short chunks (<= ``words`` tokens) return a single window equal to the
    original, so the subchunk view degrades to the parent embedding for content
    that already fits inside the model window — no behaviour change there.
    """
    toks = (text or "").split()
    if len(toks) <= words:
        return [text] if text else []
    step = max(1, words - overlap)
    out: list[str] = []
    for start in range(0, len(toks), step):
        out.append(" ".join(toks[start : start + words]))
        if start + words >= len(toks):
            break
    return out


def _meta_row_matches_document(
    row: dict,
    *,
    source_filename: str | None = None,
    doc_id: str | None = None,
) -> bool:
    """True when a meta / chunks-only row belongs to the given upload identity."""
    sf = str(row.get("source_filename") or "").strip()
    did = str(row.get("doc_id") or "").strip()
    if source_filename and sf == source_filename:
        return True
    if doc_id and did == doc_id:
        return True
    if source_filename and did == f"reference:{source_filename}":
        return True
    return False


def _theme_tags_from_meta(meta: dict) -> list[str]:
    """Read a row's theme tags, tolerating rows written before tags existed."""
    raw = meta.get("theme_tags")
    if not raw:
        return []
    from backend.content_based.taxonomy import normalize_theme_tags

    return normalize_theme_tags(raw)


def _search_hit_from_meta(
    meta: dict,
    *,
    tier: str,
    rank: float,
    text: str,
) -> SearchHit:
    return SearchHit(
        text=text,
        section_id=meta.get("section_id", ""),
        doc_id=meta.get("doc_id", ""),
        tier=tier,
        score=rank,
        is_scrubbed=bool(meta.get("is_scrubbed")),
        source_filename=meta.get("source_filename", ""),
        paragraph_index=int(meta.get("paragraph_index") or 0),
        chunk_id=meta.get("chunk_id", ""),
        document_type=meta.get("document_type", ""),
        property_type=str(meta.get("property_type") or ""),
        content_role=str(meta.get("content_role") or CONTENT_ROLE_BODY),
        parent_id=str(meta.get("parent_id") or ""),
        section_name=str(meta.get("section_name") or ""),
        ingestion_source=str(meta.get("ingestion_source") or ""),
        content_hash=str(meta.get("content_hash") or ""),
        topic_id=str(meta.get("topic_id") or ""),
        subtopic_id=str(meta.get("subtopic_id") or ""),
        theme_tags=_theme_tags_from_meta(meta),
        taxonomy_version=str(meta.get("taxonomy_version") or ""),
    )


@dataclass
class _TierIndex:
    index: object  # faiss.IndexFlatIP
    meta: list[dict] = field(default_factory=list)
    # Sparse (BM25) arm of hybrid retrieval, lazily built from ``meta`` and
    # rebuilt when its length changes. ``bm25_n`` records the meta length the
    # current index was built for.
    bm25: object | None = None
    bm25_n: int = -1
    # Small-to-big dense view (REFERENCE tier only): a matrix of L2-normalised
    # sub-window embeddings with a parallel parent-index pointer. Lazily built
    # from ``meta`` and rebuilt when its length changes, mirroring the BM25 arm.
    sub_vecs: object | None = None  # np.ndarray (n_sub, dim) | None
    sub_parent: object | None = None  # np.ndarray (n_sub,) int32 | None
    sub_n: int = -1


class RagStore:
    """Lazy, thread-safe per-tenant/tier FAISS store."""

    def __init__(self, embedder: Embedder | None = None) -> None:
        self._embedder = embedder or get_embedder()
        self._cache: dict[tuple[str, str], _TierIndex] = {}
        self._lock = threading.RLock()

    # ── persistence ──────────────────────────────────────────────────────────
    def _paths(self, tenant_id: str, tier: str) -> tuple[Path, Path]:
        d = tenant_store.faiss_dir(tenant_id, tier)
        return d / "index.faiss", d / "meta.json"

    def _chunks_only_path(self, tenant_id: str, tier: str) -> Path:
        """Sidecar for documents that were chunked/scrubbed but not embedded."""
        return tenant_store.faiss_dir(tenant_id, tier) / "chunks_only.json"

    def _load_chunks_only(self, tenant_id: str, tier: str) -> dict[str, list[dict]]:
        path = self._chunks_only_path(tenant_id, tier)
        if not path.is_file():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Could not read chunks-only sidecar %s", path)
            return {}
        if not isinstance(raw, dict):
            return {}
        out: dict[str, list[dict]] = {}
        for key, rows in raw.items():
            if isinstance(rows, list):
                out[str(key)] = [r for r in rows if isinstance(r, dict)]
        return out

    def _save_chunks_only(
        self, tenant_id: str, tier: str, data: dict[str, list[dict]]
    ) -> None:
        path = self._chunks_only_path(tenant_id, tier)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _drop_chunks_only_source(
        self,
        tenant_id: str,
        tier: str,
        *,
        source_filename: str | None = None,
        doc_id: str | None = None,
    ) -> int:
        """Remove one document's rows from the chunks-only sidecar. Returns rows dropped."""
        data = self._load_chunks_only(tenant_id, tier)
        if not data:
            return 0
        names = {n for n in (source_filename or "",) if n}
        if doc_id and doc_id.startswith("reference:"):
            names.add(doc_id.split(":", 1)[-1])
        if source_filename:
            names.add(source_filename)
        removed = 0
        for name in list(names):
            if name in data:
                removed += len(data.pop(name))
        if removed:
            self._save_chunks_only(tenant_id, tier, data)
        return removed

    def _new_index(self):
        import faiss

        return faiss.IndexFlatIP(self._embedder.embed_dim)

    def _load(self, tenant_id: str, tier: str) -> _TierIndex:
        import faiss

        idx_path, meta_path = self._paths(tenant_id, tier)
        if idx_path.is_file() and meta_path.is_file():
            try:
                # io_flags=0: load into RAM (avoid mmap — Windows cannot replace mmap'd files).
                index = faiss.read_index(str(idx_path), 0)
                # Guard against an embedder dimension change (e.g. MiniLM 384 →
                # jina-embeddings-v3 1024): a stale index would assert-fail the
                # moment it is searched/appended. Discard it so the tier rebuilds
                # empty and re-ingests at the current dimension.
                expected_dim = int(self._embedder.embed_dim)
                if int(index.d) != expected_dim:
                    logger.warning(
                        "FAISS %s/%s dim %d != embedder %d; discarding stale index.",
                        tenant_id,
                        tier,
                        int(index.d),
                        expected_dim,
                    )
                    return _TierIndex(index=self._new_index(), meta=[])
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                return _TierIndex(index=index, meta=meta)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to load FAISS %s/%s (%s); rebuilding empty.",
                    tenant_id,
                    tier,
                    exc,
                )
        return _TierIndex(index=self._new_index(), meta=[])

    def _persist(self, tenant_id: str, tier: str, ti: _TierIndex) -> None:
        import os
        import tempfile

        import faiss

        from backend.utils.runtime_paths import ensure_data_drive_runtime_dirs

        ensure_data_drive_runtime_dirs()

        idx_path, meta_path = self._paths(tenant_id, tier)
        idx_path = idx_path.resolve()
        meta_path = meta_path.resolve()
        idx_path.parent.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(ti.meta, ensure_ascii=False, separators=(",", ":"))
        scratch_root = settings.data_dir_path / "tmp" / "faiss_persist"
        scratch_root.mkdir(parents=True, exist_ok=True)

        def _atomic_write() -> None:
            with tempfile.TemporaryDirectory(
                prefix="faiss_", dir=str(scratch_root)
            ) as td:
                tmp_dir = Path(td)
                tmp_idx = tmp_dir / "index.faiss"
                tmp_meta = tmp_dir / "meta.json"
                faiss.write_index(ti.index, os.fspath(tmp_idx))
                tmp_meta.write_text(payload, encoding="utf-8")
                for final, tmp in ((idx_path, tmp_idx), (meta_path, tmp_meta)):
                    final_s = os.fspath(final)
                    tmp_s = os.fspath(tmp)
                    if os.path.exists(final_s):
                        os.remove(final_s)
                    os.replace(tmp_s, final_s)

        try:
            _atomic_write()
        except OSError as exc:
            logger.error(
                "FAISS persist failed for %s/%s (%s); quarantining and retrying once.",
                tenant_id,
                tier,
                exc,
            )
            for stale in idx_path.parent.glob("*.write.*"):
                stale.unlink(missing_ok=True)
            for final in (idx_path, meta_path):
                if final.is_file():
                    bad = final.with_suffix(final.suffix + ".bad")
                    if bad.is_file():
                        bad.unlink(missing_ok=True)
                    os.replace(os.fspath(final), os.fspath(bad))
            _atomic_write()

    def _get(self, tenant_id: str, tier: str) -> _TierIndex:
        key = (tenant_id, tier)
        with self._lock:
            if key not in self._cache:
                self._cache[key] = self._load(tenant_id, tier)
            return self._cache[key]

    def _get_bm25(self, ti: _TierIndex) -> lexical_index.BM25Index:
        """Lazily build (and cache) the sparse BM25 arm for a tier index."""
        with self._lock:
            if ti.bm25 is None or ti.bm25_n != len(ti.meta):
                corpus = [lexical_index.tokenize(m.get("text", "")) for m in ti.meta]
                ti.bm25 = lexical_index.BM25Index(
                    corpus,
                    k1=settings.hybrid_bm25_k1,
                    b=settings.hybrid_bm25_b,
                )
                ti.bm25_n = len(ti.meta)
            return ti.bm25

    def _cosine_for(self, ti: _TierIndex, i: int, qvec: np.ndarray) -> float:
        """Cosine of doc ``i`` against the query for sparse-only fusion hits.

        Embeddings are L2-normalised, so the dot product of the reconstructed
        stored vector with the (also normalised) query vector is the cosine.
        """
        try:
            vec = ti.index.reconstruct(int(i))
            return float(np.dot(qvec[0], np.asarray(vec, dtype="float32")))
        except Exception:  # noqa: BLE001 - degrade to neutral if reconstruct fails
            return 0.0

    def _get_subchunk_view(
        self, ti: _TierIndex
    ) -> tuple[np.ndarray, np.ndarray] | None:
        """Lazily build (and cache) the small-to-big dense view for a tier.

        Each parent chunk is split into overlapping sub-windows that fit inside
        the embedder's token window; every window is embedded once. Rebuilt when
        ``meta`` length changes, mirroring the BM25 arm. Returns ``None`` when the
        tier is empty so callers fall back to the parent-FAISS dense arm.
        """
        with self._lock:
            if ti.sub_vecs is None or ti.sub_n != len(ti.meta):
                sub_texts: list[str] = []
                parents: list[int] = []
                for pi, m in enumerate(ti.meta):
                    for s in _subchunk_text(
                        m.get("text", ""),
                        words=settings.reference_subchunk_words,
                        overlap=settings.reference_subchunk_overlap,
                    ):
                        if s.strip():
                            sub_texts.append(s)
                            parents.append(pi)
                dim = int(self._embedder.embed_dim)
                if sub_texts:
                    # Embed in bounded batches straight into a preallocated matrix.
                    # Embedding all windows in one call round-trips every vector
                    # through a Python list, spiking host RAM on large tiers (the
                    # cause of the OOM abort); batching keeps peak memory flat.
                    out = np.empty((len(sub_texts), dim), dtype="float32")
                    bs = max(16, int(settings.reference_subchunk_embed_batch))
                    for start in range(0, len(sub_texts), bs):
                        block = sub_texts[start : start + bs]
                        vecs = self._embedder.embed_documents(block)
                        out[start : start + len(block)] = np.asarray(
                            vecs, dtype="float32"
                        )
                    ti.sub_vecs = out
                    ti.sub_parent = np.asarray(parents, dtype="int32")
                else:
                    ti.sub_vecs = np.zeros((0, dim), dtype="float32")
                    ti.sub_parent = np.zeros((0,), dtype="int32")
                ti.sub_n = len(ti.meta)
                logger.info(
                    "Built subchunk view: %d parents -> %d sub-windows (batch=%d)",
                    len(ti.meta),
                    int(ti.sub_parent.shape[0]),
                    max(16, int(settings.reference_subchunk_embed_batch)),
                )
            if ti.sub_parent is None or ti.sub_parent.shape[0] == 0:
                return None
            return ti.sub_vecs, ti.sub_parent

    def _subchunk_dense_order(
        self, ti: _TierIndex, qvec: np.ndarray, k: int
    ) -> tuple[list[int], dict[int, float]]:
        """Parent-level dense ranking from the best sub-window per parent.

        Returns ``(dense_order, cosine_by_i)`` where ``cosine_by_i`` covers ALL
        parents (so sparse-only fusion hits resolve their cosine here instead of
        the head-biased reconstruct path), and ``dense_order`` is the top-``k``
        parents by best-window cosine.
        """
        view = self._get_subchunk_view(ti)
        if view is None:
            return [], {}
        sub_vecs, sub_parent = view
        sims = sub_vecs @ qvec[0]
        n_parents = len(ti.meta)
        best = np.full(n_parents, -1.0e9, dtype="float32")
        np.maximum.at(best, sub_parent, sims)
        valid = np.where(best > -1.0e8)[0]
        order = valid[np.argsort(-best[valid])]
        dense_order = [int(i) for i in order[:k]]
        cosine_by_i = {int(i): float(best[i]) for i in valid}
        return dense_order, cosine_by_i

    # ── ingest ─────────────────────────────────────────────────────────────--
    def ingest_document(
        self,
        tenant_id: str,
        doc_id: str,
        chunks: list[Chunk],
        *,
        tier: str,
        source_filename: str = "",
    ) -> int:
        """Embed and add chunks. REFERENCE-tier chunks are PII-scrubbed before storage.

        Duplicate chunks (same section + normalised text as one already in the tier
        or seen earlier in this batch) are dropped BEFORE scrubbing/embedding when
        ``dedupe_chunks_on_ingest`` is set, so they are never processed or stored.
        """
        prepared: list[Chunk] = []

        dedupe = bool(settings.dedupe_chunks_on_ingest)
        # Seed the seen-set with what is already stored so re-ingesting the same
        # file is a no-op rather than a duplication. Snapshot under the lock.
        seen_keys: set[tuple[str, str]] = set()
        if dedupe:
            with self._lock:
                for m in self._get(tenant_id, tier).meta:
                    seen_keys.add(
                        _dedupe_key(m.get("section_id", ""), m.get("text", ""))
                    )
        skipped_dupes = 0

        # One session per document so the same name/address/reference is masked
        # to one stable token across every chunk of this file (referential
        # integrity), while distinct values remain distinguishable.
        scrub_session = pii_scrubber.ScrubSession() if tier == TIER_REFERENCE else None
        # Document-level scrub audit (redacted content + redaction manifest).
        from backend.pii import audit as pii_scrub_audit

        audit_doc = (
            pii_scrub_audit.start_document(
                tenant_id=tenant_id,
                doc_id=doc_id,
                source_filename=source_filename,
            )
            if tier == TIER_REFERENCE
            else None
        )
        for c in chunks:
            text = c.text or ""
            # Pre-scrub raw guard: skip exact in-batch repeats before doing any
            # scrubbing work (the cheapest place to drop an obvious duplicate).
            if dedupe and _dedupe_key(c.section_id, text) in seen_keys:
                skipped_dupes += 1
                continue
            scrubbed = c.is_scrubbed
            if tier == TIER_REFERENCE and not scrubbed:
                outcome = pii_scrubber.scrub_reference_for_ingest(
                    text, session=scrub_session
                )
                if audit_doc is not None:
                    audit_doc.add_chunk(
                        section_id=c.section_id or "",
                        paragraph_index=int(c.paragraph_index or 0),
                        chunk_id=c.chunk_id or "",
                        redacted_text=outcome.cleaned_text,
                        redactions=outcome.redactions,
                        whitelisted=outcome.whitelisted,
                        dropped=outcome.dropped,
                        residual_leaks=outcome.residual_leaks,
                    )
                if outcome.result is None:
                    logger.warning(
                        "Skipping REFERENCE chunk from %s (PII could not be fully redacted)",
                        doc_id,
                    )
                    continue
                text = outcome.result.text
                scrubbed = True
            if not text.strip():
                continue
            # Post-scrub guard: catches dupes whose scrubbed form collides and any
            # raw form that survived scrubbing unchanged.
            if dedupe:
                key = _dedupe_key(c.section_id, text)
                if key in seen_keys:
                    skipped_dupes += 1
                    continue
                seen_keys.add(key)
            prepared.append(
                Chunk(
                    text=text,
                    section_id=c.section_id,
                    doc_id=c.doc_id or doc_id,
                    tier=tier,
                    is_scrubbed=scrubbed,
                    chunk_id=c.chunk_id,
                    source_filename=c.source_filename or source_filename,
                    paragraph_index=c.paragraph_index,
                    document_type=c.document_type,
                    property_type=c.property_type or "",
                    content_role=c.content_role or CONTENT_ROLE_BODY,
                    parent_id=c.parent_id or "",
                    section_name=c.section_name or "",
                    ingestion_source=c.ingestion_source or "",
                    content_hash=c.content_hash or "",
                    created_at=c.created_at or "",
                    blob_key=c.blob_key or "",
                    topic_id=c.topic_id or "",
                    subtopic_id=c.subtopic_id or "",
                    theme_tags=list(c.theme_tags or []),
                    taxonomy_version=c.taxonomy_version or "",
                )
            )
        # Emit the document-level scrub audit (redacted content + manifest) even
        # when every chunk was dropped, so a fully-redacted document is still visible.
        if audit_doc is not None:
            audit_doc.write()

        if not prepared:
            if skipped_dupes:
                logger.info(
                    "Ingested 0 chunks into %s/%s (doc=%s); skipped %d duplicate(s)",
                    tenant_id,
                    tier,
                    doc_id,
                    skipped_dupes,
                )
            return 0

        src = source_filename or doc_id.split(":", 1)[-1]
        meta_rows: list[dict] = []
        for i, c in enumerate(prepared):
            cid = c.chunk_id or f"{doc_id}:{i}"
            row_src = c.source_filename or src
            meta_rows.append(
                {
                    "text": c.text,
                    "paragraph_text": c.text,
                    "section_id": c.section_id,
                    "doc_id": c.doc_id or doc_id,
                    "tier": tier,
                    "is_scrubbed": c.is_scrubbed,
                    "chunk_id": cid,
                    "source_filename": row_src,
                    "paragraph_index": c.paragraph_index or 0,
                    "document_type": c.document_type or "",
                    "property_type": c.property_type or "",
                    "content_role": c.content_role or CONTENT_ROLE_BODY,
                    "parent_id": c.parent_id or "",
                    "section_name": c.section_name or "",
                    "ingestion_source": c.ingestion_source or "",
                    "content_hash": c.content_hash or "",
                    "created_at": c.created_at or "",
                    "blob_key": c.blob_key or "",
                    "topic_id": c.topic_id or "",
                    "subtopic_id": c.subtopic_id or "",
                    "theme_tags": list(c.theme_tags or []),
                    "taxonomy_version": c.taxonomy_version or "",
                }
            )

        # Chunk-only mode: scrub + persist text, skip FAISS / embedder cost.
        if not settings.ingest_embed_enabled:
            with self._lock:
                data = self._load_chunks_only(tenant_id, tier)
                data[src] = meta_rows
                self._save_chunks_only(tenant_id, tier, data)
            logger.info(
                "Chunk-only ingest (embed off): %d chunks for %s/%s (doc=%s); "
                "skipped %d duplicate(s)",
                len(prepared),
                tenant_id,
                tier,
                doc_id,
                skipped_dupes,
            )
            return len(prepared)

        # Full embed path — drop any prior chunk-only rows for this source.
        self._drop_chunks_only_source(
            tenant_id, tier, source_filename=src, doc_id=doc_id
        )
        vecs = self._embedder.embed_documents([c.text for c in prepared])
        arr = np.asarray(vecs, dtype="float32")
        with self._lock:
            ti = self._get(tenant_id, tier)
            ti.index.add(arr)
            base = len(ti.meta)
            for i, row in enumerate(meta_rows):
                row = dict(row)
                if not prepared[i].chunk_id:
                    row["chunk_id"] = f"{doc_id}:{base + i}"
                ti.meta.append(row)
            self._persist(tenant_id, tier, ti)
        logger.info(
            "Ingested %d chunks into %s/%s (doc=%s); skipped %d duplicate(s)",
            len(prepared),
            tenant_id,
            tier,
            doc_id,
            skipped_dupes,
        )
        return len(prepared)

    def clear_tier(self, tenant_id: str, tier: str) -> None:
        """Drop all vectors for a (tenant, tier) — used by admin override."""
        with self._lock:
            ti = _TierIndex(index=self._new_index(), meta=[])
            self._cache[(tenant_id, tier)] = ti
            self._persist(tenant_id, tier, ti)
            path = self._chunks_only_path(tenant_id, tier)
            if path.is_file():
                path.unlink(missing_ok=True)

    def evict_tier_cache(self, tenant_id: str, tier: str) -> None:
        """Drop in-memory index without persisting (used before disk purge)."""
        with self._lock:
            self._cache.pop((tenant_id, tier), None)

    def remove_document(
        self,
        tenant_id: str,
        tier: str,
        *,
        source_filename: str | None = None,
        doc_id: str | None = None,
    ) -> int:
        """Drop all chunks for a reference upload and rebuild the FAISS index."""
        if not source_filename and not doc_id:
            return 0

        with self._lock:
            ti = self._get(tenant_id, tier)
            kept: list[dict] = []
            removed = 0
            for row in ti.meta:
                if _meta_row_matches_document(
                    row, source_filename=source_filename, doc_id=doc_id
                ):
                    removed += 1
                else:
                    kept.append(row)

            if removed == 0:
                removed = self._drop_chunks_only_source(
                    tenant_id,
                    tier,
                    source_filename=source_filename,
                    doc_id=doc_id,
                )
                return removed

            if not kept:
                ti = _TierIndex(index=self._new_index(), meta=[])
            else:
                texts = [r["text"] for r in kept]
                vecs = self._embedder.embed_documents(texts)
                arr = np.asarray(vecs, dtype="float32")
                index = self._new_index()
                index.add(arr)
                ti = _TierIndex(index=index, meta=kept)

            self._cache[(tenant_id, tier)] = ti
            self._persist(tenant_id, tier, ti)
            self._drop_chunks_only_source(
                tenant_id,
                tier,
                source_filename=source_filename,
                doc_id=doc_id,
            )
            logger.info(
                "Removed %d chunk(s) from tenant=%s tier=%s (source=%s doc_id=%s)",
                removed,
                tenant_id,
                tier,
                source_filename,
                doc_id,
            )
            return removed

    def update_document_property_type(
        self,
        tenant_id: str,
        tier: str,
        *,
        property_type: str,
        source_filename: str | None = None,
        doc_id: str | None = None,
    ) -> int:
        """Stamp ``property_type`` onto matching chunk meta without re-embedding.

        Updates in-memory FAISS meta (and the chunks-only sidecar when present),
        then persists. The vector index is rewritten from the existing index
        object — embeddings are not recomputed. Returns the number of meta rows
        whose ``property_type`` changed.
        """
        want = (property_type or "").strip().lower()
        if not want or (not source_filename and not doc_id):
            return 0

        changed = 0
        with self._lock:
            ti = self._get(tenant_id, tier)
            faiss_touched = False
            for row in ti.meta:
                if not _meta_row_matches_document(
                    row, source_filename=source_filename, doc_id=doc_id
                ):
                    continue
                if (row.get("property_type") or "").strip().lower() == want:
                    continue
                row["property_type"] = want
                changed += 1
                faiss_touched = True
            if faiss_touched:
                # Persist meta alongside the existing FAISS index (no re-embed).
                self._persist(tenant_id, tier, ti)

            # Chunk-only sidecar (INGEST_EMBED_ENABLED=false path).
            data = self._load_chunks_only(tenant_id, tier)
            if data:
                sidecar_touched = False
                names = {n for n in (source_filename or "",) if n}
                if doc_id and str(doc_id).startswith("reference:"):
                    names.add(str(doc_id).split(":", 1)[-1])
                for name, rows in list(data.items()):
                    for row in rows:
                        # Match by map key or row identity fields.
                        if name in names or _meta_row_matches_document(
                            {**row, "source_filename": row.get("source_filename") or name},
                            source_filename=source_filename,
                            doc_id=doc_id,
                        ):
                            if (row.get("property_type") or "").strip().lower() == want:
                                continue
                            row["property_type"] = want
                            changed += 1
                            sidecar_touched = True
                if sidecar_touched:
                    self._save_chunks_only(tenant_id, tier, data)

        if changed:
            logger.info(
                "Retagged %d chunk(s) to property_type=%s tenant=%s tier=%s "
                "(source=%s doc_id=%s)",
                changed,
                want,
                tenant_id,
                tier,
                source_filename,
                doc_id,
            )
        return changed

    def remove_chunks_by_ids(
        self,
        tenant_id: str,
        tier: str,
        chunk_ids: list[str] | set[str],
    ) -> int:
        """Drop specific chunks by ``chunk_id`` and rebuild the FAISS index."""
        wanted = {str(c).strip() for c in chunk_ids if str(c).strip()}
        if not wanted:
            return 0

        with self._lock:
            ti = self._get(tenant_id, tier)
            kept: list[dict] = []
            removed = 0
            for row in ti.meta:
                cid = str(row.get("chunk_id") or "").strip()
                if cid in wanted:
                    removed += 1
                else:
                    kept.append(row)

            if removed == 0:
                return 0

            if not kept:
                ti = _TierIndex(index=self._new_index(), meta=[])
            else:
                texts = [r["text"] for r in kept]
                vecs = self._embedder.embed_documents(texts)
                arr = np.asarray(vecs, dtype="float32")
                index = self._new_index()
                index.add(arr)
                ti = _TierIndex(index=index, meta=kept)

            self._cache[(tenant_id, tier)] = ti
            self._persist(tenant_id, tier, ti)
            logger.info(
                "Removed %d chunk(s) by id from tenant=%s tier=%s",
                removed,
                tenant_id,
                tier,
            )
            return removed

    def list_meta(
        self,
        tenant_id: str,
        tier: str,
        *,
        section_id: str | None = None,
    ) -> list[dict]:
        """Return a copy of metadata rows, optionally filtered by section_id."""
        with self._lock:
            rows = list(self._get(tenant_id, tier).meta)
        if section_id:
            rows = [r for r in rows if _meta_matches_section(r, section_id)]
        return [dict(r) for r in rows]

    def dedupe_tier(self, tenant_id: str, tier: str) -> int:
        """Drop exact-duplicate chunks within a tier; keep the first occurrence.

        Repeated uploads / re-ingests of the same file leave identical
        (section_id, text) rows in the index. They waste memory, inflate the
        subchunk view, and skew BM25 document frequencies. This collapses them by
        reusing the already-stored vectors (``reconstruct_n`` — no re-embed, no
        model load), rebuilds the index + meta, invalidates the BM25 / subchunk
        caches via the fresh ``_TierIndex``, and persists. Returns rows removed.
        """
        with self._lock:
            ti = self._get(tenant_id, tier)
            n = len(ti.meta)
            if n == 0:
                return 0

            seen: set[tuple[str, str]] = set()
            keep_idx: list[int] = []
            for i, row in enumerate(ti.meta):
                key = _dedupe_key(row.get("section_id", ""), row.get("text", ""))
                if not key[1] or key in seen:
                    continue
                seen.add(key)
                keep_idx.append(i)

            removed = n - len(keep_idx)
            if removed == 0:
                return 0

            if not keep_idx:
                new_ti = _TierIndex(index=self._new_index(), meta=[])
            else:
                try:
                    all_vecs = ti.index.reconstruct_n(0, n)
                    arr = np.asarray(all_vecs, dtype="float32")[keep_idx]
                except Exception:  # noqa: BLE001 - fall back to re-embedding kept rows
                    arr = np.asarray(
                        self._embedder.embed_documents(
                            [ti.meta[i]["text"] for i in keep_idx]
                        ),
                        dtype="float32",
                    )
                index = self._new_index()
                index.add(arr)
                new_ti = _TierIndex(index=index, meta=[ti.meta[i] for i in keep_idx])

            self._cache[(tenant_id, tier)] = new_ti
            self._persist(tenant_id, tier, new_ti)
            logger.info(
                "Deduped %s/%s: removed %d duplicate chunk(s); %d remain.",
                tenant_id,
                tier,
                removed,
                len(keep_idx),
            )
            return removed

    def retag_topics(self, tenant_id: str, tier: str) -> dict:
        """Re-classify every chunk's content topic in place (no re-embed).

        Lets already-ingested tenants become usable in content-based topic mode
        without re-uploading, and is the migration path after a taxonomy change.
        Reuses the stored vectors and only rewrites the ``topic_id`` /
        ``subtopic_id`` / ``theme_tags`` metadata plus the taxonomy version.
        Returns a per-topic chunk-count summary.
        """
        from backend.content_based import classifier as _classifier
        from backend.content_based.taxonomy import CONTENT_TAXONOMY_VERSION

        with self._lock:
            ti = self._get(tenant_id, tier)
            rows = ti.meta
            if not rows:
                return {}
            texts = [str(r.get("text") or "") for r in rows]
            hints = [str(r.get("section_id") or "") for r in rows]
            results = _classifier.classify_batch(texts, section_id_hints=hints)
            summary: dict[str, int] = {}
            for row, res in zip(rows, results):
                row["topic_id"] = res.topic_id
                row["subtopic_id"] = res.subtopic_id
                row["theme_tags"] = list(res.theme_tags)
                row["taxonomy_version"] = CONTENT_TAXONOMY_VERSION
                summary[res.topic_id] = summary.get(res.topic_id, 0) + 1
            self._persist(tenant_id, tier, ti)
        logger.info("Retagged %s/%s topics: %s", tenant_id, tier, summary)
        return summary

    def taxonomy_version_status(self, tenant_id: str, tier: str) -> dict:
        """Report how this tier's stored topic tags line up with the live taxonomy.

        Content mode needs both sides of retrieval to agree on bucket names: if
        chunks were tagged under an older taxonomy, topic-scoped search silently
        returns nothing. Surfacing the counts lets a caller warn instead.
        """
        from backend.content_based.taxonomy import CONTENT_TAXONOMY_VERSION

        rows = self._get(tenant_id, tier).meta
        untagged = stale = current = 0
        for row in rows:
            if not str(row.get("topic_id") or ""):
                untagged += 1
            elif str(row.get("taxonomy_version") or "") != CONTENT_TAXONOMY_VERSION:
                stale += 1
            else:
                current += 1
        return {
            "tier": tier,
            "total": len(rows),
            "current": current,
            "stale": stale,
            "untagged": untagged,
            "expected_version": CONTENT_TAXONOMY_VERSION,
            "needs_retag": bool(stale or untagged),
        }

    def count(self, tenant_id: str, tier: str) -> int:
        return len(self._get(tenant_id, tier).meta)

    def count_chunks_only(self, tenant_id: str, tier: str) -> int:
        """Rows in the chunk-only sidecar (ingest with ``INGEST_EMBED_ENABLED=false``)."""
        return sum(len(rows) for rows in self._load_chunks_only(tenant_id, tier).values())

    def list_source_filenames(self, tenant_id: str, tier: str) -> list[str]:
        """Unique source filenames ingested for a tier."""
        seen: set[str] = set()
        out: list[str] = []
        for row in self._get(tenant_id, tier).meta:
            name = str(row.get("source_filename") or row.get("doc_id") or "").strip()
            if name.startswith("reference:"):
                name = name.split(":", 1)[-1]
            if name and name not in seen:
                seen.add(name)
                out.append(name)
        return out

    def export_chunks_by_source(
        self, tenant_id: str, tier: str
    ) -> dict[str, list[dict]]:
        """Group every stored chunk by its source filename, in document order.

        Returns ``{source_filename: [chunk, ...]}`` where each chunk carries the
        retrievable text plus its section/paragraph/role metadata. REFERENCE text is
        already PII-scrubbed at ingest, so the result is safe to persist to disk.

        Includes both FAISS-embedded chunks and chunk-only sidecars (when
        ``INGEST_EMBED_ENABLED=false``). Embedded rows win on filename collision.
        """

        def _row_payload(row: dict) -> dict:
            return {
                "chunk_id": row.get("chunk_id", ""),
                "section_id": row.get("section_id", ""),
                "paragraph_index": int(row.get("paragraph_index") or 0),
                "content_role": row.get("content_role", CONTENT_ROLE_BODY),
                "parent_id": row.get("parent_id", ""),
                "document_type": row.get("document_type", ""),
                "property_type": row.get("property_type", ""),
                "is_scrubbed": bool(row.get("is_scrubbed")),
                "text": row.get("text", ""),
            }

        def _source_name(row: dict) -> str:
            name = str(row.get("source_filename") or row.get("doc_id") or "").strip()
            if name.startswith("reference:"):
                name = name.split(":", 1)[-1]
            return name or "unknown"

        faiss_grouped: dict[str, list[dict]] = {}
        for row in self._get(tenant_id, tier).meta:
            faiss_grouped.setdefault(_source_name(row), []).append(_row_payload(row))

        grouped: dict[str, list[dict]] = {}
        for name, rows in self._load_chunks_only(tenant_id, tier).items():
            if name in faiss_grouped:
                continue
            for row in rows:
                key = _source_name({**row, "source_filename": row.get("source_filename") or name})
                grouped.setdefault(key, []).append(_row_payload(row))

        for name, rows in faiss_grouped.items():
            grouped[name] = rows

        for chunks in grouped.values():
            chunks.sort(
                key=lambda c: (
                    str(c.get("section_id") or ""),
                    int(c.get("paragraph_index") or 0),
                    str(c.get("chunk_id") or ""),
                )
            )
        return grouped

    def sample_chunk_texts(
        self, tenant_id: str, tier: str, *, limit: int = 40
    ) -> list[str]:
        """Return up to ``limit`` chunk texts from a tier (for style analysis)."""
        texts: list[str] = []
        for row in self._get(tenant_id, tier).meta:
            if tier == TIER_REFERENCE and is_add_to_memory_meta(row):
                continue
            text = str(row.get("text") or "").strip()
            if text:
                texts.append(text)
            if len(texts) >= limit:
                break
        return texts

    def fetch_section_chunks(
        self,
        tenant_id: str,
        *,
        tier: str,
        section_id: str,
        source_key: str | None = None,
        allowed_doc_keys: frozenset[str] | None = None,
        document_type: str | None = None,
        property_type: str | None = None,
    ) -> list[SearchHit]:
        """Return EVERY stored chunk for a ``(tenant, tier, section_id)`` in document
        order — a metadata scan, NOT a similarity search.

        This backs section-complete baseline assembly: the full past-report section is
        mapped, not only the top-K semantically nearest chunks. REFERENCE chunks pass
        the same read-time scrub backstop as :meth:`search` (unscrubbed dropped, text
        re-sanitised). When ``source_key`` is given, only chunks from that one document
        (matched on ``source_filename`` or ``doc_id``) are returned, pinning assembly to
        a single report. When ``allowed_doc_keys`` is set, the upload allowlist applies.

        When ``document_type`` is set, only that type is returned. For REFERENCE
        without an explicit type, Add-to-Memory rows are excluded so past-report
        baselines stay report-only.

        When ``property_type`` is set (canonical ``house`` / ``flat``), only chunks
        with that exact metadata value are returned — untagged chunks are excluded.
        """
        want = (section_id or "").strip().upper()
        if not want:
            return []
        want_pt = (property_type or "").strip().lower() or None
        ti = self._get(tenant_id, tier)
        out: list[SearchHit] = []
        for m in ti.meta:
            if not _meta_matches_section(m, want):
                continue
            if allowed_doc_keys is not None and not meta_matches_allowlist(
                m, allowed_doc_keys
            ):
                continue
            if source_key is not None:
                key = (m.get("source_filename") or m.get("doc_id") or "").strip()
                if key != source_key:
                    continue
            dt = (m.get("document_type") or "").strip()
            if document_type:
                if dt != document_type:
                    continue
            elif tier == TIER_REFERENCE and is_add_to_memory_meta(m):
                continue
            if want_pt is not None and (m.get("property_type") or "").strip().lower() != want_pt:
                continue
            if tier == TIER_REFERENCE and not m.get("is_scrubbed"):
                continue
            text = m.get("text") or ""
            if tier == TIER_REFERENCE:
                text = pii_scrubber.sanitize_for_generation_context(text)
            if not text.strip():
                continue
            # Uniform rank: ordering is by document position, not similarity.
            out.append(_search_hit_from_meta(m, tier=tier, rank=1.0, text=text))
        out.sort(key=lambda h: (h.paragraph_index or 0, h.chunk_id or ""))
        return out

    def fetch_parent_intro_chunks(
        self,
        tenant_id: str,
        *,
        tier: str,
        parent_id: str,
        source_key: str | None = None,
        allowed_doc_keys: frozenset[str] | None = None,
        property_type: str | None = None,
    ) -> list[SearchHit]:
        """Return parent-group preamble chunks (prose before the first leaf subsection)."""
        want_parent = (parent_id or "").strip().upper()
        if not want_parent:
            return []
        want_pt = (property_type or "").strip().lower() or None
        ti = self._get(tenant_id, tier)
        out: list[SearchHit] = []
        for m in ti.meta:
            if (m.get("content_role") or CONTENT_ROLE_BODY) != CONTENT_ROLE_PARENT_INTRO:
                continue
            if (m.get("parent_id") or "").strip().upper() != want_parent:
                continue
            if allowed_doc_keys is not None and not meta_matches_allowlist(
                m, allowed_doc_keys
            ):
                continue
            if source_key is not None:
                key = (m.get("source_filename") or m.get("doc_id") or "").strip()
                if key != source_key:
                    continue
            if want_pt is not None and (m.get("property_type") or "").strip().lower() != want_pt:
                continue
            if tier == TIER_REFERENCE and is_add_to_memory_meta(m):
                continue
            if tier == TIER_REFERENCE and not m.get("is_scrubbed"):
                continue
            text = m.get("text") or ""
            if tier == TIER_REFERENCE:
                text = pii_scrubber.sanitize_for_generation_context(text)
            if not text.strip():
                continue
            out.append(_search_hit_from_meta(m, tier=tier, rank=1.0, text=text))
        out.sort(key=lambda h: (h.paragraph_index or 0, h.chunk_id or ""))
        return out

    # ── search ─────────────────────────────────────────────────────────────--
    def search(
        self,
        tenant_id: str,
        query: str,
        *,
        tier: str | None = None,
        section_id: str | None = None,
        top_k: int = 5,
        section_strict: bool = False,
        allowed_doc_keys: frozenset[str] | None = None,
        reference_document_ids: list[str] | None = None,
        strict_uploaded_only: bool = False,
        document_type: str | None = None,
        property_type: str | None = None,
    ) -> list[SearchHit]:
        """Search one or both tiers, ranked by similarity.

        When ``tier`` is None, MASTER hits are ranked ahead of REFERENCE hits at
        equal relevance (master is authoritative). When ``section_id`` is given,
        chunks tagged with that section are boosted.

        When ``section_strict`` is True, only chunks whose ``section_id`` equals
        ``section_id`` are returned (used to pin mapping to the correct paragraph).

        When ``allowed_doc_keys`` is set, only chunks whose ``doc_id`` or
        ``source_filename`` appears in the allowlist are returned.

        When ``strict_uploaded_only`` is True and ``reference_document_ids`` is
        non-empty, builds an allowlist via :func:`build_reference_allowlist` and
        drops hits that fail :func:`meta_matches_allowlist` on ``doc_id`` or
        ``source_filename``.

        When ``property_type`` is set, only chunks with that exact metadata value
        are returned (untagged excluded).
        """
        if allowed_doc_keys is None and strict_uploaded_only:
            allowed_doc_keys = build_reference_allowlist(
                tenant_id,
                reference_document_ids,
                strict_uploaded_only=True,
            )
        want_pt = (property_type or "").strip().lower() or None
        tiers = [tier] if tier else [TIER_MASTER, TIER_REFERENCE]
        hits: list[SearchHit] = []
        qvec = np.asarray([self._embedder.embed_query(query)], dtype="float32")
        pool_mult = 20 if allowed_doc_keys else 3

        hybrid = bool(settings.hybrid_retrieval_enabled)
        q_terms = lexical_index.tokenize(query) if hybrid else []
        use_hybrid = hybrid and bool(q_terms)

        for t in tiers:
            ti = self._get(tenant_id, t)
            n = len(ti.meta)
            if n == 0:
                continue
            k = min(max(top_k * pool_mult, top_k), n)

            # Dense arm. REFERENCE tier optionally uses the small-to-big view:
            # score the best sub-window per parent instead of the head-truncated
            # full chunk, then collapse to parent ids so the rest of the pipeline
            # (RRF, scrub, reranker, assembly) is unchanged.
            if settings.reference_subchunk_indexing_enabled and t == TIER_REFERENCE:
                dense_order, cosine_by_i = self._subchunk_dense_order(ti, qvec, k)
            else:
                scores, idxs = ti.index.search(qvec, k)
                cosine_by_i = {}
                dense_order = []
                for score, i in zip(scores[0], idxs[0], strict=False):
                    i = int(i)
                    if i < 0:
                        continue
                    cosine_by_i[i] = float(score)
                    dense_order.append(i)

            # Sparse arm + Reciprocal Rank Fusion. ``candidates`` is the ordered
            # pool the rest of the pipeline ranks over; ``fusion_by_i`` carries
            # the RRF score used as the primary sort key when hybrid is active.
            bm25_by_i: dict[int, float] = {}
            if use_hybrid:
                bm25 = self._get_bm25(ti)
                # Full corpus BM25 vector so every dense candidate keeps its
                # lexical score in the hit record (not only the sparse top-k).
                for local_i, s in enumerate(bm25.scores(q_terms)):
                    if s > 0.0:
                        bm25_by_i[local_i] = float(s)
                sparse_order = [i for i, _s in bm25.top_n(q_terms, k)]
                fused = lexical_index.reciprocal_rank_fusion(
                    [dense_order, sparse_order], k=settings.hybrid_rrf_k
                )
                candidates = [i for i, _f in fused]
                fusion_by_i = dict(fused)
            else:
                candidates = dense_order
                fusion_by_i = {}

            for i in candidates:
                m = ti.meta[i]
                if allowed_doc_keys is not None and not meta_matches_allowlist(
                    m, allowed_doc_keys
                ):
                    continue
                if document_type and (m.get("document_type") or "") != document_type:
                    continue
                # Default REFERENCE search hides Add-to-Memory; pass
                # document_type=DOC_TYPE_ADD_TO_MEMORY to retrieve them.
                if (
                    t == TIER_REFERENCE
                    and not document_type
                    and is_add_to_memory_meta(m)
                ):
                    continue
                if want_pt is not None and (m.get("property_type") or "").strip().lower() != want_pt:
                    continue
                if section_strict and section_id and m.get("section_id") != section_id:
                    continue
                # Reference backstop: never surface unscrubbed reference chunks.
                if t == TIER_REFERENCE and not m.get("is_scrubbed"):
                    continue
                text = m["text"]
                if t == TIER_REFERENCE:
                    text = pii_scrubber.sanitize_for_generation_context(text)
                    if not text.strip():
                        continue
                # ``score`` stays a cosine (+ boosts) so the downstream
                # multi-signal reranker's vector term keeps its semantics; the
                # sparse signal influences ordering via ``fusion_score``.
                # Component fields keep the raw arms for retrieval telemetry.
                cos = cosine_by_i.get(i)
                if cos is None:
                    cos = self._cosine_for(ti, i, qvec)
                rank = cos
                if t == TIER_MASTER:
                    rank += 0.05  # authoritative tier nudge
                if section_id and m.get("section_id") == section_id:
                    rank += settings.retrieval_section_boost
                hit = _search_hit_from_meta(m, tier=t, rank=rank, text=text)
                hit.similarity_score = float(cos)
                hit.bm25_score = float(bm25_by_i.get(i, 0.0))
                hit.fusion_score = float(fusion_by_i.get(i, 0.0))
                hits.append(hit)

        if use_hybrid:
            # RRF primary; cosine(+section/tier boost) breaks ties so section and
            # master priority survive among equally-fused candidates.
            hits.sort(key=lambda h: (h.fusion_score, h.score), reverse=True)
        else:
            hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    def search_section_scoped_hybrid(
        self,
        tenant_id: str,
        query: str,
        *,
        tier: str,
        section_id: str,
        top_k: int = 5,
        property_type: str | None = None,
        allowed_doc_keys: frozenset[str] | None = None,
    ) -> list[SearchHit]:
        """Hybrid retrieve within one subsection only (Approach B for SP / past reports).

        1. Filter meta rows to ``section_id`` (and optional ``property_type`` /
           allowlist).
        2. Dense (cosine) + BM25 only over that subset.
        3. Reciprocal Rank Fusion → Top-K.

        Unlike :meth:`search` with ``section_strict``, BM25/dense never compete
        with chunks from other subsections, and this path never builds the
        REFERENCE subchunk window view.

        Default REFERENCE behaviour excludes Add-to-Memory. Pass
        ``document_type=add_to_memory`` to retrieve only those paragraphs with
        the same hybrid parent-chunk scoring.
        """
        sid = (section_id or "").strip()
        if not sid:
            return []
        q = (query or "").strip()
        if not q:
            return []
        want_pt = (property_type or "").strip().lower() or None

        ti = self._get(tenant_id, tier)
        section_idxs: list[int] = []
        for i, m in enumerate(ti.meta):
            if str(m.get("section_id") or "").strip() != sid:
                continue
            if want_pt is not None and (m.get("property_type") or "").strip().lower() != want_pt:
                continue
            if allowed_doc_keys is not None and not meta_matches_allowlist(
                m, allowed_doc_keys
            ):
                continue
            if tier == TIER_REFERENCE and is_add_to_memory_meta(m):
                continue
            if tier == TIER_REFERENCE and not m.get("is_scrubbed"):
                continue
            section_idxs.append(i)
        if not section_idxs:
            return []

        qvec = np.asarray([self._embedder.embed_query(q)], dtype="float32")
        # Dense ranking within the filtered subsection pool.
        dense_scored: list[tuple[int, float]] = []
        for i in section_idxs:
            cos = self._cosine_for(ti, i, qvec)
            dense_scored.append((i, cos))
        dense_scored.sort(key=lambda x: x[1], reverse=True)
        dense_order = [i for i, _ in dense_scored]

        hybrid = bool(settings.hybrid_retrieval_enabled)
        q_terms = lexical_index.tokenize(q) if hybrid else []
        use_hybrid = hybrid and bool(q_terms)

        fusion_by_i: dict[int, float] = {}
        bm25_by_i: dict[int, float] = {}
        if use_hybrid:
            # BM25 corpus is ONLY this filtered subsection pool (local doc ids).
            corpus = [
                lexical_index.tokenize(str(ti.meta[i].get("text") or ""))
                for i in section_idxs
            ]
            bm25 = lexical_index.BM25Index(
                corpus,
                k1=settings.hybrid_bm25_k1,
                b=settings.hybrid_bm25_b,
            )
            local_scores = bm25.scores(q_terms)
            for local_i, s in enumerate(local_scores):
                if s > 0.0:
                    bm25_by_i[section_idxs[local_i]] = float(s)
            local_top = bm25.top_n(q_terms, len(section_idxs))
            sparse_order = [section_idxs[local_i] for local_i, _s in local_top]
            # Include every dense candidate so RRF still ranks pure-semantic hits.
            if not sparse_order:
                candidates = dense_order
            else:
                fused = lexical_index.reciprocal_rank_fusion(
                    [dense_order, sparse_order], k=settings.hybrid_rrf_k
                )
                candidates = [i for i, _f in fused]
                fusion_by_i = dict(fused)
        else:
            candidates = dense_order

        cosine_by_i = {i: s for i, s in dense_scored}
        hits: list[SearchHit] = []
        for i in candidates:
            m = ti.meta[i]
            text = m.get("text") or ""
            if tier == TIER_REFERENCE:
                text = pii_scrubber.sanitize_for_generation_context(text)
            if not str(text).strip():
                continue
            cos = float(cosine_by_i.get(i, 0.0))
            hit = _search_hit_from_meta(m, tier=tier, rank=cos, text=text)
            hit.similarity_score = cos
            hit.bm25_score = float(bm25_by_i.get(i, 0.0))
            hit.fusion_score = float(fusion_by_i.get(i, 0.0))
            hits.append(hit)

        if use_hybrid and fusion_by_i:
            hits.sort(key=lambda h: (h.fusion_score, h.score), reverse=True)
        else:
            hits.sort(key=lambda h: h.score, reverse=True)
        return hits[: max(1, int(top_k))]

    def fetch_topic_chunks(
        self,
        tenant_id: str,
        *,
        tier: str,
        topic_id: str,
        subtopic_id: str | None = None,
        allowed_doc_keys: frozenset[str] | None = None,
        document_type: str | None = None,
        property_type: str | None = None,
    ) -> list[SearchHit]:
        """Content-mode analogue of :meth:`fetch_section_chunks`.

        Metadata scan (NOT a similarity search) returning EVERY stored chunk whose
        ``topic_id`` matches (and ``subtopic_id`` when given), in document order.
        Applies the same REFERENCE read-time scrub backstop, Add-to-Memory
        exclusion, allowlist and property-type filters as the section-scoped fetch.
        """
        want_topic = (topic_id or "").strip()
        if not want_topic:
            return []
        want_sub = (subtopic_id or "").strip() or None
        want_pt = (property_type or "").strip().lower() or None
        ti = self._get(tenant_id, tier)
        out: list[SearchHit] = []
        for m in ti.meta:
            if str(m.get("topic_id") or "").strip() != want_topic:
                continue
            if want_sub is not None and str(m.get("subtopic_id") or "").strip() != want_sub:
                continue
            if allowed_doc_keys is not None and not meta_matches_allowlist(
                m, allowed_doc_keys
            ):
                continue
            dt = (m.get("document_type") or "").strip()
            if document_type:
                if dt != document_type:
                    continue
            elif tier == TIER_REFERENCE and is_add_to_memory_meta(m):
                continue
            if want_pt is not None and (m.get("property_type") or "").strip().lower() != want_pt:
                continue
            if tier == TIER_REFERENCE and not m.get("is_scrubbed"):
                continue
            text = m.get("text") or ""
            if tier == TIER_REFERENCE:
                text = pii_scrubber.sanitize_for_generation_context(text)
            if not text.strip():
                continue
            out.append(_search_hit_from_meta(m, tier=tier, rank=1.0, text=text))
        out.sort(key=lambda h: (h.paragraph_index or 0, h.chunk_id or ""))
        return out

    def search_topic_scoped_hybrid(
        self,
        tenant_id: str,
        query: str,
        *,
        tier: str,
        topic_id: str,
        subtopic_id: str | None = None,
        top_k: int = 5,
        property_type: str | None = None,
        allowed_doc_keys: frozenset[str] | None = None,
        require_theme_tags: frozenset[str] | None = None,
        boost_theme_tags: frozenset[str] | None = None,
        min_chars: int | None = None,
    ) -> list[SearchHit]:
        """Content-mode analogue of :meth:`search_section_scoped_hybrid`.

        Hybrid dense+BM25 retrieval restricted to one topic (and optional
        sub-topic) via the ``topic_id`` / ``subtopic_id`` chunk metadata, so
        content-mode retrieval never competes with other topics.

        ``require_theme_tags`` narrows to chunks carrying at least one of those
        themes — the way to ask "all damp evidence" across elements.
        ``boost_theme_tags`` instead reorders within the topic, preferring chunks
        that share a theme. ``min_chars`` drops form-field rows too short to be
        useful as style exemplars (defaults to ``content_min_chunk_chars``).
        """
        want_topic = (topic_id or "").strip()
        if not want_topic:
            return []
        q = (query or "").strip()
        if not q:
            return []
        want_sub = (subtopic_id or "").strip() or None
        want_pt = (property_type or "").strip().lower() or None
        need_tags = frozenset(require_theme_tags or ())
        floor = (
            int(settings.content_min_chunk_chars) if min_chars is None else int(min_chars)
        )

        ti = self._get(tenant_id, tier)
        topic_idxs: list[int] = []
        short_idxs: list[int] = []
        for i, m in enumerate(ti.meta):
            if str(m.get("topic_id") or "").strip() != want_topic:
                continue
            if want_sub is not None and str(m.get("subtopic_id") or "").strip() != want_sub:
                continue
            if want_pt is not None and (m.get("property_type") or "").strip().lower() != want_pt:
                continue
            if need_tags and not (need_tags & set(_theme_tags_from_meta(m))):
                continue
            if allowed_doc_keys is not None and not meta_matches_allowlist(
                m, allowed_doc_keys
            ):
                continue
            if tier == TIER_REFERENCE and is_add_to_memory_meta(m):
                continue
            if tier == TIER_REFERENCE and not m.get("is_scrubbed"):
                continue
            if floor > 0 and len(str(m.get("text") or "").strip()) < floor:
                short_idxs.append(i)
                continue
            topic_idxs.append(i)
        # The length floor is a preference, not a hard rule: a topic that only holds
        # short form-field rows should still return them rather than nothing at all.
        if not topic_idxs:
            topic_idxs = short_idxs
        if not topic_idxs:
            return []

        qvec = np.asarray([self._embedder.embed_query(q)], dtype="float32")
        dense_scored: list[tuple[int, float]] = []
        for i in topic_idxs:
            cos = self._cosine_for(ti, i, qvec)
            dense_scored.append((i, cos))
        dense_scored.sort(key=lambda x: x[1], reverse=True)
        dense_order = [i for i, _ in dense_scored]

        hybrid = bool(settings.hybrid_retrieval_enabled)
        q_terms = lexical_index.tokenize(q) if hybrid else []
        use_hybrid = hybrid and bool(q_terms)

        fusion_by_i: dict[int, float] = {}
        bm25_by_i: dict[int, float] = {}
        if use_hybrid:
            corpus = [
                lexical_index.tokenize(str(ti.meta[i].get("text") or ""))
                for i in topic_idxs
            ]
            bm25 = lexical_index.BM25Index(
                corpus,
                k1=settings.hybrid_bm25_k1,
                b=settings.hybrid_bm25_b,
            )
            local_scores = bm25.scores(q_terms)
            for local_i, s in enumerate(local_scores):
                if s > 0.0:
                    bm25_by_i[topic_idxs[local_i]] = float(s)
            local_top = bm25.top_n(q_terms, len(topic_idxs))
            sparse_order = [topic_idxs[local_i] for local_i, _s in local_top]
            if not sparse_order:
                candidates = dense_order
            else:
                fused = lexical_index.reciprocal_rank_fusion(
                    [dense_order, sparse_order], k=settings.hybrid_rrf_k
                )
                candidates = [i for i, _f in fused]
                fusion_by_i = dict(fused)
        else:
            candidates = dense_order

        cosine_by_i = {i: s for i, s in dense_scored}
        prefer_tags = frozenset(boost_theme_tags or ())
        tag_boost = float(settings.tag_retrieval_boost)
        # (fusion_rank, dense_rank, hit) — the tag preference has to be folded into
        # whichever key actually sorts, or it does nothing on the hybrid path.
        ranked: list[tuple[float, float, SearchHit]] = []
        for i in candidates:
            m = ti.meta[i]
            text = m.get("text") or ""
            if tier == TIER_REFERENCE:
                text = pii_scrubber.sanitize_for_generation_context(text)
            if not str(text).strip():
                continue
            cos = float(cosine_by_i.get(i, 0.0))
            hit = _search_hit_from_meta(m, tier=tier, rank=cos, text=text)
            hit.similarity_score = cos
            hit.bm25_score = float(bm25_by_i.get(i, 0.0))
            hit.fusion_score = float(fusion_by_i.get(i, 0.0))
            # Sharing a theme with the request is relevance evidence the cosine can
            # miss. Scaled rather than added so it expresses a proportional
            # preference on either key and cannot swamp a much better match.
            factor = (
                1.0 + tag_boost
                if prefer_tags and tag_boost > 0.0 and (prefer_tags & set(hit.theme_tags))
                else 1.0
            )
            hit.score = cos * factor
            ranked.append((hit.fusion_score * factor, hit.score, hit))

        if use_hybrid and fusion_by_i:
            ranked.sort(key=lambda r: (r[0], r[1]), reverse=True)
        else:
            ranked.sort(key=lambda r: r[1], reverse=True)
        return [hit for _f, _d, hit in ranked[: max(1, int(top_k))]]

    def search_for_generation(
        self,
        tenant_id: str,
        query: str,
        *,
        section_id: str | None = None,
        top_k: int = 5,
        section_strict: bool = False,
    ) -> list[SearchHit]:
        """Retrieve paragraphs for report mapping — MASTER boilerplate only.

        Past completed reports (REFERENCE tier) are never passed to the mapping
        step, so another property's sensitive data cannot enter the current report.
        """
        hits = self.search(
            tenant_id,
            query,
            tier=TIER_MASTER,
            section_id=section_id,
            top_k=top_k,
            section_strict=section_strict,
        )
        safe: list[SearchHit] = []
        for h in hits:
            text = pii_scrubber.sanitize_for_generation_context(h.text)
            if not text.strip():
                continue
            sh = _search_hit_from_meta(
                {
                    "section_id": h.section_id,
                    "doc_id": h.doc_id,
                    "is_scrubbed": h.is_scrubbed,
                    "source_filename": h.source_filename,
                    "paragraph_index": h.paragraph_index,
                    "chunk_id": h.chunk_id,
                },
                tier=h.tier,
                rank=h.score,
                text=text,
            )
            sh.similarity_score = float(getattr(h, "similarity_score", 0.0) or 0.0)
            sh.bm25_score = float(getattr(h, "bm25_score", 0.0) or 0.0)
            sh.fusion_score = h.fusion_score
            sh.rerank_score = float(h.rerank_score or 0.0)
            safe.append(sh)
        return safe

    def search_for_reference_mapping(
        self,
        tenant_id: str,
        query: str,
        *,
        section_id: str | None = None,
        top_k: int = 5,
        section_strict: bool = False,
        allowed_doc_keys: frozenset[str] | None = None,
        property_type: str | None = None,
    ) -> list[SearchHit]:
        """Retrieve scrubbed past-report excerpts for minimum-AI mapping."""
        hits = self.search(
            tenant_id,
            query,
            tier=TIER_REFERENCE,
            section_id=section_id,
            top_k=top_k,
            section_strict=section_strict,
            allowed_doc_keys=allowed_doc_keys,
            property_type=property_type,
        )
        safe: list[SearchHit] = []
        for h in hits:
            text = pii_scrubber.sanitize_for_generation_context(h.text)
            if not text.strip():
                continue
            sh = _search_hit_from_meta(
                {
                    "section_id": h.section_id,
                    "doc_id": h.doc_id,
                    "is_scrubbed": h.is_scrubbed,
                    "source_filename": h.source_filename,
                    "paragraph_index": h.paragraph_index,
                    "chunk_id": h.chunk_id,
                    "document_type": h.document_type,
                    "property_type": h.property_type,
                    "content_role": h.content_role,
                    "parent_id": h.parent_id,
                    "section_name": h.section_name,
                    "ingestion_source": h.ingestion_source,
                    "content_hash": h.content_hash,
                },
                tier=h.tier,
                rank=h.score,
                text=text,
            )
            sh.similarity_score = float(getattr(h, "similarity_score", 0.0) or 0.0)
            sh.bm25_score = float(getattr(h, "bm25_score", 0.0) or 0.0)
            sh.fusion_score = h.fusion_score
            sh.rerank_score = float(h.rerank_score or 0.0)
            safe.append(sh)
        return safe


_instance: RagStore | None = None


def get_rag_store() -> RagStore:
    global _instance
    if _instance is None:
        _instance = RagStore()
    return _instance


def reset_rag_store() -> None:
    global _instance
    _instance = None
