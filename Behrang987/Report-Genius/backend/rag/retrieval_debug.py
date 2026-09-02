"""Human-readable dump of the pre-rerank retrieval shortlist, for auditing recall.

Enabled by ``settings.retrieval_debug_dump`` (env ``RETRIEVAL_DEBUG_DUMP``). For each
reference-mapping retrieval it appends one block to
``<data_dir>/retrieval_debug/retrieval_<date>.log`` capturing the hybrid candidates
(dense jina-embeddings-v3 + BM25, RRF-fused) exactly as they stand BEFORE
jina-reranker-v3 reorders them — so you can see whether the embedder is pulling the
right chunks independent of the reranker.

Best-effort only: any failure here is swallowed so it can never break generation.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from backend.config import settings
from backend.observability import token_audit

if TYPE_CHECKING:
    from backend.rag.types import SearchHit

logger = logging.getLogger(__name__)

# Serialise writes: report generation fans many section retrievals across threads.
_write_lock = threading.Lock()


def enabled() -> bool:
    return bool(getattr(settings, "retrieval_debug_dump", False))


def _dump_file() -> Path:
    directory = settings.data_dir_path / "retrieval_debug"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"retrieval_{datetime.now():%Y%m%d}.log"


def _clip(text: str, cap: int) -> str:
    text = (text or "").strip()
    if cap and len(text) > cap:
        return f"{text[:cap]} …[+{len(text) - cap} more chars]"
    return text


def dump_pre_rerank(
    *,
    tenant_id: str,
    query: str,
    section_id: str,
    section_label: str,
    interference_level: str,
    retrieval_level: str,
    hits: list[SearchHit],
    rerank_top_n: int,
    final_top_k: int,
) -> None:
    """Append the pre-rerank candidate shortlist to the audit file (no-op if off)."""
    if not enabled():
        return
    try:
        cap = int(getattr(settings, "retrieval_debug_max_text_chars", 1500) or 0)
        embed_cap = int(getattr(settings, "local_embedding_max_seq_length", 0) or 0)
        rerank_char_cap = int(
            getattr(settings, "reference_cross_encoder_doc_chars", 0) or 0
        )
        query_summary = token_audit.summarize_text(query)
        query_embed = token_audit.summarize_embedder_feed(
            query, max_seq_length=embed_cap
        )
        out: list[str] = []
        out.append("=" * 100)
        out.append(
            f"[{datetime.now():%Y-%m-%d %H:%M:%S}] tenant={tenant_id or '?'} "
            f"section={section_id or '?'} ({section_label or '-'})  "
            f"interference={interference_level}  retrieval_level={retrieval_level}"
        )
        out.append(f"QUERY: {(query or '').strip()}")
        out.append(
            f"query chars={query_summary['chars']} tok={query_summary['tokens']} "
            f"(embed_cap={embed_cap or 'model-default'}, "
            f"embed_trunc={'yes' if query_embed['would_truncate'] else 'no'})"
        )
        out.append(
            f"candidates={len(hits)}  reranker_shortlist(top_n)={rerank_top_n}  "
            f"final_top_k={final_top_k}  reranker_doc_chars={rerank_char_cap}"
        )
        out.append(
            "token counts = tiktoken cl100k_base audit proxy "
            "(jina models use XLM-R tokenizer; counts are relative, not exact)"
        )
        out.append("order below = EMBEDDER/HYBRID rank (dense+BM25 RRF), PRE-rerank")
        out.append("-" * 100)
        if not hits:
            out.append("(no candidates retrieved)")
        for i, h in enumerate(hits, start=1):
            fed = "-> reranker" if i <= rerank_top_n else "tail (not reranked)"
            embed = token_audit.summarize_embedder_feed(
                h.text or "", max_seq_length=embed_cap
            )
            rerank = token_audit.summarize_reranker_feed(
                h.text or "",
                doc_chars_cap=rerank_char_cap if i <= rerank_top_n else 0,
            )
            rerank_tok_line = (
                f"rerank_fed={rerank['fed_chars']}c/{rerank['fed_tokens']}tok"
                if i <= rerank_top_n
                else "rerank_fed=n/a"
            )
            out.append(
                f"#{i:<2} [{fed}] score={h.score:.4f} "
                f"sim={getattr(h, 'similarity_score', 0.0):.4f} "
                f"bm25={getattr(h, 'bm25_score', 0.0):.4f} "
                f"fusion={h.fusion_score:.4f} "
                f"sec={h.section_id or '-'} para={h.paragraph_index} "
                f"src={h.source_filename or '-'} chunk={h.chunk_id or '-'} "
                f"scrubbed={h.is_scrubbed} "
                f"chars={embed['chars']} tok={embed['tokens']} "
                f"embed_trunc={'yes' if embed['would_truncate'] else 'no'} "
                f"{rerank_tok_line}"
            )
            out.append(f"    {_clip(h.text, cap)}")
        out.append("=" * 100)
        out.append("")
        blob = "\n".join(out)
        with _write_lock, _dump_file().open("a", encoding="utf-8") as fh:
            fh.write(blob)
    except Exception:  # noqa: BLE001 - auditing must never break retrieval
        logger.debug("retrieval_debug dump failed", exc_info=True)
