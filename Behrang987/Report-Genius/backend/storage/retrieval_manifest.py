"""Per-report retrieval manifest: which chunks were used to map each section.

Companion to ``extracted_chunks.json`` (the ingest-time view). Where that records
what every uploaded file was chunked into, this records — at generation time — the
messy surveyor notes for a section (e.g. ``D1``) alongside the exact chunks
that were retrieved (past-report OR standard-paragraph memory) and the exact
prompt that was sent to the LLM to rewrite that section's content.

``knowledge_source`` on each section record is ``past_report``,
``standard_paragraph``, or ``both``.

Per section we log, without skipping anything:
  * ``requested_top_k``       — the top-k the retriever was asked for.
  * ``retrieved_chunk_count`` — how many past-report chunks were actually retrieved.
  * ``prompt_chunk_count``    — how many of those were woven into the prompt baseline.
  * ``chunks_used``           — those chunks (``chunk_text`` = the past-report content).
  * ``baseline_text``         — the assembled INPUT-1 baseline built from the chunks.
  * ``prompt``                — the real LLM call: ``system`` rules, the
                                ``final_user_prompt`` built for THIS
                                section/subsection (leaf baseline + notes), and
                                the full ``messages`` array exactly as sent.
                                Mapping no longer injects cross-section few-shots.

Written to
``{tenant_root}/generate-runs/{UTC_YYYYMMDD-HHMMSS}_{report_id}/retrieval_manifest.json``
keyed by section id. Section workers run concurrently in threads, so every write
is a locked read-modify-write. Human-readable section files live in the same
run folder (see ``generation_run_export``).
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from backend.config import settings
from backend.storage import generate_run_store, tenant_store

if TYPE_CHECKING:
    from backend.rag.types import SearchHit

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def retrievals_dir(tenant_id: str) -> Path:
    """Legacy folder (pre–generate-runs). Kept for read fallback only."""
    d = tenant_store.tenant_root(tenant_id) / "retrievals"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_report_id(report_id: str) -> str:
    return generate_run_store.safe_draft_id(report_id)


def _legacy_stamped_manifest_candidates(tenant_id: str, safe_report: str) -> list[Path]:
    """Newest-last list of old ``retrievals/{stamp}_{report_id}.json`` files."""
    d = retrievals_dir(tenant_id)
    out: list[Path] = []
    for path in d.glob("*.json"):
        stem = path.stem
        if stem == safe_report:
            continue
        if stem.endswith(f"_{safe_report}") or f"_{safe_report}_" in stem:
            if len(stem) >= 16 and stem[8] == "-" and stem[15] == "_":
                out.append(path)
    return sorted(out, key=lambda p: p.name)


def retrieval_manifest_path(
    tenant_id: str,
    report_id: str,
    *,
    for_write: bool = False,
) -> Path:
    """Path for a report's retrieval manifest JSON.

    * ``for_write=True`` — allocate
      ``generate-runs/{UTC_stamp}_{report_id}/retrieval_manifest.json`` once per
      in-flight generate (shared by concurrent section writers).
    * ``for_write=False`` — newest generate-run manifest, else legacy
      ``retrievals/`` stamped file / ``{report_id}.json`` alias.
    """
    safe = _safe_report_id(report_id)

    if for_write:
        run_dir = generate_run_store.allocate_run_dir(tenant_id, report_id)
        return generate_run_store.retrieval_manifest_file(run_dir)

    run_dir = generate_run_store.resolve_run_dir(tenant_id, report_id, for_write=False)
    if run_dir is not None:
        path = generate_run_store.retrieval_manifest_file(run_dir)
        if path.is_file() or generate_run_store.peek_active_run_dir(
            tenant_id, report_id
        ) is not None:
            return path

    legacy = _legacy_stamped_manifest_candidates(tenant_id, safe)
    if legacy:
        return legacy[-1]
    return retrievals_dir(tenant_id) / f"{safe}.json"

def _serialize_dual_path(dual_path: dict | None) -> dict | None:
    """JSON-safe dual-path audit block (past draft + SP draft + per-path chunks)."""
    if not isinstance(dual_path, dict):
        return None
    past_hits = dual_path.get("past_report_hits") or []
    sp_hits = dual_path.get("standard_paragraph_hits") or []
    return {
        "merged": bool(dual_path.get("merged")),
        "past_report_draft": str(dual_path.get("past_report_draft") or ""),
        "standard_paragraph_draft": str(
            dual_path.get("standard_paragraph_draft") or ""
        ),
        "sp_findings": [
            str(i).strip()
            for i in (dual_path.get("sp_findings") or [])
            if str(i).strip()
        ],
        "sp_baseline_text": str(dual_path.get("sp_baseline_text") or ""),
        "past_report_chunks": [
            _hit_to_record(h) for h in past_hits if h is not None
        ],
        "standard_paragraph_chunks": [
            _hit_to_record(h) for h in sp_hits if h is not None
        ],
    }


def _hit_to_record(hit: "SearchHit") -> dict:
    """One retrieved chunk that was fed into this section's prompt.

    ``chunk_text`` is the source chunk content (past-report or standard-paragraph)
    that the baseline is assembled from.

    Score fields (same schema for past reports and standard paragraphs):
      * ``similarity_score`` — dense cosine similarity to the query
      * ``bm25_score`` — raw BM25 lexical score
      * ``fusion_score`` — Reciprocal Rank Fusion of dense + BM25 ranks
      * ``score`` — ranking key that decided order (rerank → fusion → similarity);
        after past-report section expansion this is the source-level primary
      * ``rerank_score`` — cross-encoder score when that path ran
    """
    return {
        "chunk_id": hit.chunk_id,
        "source_filename": hit.source_filename,
        "section_id": hit.section_id,
        "paragraph_index": hit.paragraph_index,
        "content_role": getattr(hit, "content_role", "body"),
        "parent_id": getattr(hit, "parent_id", ""),
        "score": round(float(hit.score or 0.0), 6),
        "similarity_score": round(
            float(getattr(hit, "similarity_score", 0.0) or 0.0), 6
        ),
        "bm25_score": round(float(getattr(hit, "bm25_score", 0.0) or 0.0), 6),
        "fusion_score": round(float(getattr(hit, "fusion_score", 0.0) or 0.0), 6),
        "rerank_score": round(float(hit.rerank_score or 0.0), 6),
        "chunk_text": hit.text,
    }


def _split_prompt_messages(
    prompt_messages: list[dict[str, str]],
) -> tuple[str, list[dict[str, str]], str]:
    """Separate the system rules, the canned few-shot demos, and the live task.

    The message array is ``[system, (demo_user, demo_assistant)*, live_user]`` (see
    ``inject_few_shot_turns`` / ``apply_dynamic_literature``, which always keep the
    live user turn last). Splitting them here is the whole point: the demo turns are
    teaching examples for OTHER sections and must not be mistaken for the prompt that
    was actually built for THIS section.
    """
    system = ""
    if prompt_messages and prompt_messages[0].get("role") == "system":
        system = prompt_messages[0].get("content", "") or ""

    live_idx = next(
        (
            i
            for i in range(len(prompt_messages) - 1, -1, -1)
            if prompt_messages[i].get("role") == "user"
        ),
        None,
    )
    final_user = (
        prompt_messages[live_idx].get("content", "") if live_idx is not None else ""
    )

    demo_slice = prompt_messages[1:live_idx] if live_idx is not None else []
    few_shot: list[dict[str, str]] = []
    pending_user: str | None = None
    for msg in demo_slice:
        role = msg.get("role")
        if role == "user":
            pending_user = msg.get("content", "") or ""
        elif role == "assistant":
            few_shot.append(
                {"user": pending_user or "", "assistant": msg.get("content", "") or ""}
            )
            pending_user = None
    if pending_user is not None:
        few_shot.append({"user": pending_user, "assistant": ""})

    return system, few_shot, final_user


def _prompt_block(
    prompt_messages: list[dict[str, str]] | None,
    *,
    temperature: float = 0.0,
    llm_usage: dict | None = None,
) -> dict | None:
    """Shape the exact LLM prompt (system + final user + full messages) for logging.

    Returns ``None`` for sections that never reached the LLM (NO_RAG_MATCH,
    authored-from-findings, notes-only), so those are logged explicitly rather
    than silently omitted.

    ``usage`` is the OpenAI response ``usage`` payload (prompt/completion/total
    tokens) when the call succeeded — billed provider counts, not tiktoken.
    """
    if not prompt_messages:
        return None
    system = next(
        (m.get("content", "") for m in prompt_messages if m.get("role") == "system"),
        "",
    )
    final_user = next(
        (
            m.get("content", "")
            for m in reversed(prompt_messages)
            if m.get("role") == "user"
        ),
        "",
    )
    block: dict = {
        "model": settings.mapping_model,
        "max_tokens": settings.max_tokens_mapping,
        "temperature": float(temperature),
        "system": system,
        "final_user_prompt": final_user,
        "messages": prompt_messages,
    }
    if llm_usage:
        block["usage"] = llm_usage
    return block


def record_section_retrieval(
    tenant_id: str,
    report_id: str,
    *,
    section_id: str,
    section_title: str,
    observations: list[str],
    baseline_text: str,
    hits: list["SearchHit"],
    status: str,
    prompt_messages: list[dict[str, str]] | None = None,
    retrieved_count: int | None = None,
    prompt_chunk_count: int | None = None,
    elapsed_ms: float | None = None,
    knowledge_source: str = "past_report",
    requested_top_k: int | None = None,
    generated_text: str | None = None,
    retrieval_issues: list[str] | None = None,
    llm_usage: dict | None = None,
    style_sample_count: int | None = None,
    add_to_memory_hits: list["SearchHit"] | None = None,
    dual_path: dict | None = None,
) -> None:
    """Append/replace one section's retrieval record and persist the manifest.

    Captures, per section: the top-k requested (``requested_top_k``), how many
    chunks were retrieved (``retrieved_chunk_count``), how many entered the prompt
    (``prompt_chunk_count``), the chunks themselves (``chunks_used`` with
    ``chunk_text``), the LLM output (``generated_text``), and the full LLM prompt
    (``prompt``: system rules, the ``final_user_prompt`` built for THIS section,
    and the complete ``messages`` array). When the OpenAI call returns
    ``usage``, that is stored as ``llm_usage`` / ``prompt.usage`` (provider
    prompt/completion/total tokens). Never raises — a manifest write failure
    must not abort section generation.

    ``knowledge_source`` is ``past_report``, ``standard_paragraph``, or ``both``.
    """
    if not report_id:
        return
    try:
        ks = (knowledge_source or "both").strip().lower() or "both"
        if requested_top_k is not None:
            top_k = int(requested_top_k)
        elif ks == "standard_paragraph":
            top_k = int(settings.standard_paragraphs_merged_top_k)
        else:
            top_k = int(settings.retrieval_top_k)
        chunks_used = [_hit_to_record(h) for h in (hits or [])]
        prompt_temp = (
            float(settings.standard_paragraphs_temperature)
            if ks == "standard_paragraph"
            else float(settings.mapping_temperature)
        )
        prompt_block = _prompt_block(
            prompt_messages,
            temperature=prompt_temp,
            llm_usage=llm_usage,
        )
        now_iso = datetime.now(timezone.utc).isoformat()
        record = {
            "section_title": section_title,
            "status": status,
            "knowledge_source": ks,
            "elapsed_ms": elapsed_ms,
            "recorded_at": now_iso,
            "observations": [o for o in (observations or []) if str(o).strip()],
            # LLM-decomposed findings used for per-issue SP retrieve (SP path).
            "retrieval_issues": [
                i for i in (retrieval_issues or []) if str(i).strip()
            ],
            "retrieval_findings": [
                i for i in (retrieval_issues or []) if str(i).strip()
            ],
            # Concatenated retrieved SP texts only (audit). NOT the full LLM payload.
            "baseline_text": baseline_text or "",
            # Final subsection prose returned for this section (LLM or fallback).
            "generated_text": (generated_text or "").strip(),
            "requested_top_k": top_k,
            "retrieved_chunk_count": (
                retrieved_count if retrieved_count is not None else len(chunks_used)
            ),
            "prompt_chunk_count": (
                prompt_chunk_count
                if prompt_chunk_count is not None
                else len(chunks_used)
            ),
            "chunk_count": len(chunks_used),
            "chunks_used": chunks_used,
            "prompt_logged": bool(prompt_block),
            # Exact LLM inputs (what was actually sent).
            "system_prompt": (prompt_block or {}).get("system") or "",
            "user_prompt": (prompt_block or {}).get("final_user_prompt") or "",
            "prompt": prompt_block,
            # OpenAI response.usage (prompt/completion/total); None if no LLM call.
            "llm_usage": llm_usage,
            # Past-report style samples injected into the SP prompt (0 when off).
            "style_sample_count": int(style_sample_count or 0),
            # Add-to-Memory shells injected into the past-report prompt (0 when none).
            "add_to_memory_count": len(add_to_memory_hits or []),
            "add_to_memory_chunks": [
                _hit_to_record(h) for h in (add_to_memory_hits or [])
            ],
            # When knowledge_source=both: per-path drafts, findings, and chunks.
            "dual_path": _serialize_dual_path(dual_path),
        }
        path = retrieval_manifest_path(tenant_id, report_id, for_write=True)
        run_dir = path.parent
        with _lock:
            data: dict = {"report_id": report_id, "sections": {}}
            if path.is_file():
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(existing, dict) and "sections" in existing:
                        data = existing
                except (OSError, ValueError):
                    pass
            data["sections"][section_id.upper()] = record
            data.setdefault("generated_at", now_iso)
            data["updated_at"] = now_iso
            data["knowledge_source"] = ks
            data["manifest_file"] = path.name
            data["run_folder"] = run_dir.name
            payload = json.dumps(data, indent=2, ensure_ascii=False)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")
    except Exception:  # noqa: BLE001 - manifest is a non-critical side artifact
        logger.warning(
            "Failed to record retrieval manifest for tenant=%s report=%s section=%s.",
            tenant_id,
            report_id,
            section_id,
            exc_info=True,
        )
