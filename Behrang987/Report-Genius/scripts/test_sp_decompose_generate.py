"""E2E: LLM decompose issues → per-issue SP retrieve → generate for one subsection.

Bypasses the note-parser heading trap by using the same per-section observations
as ``test_sp_decompose_notes.py``. Does not require
``STANDARD_PARAGRAPHS_DECOMPOSE_NOTES=true`` (uses force_decompose).

Examples:
  python scripts/test_sp_decompose_generate.py --section D1 --force-llm
  python scripts/test_sp_decompose_generate.py --section F6 --force-llm --all-sps
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.config import settings
from backend.domain import template_discoverer
from backend.standard_paragraphs.generate import generate_from_standard_paragraphs
from backend.standard_paragraphs.note_issues_manifest import record_note_issues
from backend.storage import retrieval_manifest


def _load_decompose_cases() -> tuple[list[dict], str]:
    path = _ROOT / "scripts" / "test_sp_decompose_notes.py"
    spec = importlib.util.spec_from_file_location("test_sp_decompose_notes", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(mod.CASES), str(mod.TENANT)


CASES, DEFAULT_TENANT = _load_decompose_cases()


def _case_for(section_id: str) -> dict:
    sid = section_id.strip().upper()
    for case in CASES:
        if case["section_id"].upper() == sid:
            return case
    known = [c["section_id"] for c in CASES]
    raise SystemExit(f"Unknown section {section_id!r}. Known: {known}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="E2E SP: decompose → retrieve → generate (one subsection)"
    )
    parser.add_argument("--section", required=True, help="e.g. D1, D8, F6")
    parser.add_argument(
        "--force-llm",
        action="store_true",
        help="Force LLM decompose even for short notes",
    )
    parser.add_argument(
        "--all-sps",
        action="store_true",
        help=(
            "Pass EVERY standard paragraph for this subsection from FAISS "
            "(no Top-K). Still decomposes notes into findings for the prompt."
        ),
    )
    parser.add_argument(
        "--style-samples",
        action="store_true",
        help=(
            "Force-inject past REFERENCE subsection samples into the SP prompt "
            "(overrides STANDARD_PARAGRAPHS_STYLE_SAMPLES_ENABLED for this run)."
        ),
    )
    parser.add_argument("--tenant", default=DEFAULT_TENANT)
    parser.add_argument(
        "--draft-id",
        default="",
        help="Retrieval manifest id (default: sp-e2e-<section>-<timestamp>)",
    )
    args = parser.parse_args()

    case = _case_for(args.section)
    sid = case["section_id"]
    title = case["section_title"]
    observations = list(case["observations"])
    suffix = "allsps" if args.all_sps else "e2e"
    draft_id = args.draft_id.strip() or (
        f"sp-{suffix}-{sid.lower()}-"
        + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    )

    print("tenant=", args.tenant)
    print("draft=", draft_id)
    print("section=", sid, title)
    print("force_decompose=True force_llm=", args.force_llm)
    print("use_all_section_sps=", args.all_sps)
    print("style_samples=", args.style_samples)
    print("decompose_flag_in_env=", settings.standard_paragraphs_decompose_notes)
    print("observations:")
    for o in observations:
        print(" -", o)

    schema = template_discoverer.ensure_canonical_schema(args.tenant)
    text, hits, messages, guidance, issues, llm_usage, style_sample_count = (
        generate_from_standard_paragraphs(
            tenant_id=args.tenant,
            schema=schema,
            section_id=sid,
            section_title=title,
            observations=observations,
            candidate_ids=[sid],
            force_decompose=True,
            force_decompose_llm=args.force_llm,
            use_all_section_sps=args.all_sps,
            style_samples_enabled=True if args.style_samples else None,
        )
    )

    issues_path = record_note_issues(
        args.tenant,
        draft_id,
        section_id=sid,
        section_title=title,
        observations=observations,
        issues=list(issues),
        source="e2e_decompose_generate",
        used_llm=True if args.force_llm else None,
    )

    retrieval_manifest.record_section_retrieval(
        args.tenant,
        draft_id,
        section_id=sid,
        section_title=title,
        observations=observations,
        baseline_text=guidance,
        hits=hits,
        status="MAPPED" if text.strip() and hits else "NO_RAG_MATCH",
        prompt_messages=messages,
        retrieved_count=len(hits),
        prompt_chunk_count=len(hits),
        knowledge_source="standard_paragraph",
        generated_text=text,
        retrieval_issues=list(issues),
        requested_top_k=len(hits) if args.all_sps else None,
        llm_usage=llm_usage,
        style_sample_count=style_sample_count,
    )
    ret_path = retrieval_manifest.retrieval_manifest_path(args.tenant, draft_id)

    print("\n=== ISSUES (LLM / heuristic) ===")
    for i, issue in enumerate(issues, 1):
        print(f" {i}. {issue}")
    print("note_issues=", issues_path)

    # Show how the user prompt was grouped (findings ↔ candidates).
    user_prompt = ""
    if messages:
        for msg in messages:
            if msg.get("role") == "user":
                user_prompt = msg.get("content") or ""
                break
    if "CURRENT INSPECTION FINDINGS" in user_prompt or "CURRENT FINDINGS" in user_prompt:
        print("\n=== PROMPT FINDINGS / CANDIDATES (excerpt) ===")
        # Print from findings header through first ~2500 chars of that block.
        start = user_prompt.find("CURRENT INSPECTION FINDINGS")
        if start < 0:
            start = user_prompt.find("CURRENT FINDINGS")
        excerpt = user_prompt[start : start + 2500]
        print(excerpt)
        if len(user_prompt) - start > 2500:
            print("... [truncated]")

    print("\n=== RETRIEVED SPs (flat manifest hits) ===", len(hits), ("(ALL section SPs)" if args.all_sps else ""))
    for i, h in enumerate(hits[:20], 1):
        preview = (h.text or "").replace("\n", " ")[:120]
        if args.all_sps:
            print(f" {i}. idx={h.paragraph_index} {preview!r}")
        else:
            print(f" {i}. cosine={getattr(h, 'score', 0) or 0:.3f} fusion={getattr(h, 'fusion_score', 0) or 0:.4f} {preview!r}")
    if len(hits) > 20:
        print(f" ... +{len(hits) - 20} more")

    print("\n=== GENERATED ===")
    print("style_sample_count=", style_sample_count)
    print("llm_usage=", llm_usage)
    print(text or "(empty)")

    print("\nretrieval=", ret_path)
    sample = (
        _ROOT
        / "backend"
        / "standard_paragraphs"
        / "samples"
        / f"{draft_id}.e2e.json"
    )
    payload = {
        "draft_id": draft_id,
        "section_id": sid,
        "section_title": title,
        "observations": observations,
        "retrieval_issues": issues,
        "retrieved_chunk_count": len(hits),
        "use_all_section_sps": args.all_sps,
        "generated_text": text,
        "note_issues_path": str(issues_path),
        "retrieval_path": str(ret_path),
    }
    sample.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print("sample copy=", sample)
    return 0 if text.strip() else 2


if __name__ == "__main__":
    raise SystemExit(main())
