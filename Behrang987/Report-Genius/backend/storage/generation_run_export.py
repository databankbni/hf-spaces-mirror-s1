"""Human-readable files for a generate run (same folder as retrieval_manifest).

Layout (one Generate → one folder)::

    {DATA_DIR}/tenants/<tenant>/generate-runs/{UTC_stamp}_{draft_id}/
      retrieval_manifest.json     # machine truth (written during generate)
      run_summary.json            # short index of sections in this export
      D2/
        01_inspection_notes.txt
        02_final_generated_prose.txt
        03_past_report_draft.txt
        04_past_report_retrieved_sources.txt
        05_standard_paragraph_draft.txt
        06_standard_paragraph_retrieved_sources.txt
        07_standard_paragraph_findings.txt
        08_standard_paragraph_baseline.txt
        09_llm_system_prompt.txt
        10_llm_user_prompt.txt
        11_retrieved_chunks.json
        12_section_summary.json
        13_readable_overview.txt
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from backend.storage import generate_run_store, retrieval_manifest

logger = logging.getLogger(__name__)


def _clean_prose(text: str) -> str:
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    while "\n\n\n" in t:
        t = t.replace("\n\n\n", "\n\n")
    return t.strip() + ("\n" if (text or "").strip() else "")


def _sources_from_manifest_section(sec: dict) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for chunk in sec.get("chunks_used") or []:
        if not isinstance(chunk, dict):
            continue
        name = str(
            chunk.get("source_filename") or chunk.get("doc_id") or ""
        ).strip()
        if name.startswith("reference:"):
            name = name.split(":", 1)[-1]
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _ranking_preview_from_manifest(sec: dict) -> list[dict]:
    out: list[dict] = []
    for i, chunk in enumerate(sec.get("chunks_used") or [], start=1):
        if not isinstance(chunk, dict):
            continue
        name = str(chunk.get("source_filename") or chunk.get("doc_id") or "").strip()
        if name.startswith("reference:"):
            name = name.split(":", 1)[-1]
        text = str(chunk.get("chunk_text") or chunk.get("text") or "")
        out.append(
            {
                "rank": i,
                "source_filename": name,
                "chars": len(text),
                "score": chunk.get("score"),
                "similarity_score": chunk.get("similarity_score"),
                "bm25_score": chunk.get("bm25_score"),
                "fusion_score": chunk.get("fusion_score"),
            }
        )
    return out


def _notes_for_section(sec_id: str, observations: list[str], raw_notes: str) -> str:
    items = [o.strip() for o in (observations or []) if str(o).strip()]
    if items:
        return "\n".join(items)
    blob = (raw_notes or "").strip()
    if not blob:
        return ""
    pat = re.compile(
        rf"(?im)^\s*{re.escape(sec_id)}\s*:\s*(.+?)(?=^\s*[A-Z]\d{{0,2}}\s*:|\Z)",
        re.S,
    )
    m = pat.search(blob)
    if m:
        return m.group(1).strip()
    return blob


def _write_named_sources(path: Path, sources: list[str], *, header: str) -> None:
    body = "\n".join(f"{i}. {n}" for i, n in enumerate(sources, 1))
    path.write_text(
        (f"{header}\n" if header else "")
        + body
        + ("\n" if body or header else ""),
        encoding="utf-8",
    )


def _dual_path_from_manifest(man: dict) -> dict:
    raw = man.get("dual_path")
    return raw if isinstance(raw, dict) else {}


def _write_section_bundle(
    run_dir: Path,
    *,
    draft_id: str,
    tenant_id: str,
    property_type: str,
    section_id: str,
    status: str,
    notes: str,
    generated: str,
    unmatched: list[Any],
    sources: list[str],
    blocks_meta: list[dict],
    knowledge_source: str,
    manifest_path: Path | None,
    man_section: dict | None = None,
) -> Path:
    sec_dir = run_dir / section_id.upper()
    sec_dir.mkdir(parents=True, exist_ok=True)
    notes_clean = _clean_prose(notes)
    gen_clean = _clean_prose(generated)
    man = man_section if isinstance(man_section, dict) else {}
    dual = _dual_path_from_manifest(man)
    ks = (knowledge_source or "").strip().lower()
    has_dual_audit = bool(dual)

    past_draft = _clean_prose(str(dual.get("past_report_draft") or ""))
    sp_draft = _clean_prose(str(dual.get("standard_paragraph_draft") or ""))
    sp_findings = [
        str(i).strip() for i in (dual.get("sp_findings") or []) if str(i).strip()
    ]
    sp_baseline = _clean_prose(str(dual.get("sp_baseline_text") or ""))
    past_chunks = dual.get("past_report_chunks") or []
    sp_chunks = dual.get("standard_paragraph_chunks") or []
    if not isinstance(past_chunks, list):
        past_chunks = []
    if not isinstance(sp_chunks, list):
        sp_chunks = []

    # Past sources must come from dual-path past hits when present. Do NOT fall
    # back to final ``chunks_used`` — those are often SP hits and made it look
    # like past retrieval succeeded while past_report_draft was empty.
    if past_chunks:
        past_sources = _sources_from_manifest_section({"chunks_used": past_chunks})
        past_ranking = _ranking_preview_from_manifest({"chunks_used": past_chunks})
    elif not has_dual_audit and ks != "standard_paragraph":
        # Past-only (or UI ``both`` resolved to past when no SP index): chunks_used
        # ARE the past-report scaffolds.
        past_sources = list(sources)
        past_ranking = list(blocks_meta)
    else:
        past_sources = []
        past_ranking = []

    # Past-only generates do not stamp dual_path; prose lives on generated_text.
    # UI always requests ``both``, but resolve_knowledge_source collapses to
    # ``past_report`` when the SP catalogue is empty — same empty-dual case.
    if not past_draft.strip() and not has_dual_audit and ks != "standard_paragraph":
        past_draft = gen_clean
    elif (
        not past_draft.strip()
        and has_dual_audit
        and past_chunks
        and not sp_draft.strip()
        and gen_clean.strip()
    ):
        # Dual-path past survivor without draft field — use final prose.
        past_draft = gen_clean

    sp_sources = (
        _sources_from_manifest_section({"chunks_used": sp_chunks}) if sp_chunks else []
    )
    sp_ranking = (
        _ranking_preview_from_manifest({"chunks_used": sp_chunks}) if sp_chunks else []
    )

    # Numbered prefixes = recommended reading order in a file browser.
    (sec_dir / "01_inspection_notes.txt").write_text(notes_clean, encoding="utf-8")
    (sec_dir / "02_final_generated_prose.txt").write_text(gen_clean, encoding="utf-8")

    write_past = bool(past_draft.strip() or past_sources or past_chunks)
    if write_past or (has_dual_audit and "past_report_draft" in dual):
        past_draft_out = past_draft
        if not past_draft.strip() and has_dual_audit:
            past_draft_out = (
                "(no past-report draft for this subsection — past-report path "
                "returned no usable prose, e.g. NO_RAG_MATCH / empty. Final "
                "output may still come from standard paragraphs or merge.)\n"
            )
        (sec_dir / "03_past_report_draft.txt").write_text(
            past_draft_out, encoding="utf-8"
        )
        _write_named_sources(
            sec_dir / "04_past_report_retrieved_sources.txt",
            past_sources,
            header="Past-report documents used for this subsection",
        )
    if sp_draft or sp_sources or sp_findings or sp_baseline or dual.get("merged"):
        (sec_dir / "05_standard_paragraph_draft.txt").write_text(
            sp_draft, encoding="utf-8"
        )
        _write_named_sources(
            sec_dir / "06_standard_paragraph_retrieved_sources.txt",
            sp_sources,
            header="Standard-paragraph documents used for this subsection",
        )
        if sp_findings:
            (sec_dir / "07_standard_paragraph_findings.txt").write_text(
                "\n".join(f"- {f}" for f in sp_findings) + "\n",
                encoding="utf-8",
            )
        if sp_baseline:
            (sec_dir / "08_standard_paragraph_baseline.txt").write_text(
                sp_baseline, encoding="utf-8"
            )

    system_prompt = str(man.get("system_prompt") or "").strip()
    user_prompt = str(man.get("user_prompt") or "").strip()
    if not system_prompt and isinstance(man.get("prompt"), dict):
        system_prompt = str(man["prompt"].get("system") or "").strip()
    if not user_prompt and isinstance(man.get("prompt"), dict):
        user_prompt = str(man["prompt"].get("final_user_prompt") or "").strip()
    if system_prompt:
        (sec_dir / "09_llm_system_prompt.txt").write_text(
            system_prompt + "\n", encoding="utf-8"
        )
    if user_prompt:
        (sec_dir / "10_llm_user_prompt.txt").write_text(
            user_prompt + "\n", encoding="utf-8"
        )

    chunks_payload = {
        "section_id": section_id.upper(),
        "chunks_used": man.get("chunks_used") or [],
        "past_report_chunks": past_chunks,
        "standard_paragraph_chunks": sp_chunks,
        "add_to_memory_chunks": man.get("add_to_memory_chunks") or [],
    }
    (sec_dir / "11_retrieved_chunks.json").write_text(
        json.dumps(chunks_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    meta = {
        "draft_id": draft_id,
        "tenant_id": tenant_id,
        "property_type": property_type,
        "section_id": section_id.upper(),
        "status": status,
        "knowledge_source": knowledge_source,
        "unmatched": unmatched,
        "retrieved_count": len(past_sources),
        "retrieved_sources": past_sources,
        "char_counts": {
            "inspection_notes": len(notes_clean),
            "final_generated_prose": len(gen_clean),
            "final_generated_words": len(gen_clean.split()),
            "past_report_draft": len(past_draft),
            "standard_paragraph_draft": len(sp_draft),
        },
        "ranking_preview": past_ranking,
        "retrieval_manifest": str(manifest_path) if manifest_path else None,
        "dual_path": {
            "merged": bool(dual.get("merged")),
            "past_report_sources": past_sources,
            "standard_paragraph_sources": sp_sources,
            "sp_findings": sp_findings,
            "past_report_ranking": past_ranking,
            "standard_paragraph_ranking": sp_ranking,
            "had_past_report_draft": bool(past_draft.strip()),
            "had_standard_paragraph_draft": bool(sp_draft.strip()),
        }
        if dual
        else None,
        "llm_usage": man.get("llm_usage"),
    }
    (sec_dir / "12_section_summary.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    readable_parts = [
        f"DRAFT: {draft_id}",
        f"STATUS: {status}",
        f"KNOWLEDGE_SOURCE: {knowledge_source}",
        f"DUAL_PATH_MERGED: {bool(dual.get('merged')) if dual else 'n/a'}",
        f"WORDS: {len(gen_clean.split())}  CHARS: {len(gen_clean)}",
        f"{'=' * 72}",
        "INSPECTION NOTES",
        f"{'=' * 72}",
        "",
        notes_clean,
    ]
    if past_draft.strip():
        readable_parts.extend(
            [
                f"{'=' * 72}",
                "PAST REPORT DRAFT",
                f"{'=' * 72}",
                "",
                past_draft,
            ]
        )
    if sp_draft.strip():
        readable_parts.extend(
            [
                f"{'=' * 72}",
                "STANDARD PARAGRAPH DRAFT",
                f"{'=' * 72}",
                "",
                sp_draft,
            ]
        )
    if sp_findings:
        readable_parts.extend(
            [
                f"{'=' * 72}",
                "STANDARD PARAGRAPH FINDINGS (decomposed)",
                f"{'=' * 72}",
                "",
                "\n".join(f"- {f}" for f in sp_findings),
            ]
        )
    readable_parts.extend(
        [
            f"{'=' * 72}",
            f"FINAL GENERATED {section_id.upper()}"
            + (" (merged)" if dual.get("merged") else ""),
            f"{'=' * 72}",
            "",
            gen_clean,
        ]
    )
    (sec_dir / "13_readable_overview.txt").write_text(
        "\n".join(readable_parts), encoding="utf-8"
    )
    return sec_dir


def export_ui_generation_run(
    *,
    tenant_id: str,
    draft_id: str,
    property_type: str = "",
    knowledge_source: str = "both",
    interference_level: str = "",
    raw_notes: str = "",
    sections: list[Any] | None = None,
    section_payloads: dict[str, dict] | None = None,
) -> Path | None:
    """Write human-readable section bundles into the generate-run folder.

    Reuses the same ``generate-runs/{stamp}_{draft_id}/`` directory that
    ``retrieval_manifest`` allocated during generate (or allocates one if
    missing). Never raises — export failure must not fail the user-facing call.
    """
    try:
        safe = generate_run_store.safe_draft_id(draft_id)
        if not safe or safe == "report" and not (draft_id or "").strip():
            return None

        run_dir = generate_run_store.resolve_run_dir(
            tenant_id, draft_id, for_write=True
        )
        assert run_dir is not None
        run_dir.mkdir(parents=True, exist_ok=True)
        run_folder = run_dir.name
        # Stamp is the folder prefix before the first '_' after YYYYMMDD-HHMMSS.
        run_stamp = run_folder.split("_", 1)[0] if "_" in run_folder else run_folder

        manifest_path = retrieval_manifest.retrieval_manifest_path(
            tenant_id, draft_id, for_write=False
        )
        manifest: dict = {}
        if manifest_path.is_file():
            try:
                loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    manifest = loaded
            except (OSError, ValueError):
                manifest = {}
        man_sections = manifest.get("sections") or {}
        if not isinstance(man_sections, dict):
            man_sections = {}

        section_rows: list[dict] = []

        def _export_one(
            sid: str,
            *,
            generated: str,
            status: str,
            unmatched: list[Any],
        ) -> None:
            man = man_sections.get(sid) or {}
            notes = _notes_for_section(
                sid, list(man.get("observations") or []), raw_notes
            )
            sources = _sources_from_manifest_section(man)
            blocks_meta = _ranking_preview_from_manifest(man)
            _write_section_bundle(
                run_dir,
                draft_id=safe,
                tenant_id=tenant_id,
                property_type=property_type,
                section_id=sid,
                status=status,
                notes=notes,
                generated=generated,
                unmatched=unmatched,
                sources=sources,
                blocks_meta=blocks_meta,
                knowledge_source=str(man.get("knowledge_source") or knowledge_source),
                manifest_path=manifest_path if manifest_path.is_file() else None,
                man_section=man,
            )
            dual = _dual_path_from_manifest(man)
            section_rows.append(
                {
                    "section_id": sid,
                    "status": status,
                    "generated_text": generated,
                    "observations": man.get("observations") or [],
                    "retrieved_sources": sources,
                    "knowledge_source": man.get("knowledge_source") or knowledge_source,
                    "unmatched": unmatched,
                    "dual_path_merged": bool(dual.get("merged")) if dual else None,
                    "had_standard_paragraph_draft": bool(
                        str(dual.get("standard_paragraph_draft") or "").strip()
                    )
                    if dual
                    else False,
                    "section_folder": sid,
                }
            )

        if sections:
            for sec in sections:
                sid = str(getattr(sec, "section_id", "") or "").strip().upper()
                if not sid:
                    continue
                man = man_sections.get(sid) or {}
                generated = str(
                    getattr(sec, "text", None) or man.get("generated_text") or ""
                )
                status = str(getattr(sec, "status", None) or man.get("status") or "")
                unmatched = list(getattr(sec, "unmatched_observations", None) or [])
                _export_one(sid, generated=generated, status=status, unmatched=unmatched)
        elif section_payloads:
            for sid_raw, payload in section_payloads.items():
                sid = str(sid_raw or "").strip().upper()
                if not sid or not isinstance(payload, dict):
                    continue
                man = man_sections.get(sid) or {}
                generated = str(
                    payload.get("content")
                    or payload.get("text")
                    or man.get("generated_text")
                    or ""
                )
                status = str(payload.get("status") or man.get("status") or "")
                unmatched = list(payload.get("unmatched_observations") or [])
                _export_one(sid, generated=generated, status=status, unmatched=unmatched)

        from datetime import datetime, timezone

        out = {
            "draft_id": safe,
            "run_stamp": run_stamp,
            "run_folder": run_folder,
            "tenant_id": tenant_id,
            "property_type": property_type,
            "knowledge_source": knowledge_source,
            "interference_level": interference_level,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "retrieval_manifest": str(manifest_path) if manifest_path.is_file() else None,
            "run_dir": str(run_dir),
            "sections": section_rows,
            "files": {
                "retrieval_manifest": generate_run_store.RETRIEVAL_MANIFEST_NAME,
                "run_summary": generate_run_store.RUN_SUMMARY_NAME,
                "per_section": [
                    "01_inspection_notes.txt",
                    "02_final_generated_prose.txt",
                    "03_past_report_draft.txt",
                    "04_past_report_retrieved_sources.txt",
                    "05_standard_paragraph_draft.txt",
                    "06_standard_paragraph_retrieved_sources.txt",
                    "07_standard_paragraph_findings.txt",
                    "08_standard_paragraph_baseline.txt",
                    "09_llm_system_prompt.txt",
                    "10_llm_user_prompt.txt",
                    "11_retrieved_chunks.json",
                    "12_section_summary.json",
                    "13_readable_overview.txt",
                ],
            },
        }
        generate_run_store.run_summary_file(run_dir).write_text(
            json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        logger.info(
            "ui_generation_export draft=%s sections=%d dir=%s",
            safe,
            len(section_rows),
            run_dir,
        )
        return run_dir
    except Exception:  # noqa: BLE001 — non-critical operator artefact
        logger.warning(
            "ui_generation_export_failed tenant=%s draft=%s",
            tenant_id,
            draft_id,
            exc_info=True,
        )
        return None
    finally:
        # Next Generate for this draft gets a fresh stamped folder.
        try:
            generate_run_store.release_active_run(tenant_id, draft_id)
        except Exception:  # noqa: BLE001
            pass
