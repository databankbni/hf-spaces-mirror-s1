"""Run SP generate + coverage evaluation for D2 and D4 messy notes."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.evaluation import evaluate_report, evaluation_manifest_path
from backend.evaluation.models import SectionEvalInput
from backend.models.report import GeneratedSection, ReportResult
from scripts.test_sp_decompose_generate import (
    CASES,
    DEFAULT_TENANT,
    _case_for,
)
from backend.domain import template_discoverer
from backend.standard_paragraphs.generate import generate_from_standard_paragraphs
from backend.standard_paragraphs.note_issues_manifest import record_note_issues
from backend.storage import retrieval_manifest

DRAFT_ID = (
    "sp-e2e-d2-d4-"
    + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
)
SECTIONS = ("D2", "D4")
_STYLE_SAMPLES = "--style-samples" in sys.argv


def _run_section(sid: str) -> dict:
    case = _case_for(sid)
    title = case["section_title"]
    observations = list(case["observations"])
    schema = template_discoverer.ensure_canonical_schema(DEFAULT_TENANT)
    text, hits, messages, guidance, issues, llm_usage, style_sample_count = (
        generate_from_standard_paragraphs(
            tenant_id=DEFAULT_TENANT,
            schema=schema,
            section_id=sid,
            section_title=title,
            observations=observations,
            candidate_ids=[sid],
            force_decompose=True,
            force_decompose_llm=True,
            use_all_section_sps=False,
            style_samples_enabled=True if _STYLE_SAMPLES else None,
        )
    )
    record_note_issues(
        DEFAULT_TENANT,
        DRAFT_ID,
        section_id=sid,
        section_title=title,
        observations=observations,
        issues=list(issues),
        source="e2e_d2_d4_eval",
        used_llm=True,
    )
    retrieval_manifest.record_section_retrieval(
        DEFAULT_TENANT,
        DRAFT_ID,
        section_id=sid,
        section_title=title,
        observations=observations,
        baseline_text=guidance,
        hits=hits,
        status="MAPPED" if text.strip() else "NO_RAG_MATCH",
        prompt_messages=messages,
        retrieved_count=len(hits),
        prompt_chunk_count=len(hits),
        knowledge_source="standard_paragraph",
        generated_text=text,
        retrieval_issues=list(issues),
        llm_usage=llm_usage,
        style_sample_count=style_sample_count,
    )
    return {
        "section_id": sid,
        "title": title,
        "observations": observations,
        "findings": list(issues),
        "hit_count": len(hits),
        "generated_text": text,
        "llm_usage": llm_usage,
        "style_sample_count": style_sample_count,
    }


async def _evaluate(results: list[dict]):
    # Prefer decomposed findings for coverage (atomic notes); fall back to blob.
    section_inputs = []
    sections = []
    for r in results:
        obs = r["findings"] or r["observations"]
        sections.append(
            GeneratedSection(
                section_id=r["section_id"],
                title=r["title"],
                text=r["generated_text"] or "",
            )
        )
        section_inputs.append(
            SectionEvalInput(
                section_id=r["section_id"],
                title=r["title"],
                observations=obs,
                generated_text=r["generated_text"] or "",
                baseline_text="",
            )
        )
    report = ReportResult(
        tenant_id=DEFAULT_TENANT,
        schema_version=2,
        sections=sections,
    )
    return await evaluate_report(
        report,
        report_id=DRAFT_ID,
        section_inputs=section_inputs,
    )


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


async def main() -> int:
    print("draft=", DRAFT_ID)
    print("tenant=", DEFAULT_TENANT)
    print("style_samples=", _STYLE_SAMPLES)
    results = []
    for sid in SECTIONS:
        print(f"\n========== GENERATE {sid} ==========")
        r = _run_section(sid)
        results.append(r)
        print("findings=", len(r["findings"]))
        for i, f in enumerate(r["findings"], 1):
            print(f"  {i}. {f}")
        print("retrieved_hits=", r["hit_count"])
        print("style_sample_count=", r.get("style_sample_count"))
        print("llm_usage=", r.get("llm_usage"))
        print("generated_text=\n", r["generated_text"])

    print("\n========== EVALUATION ==========")
    evaluation = await _evaluate(results)
    if evaluation is None:
        print("evaluation disabled")
        return 1

    print("status=", evaluation.status)
    print("coverage_rate=", _pct(evaluation.coverage_rate))
    print("covered/total=", evaluation.covered_note_atoms, "/", evaluation.total_note_atoms)
    print("faithfulness=", _pct(evaluation.faithfulness_score))
    print("model=", evaluation.model)
    print("error=", evaluation.error)

    for sec in evaluation.sections:
        print(f"\n--- {sec.section_id} coverage={_pct(sec.coverage_rate)} ---")
        print("observations judged=", len(sec.observations))
        for j in sec.note_judgments or []:
            print(f"  [{j.status}] {j.note}")
            if j.evidence:
                print(f"           evidence: {j.evidence[:120]}")
        if sec.missing_facts:
            print("  missing_facts=", sec.missing_facts)
        if sec.error:
            print("  error=", sec.error)

    path = evaluation_manifest_path(DEFAULT_TENANT, DRAFT_ID)
    print("\nevaluation_manifest=", path)
    print("retrieval_manifest=", retrieval_manifest.retrieval_manifest_path(DEFAULT_TENANT, DRAFT_ID))

    summary = {
        "draft_id": DRAFT_ID,
        "sections": {
            r["section_id"]: {
                "findings": r["findings"],
                "hit_count": r["hit_count"],
                "generated_text": r["generated_text"],
            }
            for r in results
        },
        "evaluation": {
            "status": evaluation.status,
            "coverage_rate": evaluation.coverage_rate,
            "covered_note_atoms": evaluation.covered_note_atoms,
            "total_note_atoms": evaluation.total_note_atoms,
            "faithfulness_score": evaluation.faithfulness_score,
            "per_section": {
                s.section_id: {
                    "coverage_rate": s.coverage_rate,
                    "judgments": [
                        {"note": j.note, "status": j.status, "evidence": j.evidence}
                        for j in (s.note_judgments or [])
                    ],
                    "missing_facts": s.missing_facts,
                }
                for s in evaluation.sections
            },
        },
    }
    out = (
        _ROOT
        / "backend"
        / "standard_paragraphs"
        / "samples"
        / f"{DRAFT_ID}.e2e_eval.json"
    )
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print("sample copy=", out)
    return 0


if __name__ == "__main__":
    # Ensure CASES module is loaded (D2/D4 notes updated in test_sp_decompose_notes).
    _ = CASES
    raise SystemExit(asyncio.run(main()))
