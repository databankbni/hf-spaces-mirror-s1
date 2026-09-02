"""Evaluate a past-report D2/D4 draft (retrieval manifest + coverage JSON).

Uses the same explicit per-section CASES as ``run_past_d2_d4_generate.py``.
For coverage judging, each locked note blob is split into sentences so missing
facts are visible at atom level (same messy-note atoms as the SP e2e eval).

Example:
  python scripts/run_past_d2_d4_eval.py past-e2e-d2-d4-20260802-120000
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.evaluation import evaluate_report, evaluation_manifest_path
from backend.evaluation.models import SectionEvalInput
from backend.models.report import GeneratedSection, ReportResult
from backend.storage import retrieval_manifest


def _load_cases() -> tuple[list[dict], str]:
    path = _ROOT / "scripts" / "run_past_d2_d4_generate.py"
    spec = importlib.util.spec_from_file_location("run_past_d2_d4_generate", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(mod.CASES), str(mod.TENANT)


CASES, TENANT = _load_cases()


def _atomic_notes(observations: list[str]) -> list[str]:
    """Split locked blobs into sentence atoms for coverage judging."""
    out: list[str] = []
    for blob in observations:
        parts = re.split(r"(?<=[.!?])\s+", (blob or "").strip())
        for p in parts:
            text = p.strip()
            if text:
                out.append(text)
    return out or list(observations)


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


async def main() -> int:
    draft_id = sys.argv[1] if len(sys.argv) > 1 else ""
    if not draft_id:
        print("Usage: python scripts/run_past_d2_d4_eval.py <draft_id>")
        return 1

    cases_by_id = {c["section_id"].upper(): c for c in CASES}
    mpath = retrieval_manifest.retrieval_manifest_path(TENANT, draft_id)
    if not mpath.is_file():
        print("retrieval manifest missing:", mpath)
        return 1

    data = json.loads(mpath.read_text(encoding="utf-8"))
    print("draft=", draft_id)
    print("retrieval_manifest=", mpath)

    sections: list[GeneratedSection] = []
    section_inputs: list[SectionEvalInput] = []
    generated: dict[str, str] = {}
    atoms_by_sid: dict[str, list[str]] = {}

    for sid in ("D2", "D4"):
        case = cases_by_id[sid]
        sec = (data.get("sections") or {}).get(sid) or {}
        text = (sec.get("generated_text") or "").strip()
        if not text:
            docs = _ROOT / "docs" / f"{draft_id}-output.json"
            if docs.is_file():
                payload = json.loads(docs.read_text(encoding="utf-8"))
                for row in payload.get("sections") or []:
                    if row.get("section_id") == sid:
                        text = (row.get("generated_text") or row.get("text") or "").strip()
        generated[sid] = text
        atoms = _atomic_notes(list(case["observations"]))
        atoms_by_sid[sid] = atoms
        title = case["section_title"]
        print(f"\n{sid}: generated chars={len(text)} note_atoms={len(atoms)}")
        sections.append(GeneratedSection(section_id=sid, title=title, text=text))
        section_inputs.append(
            SectionEvalInput(
                section_id=sid,
                title=title,
                observations=atoms,
                generated_text=text,
                baseline_text=(sec.get("baseline_text") or ""),
            )
        )

    report = ReportResult(tenant_id=TENANT, schema_version=2, sections=sections)
    evaluation = await evaluate_report(
        report,
        report_id=draft_id,
        section_inputs=section_inputs,
    )
    if evaluation is None:
        print("evaluation disabled or returned None")
        return 2

    print("\n========== EVALUATION ==========")
    print("status=", evaluation.status)
    print("coverage_rate=", _pct(evaluation.coverage_rate))
    print(
        "covered/total=",
        evaluation.covered_note_atoms,
        "/",
        evaluation.total_note_atoms,
    )
    print("faithfulness=", _pct(evaluation.faithfulness_score))
    print("model=", evaluation.model)
    print("error=", evaluation.error)

    for sec in evaluation.sections:
        print(f"\n--- {sec.section_id} coverage={_pct(sec.coverage_rate)} ---")
        for j in sec.note_judgments or []:
            print(f"  [{j.status}] {j.note}")
            if j.evidence:
                print(f"           evidence: {j.evidence[:160]}")
        if sec.missing_facts:
            print("  missing_facts=", sec.missing_facts)

    epath = evaluation_manifest_path(TENANT, draft_id)
    print("\nevaluation_manifest=", epath)

    summary = {
        "draft_id": draft_id,
        "tenant_id": TENANT,
        "knowledge_source": "past_report",
        "router_bypassed": True,
        "retrieval_manifest": str(mpath),
        "evaluation_manifest": str(epath),
        "sections": {
            sid: {
                "observations": list(cases_by_id[sid]["observations"]),
                "note_atoms": atoms_by_sid[sid],
                "generated_text": generated[sid],
            }
            for sid in ("D2", "D4")
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
                        {
                            "note": j.note,
                            "status": j.status,
                            "evidence": j.evidence,
                        }
                        for j in (s.note_judgments or [])
                    ],
                    "missing_facts": s.missing_facts,
                }
                for s in evaluation.sections
            },
        },
    }
    out = _ROOT / "docs" / f"{draft_id}.e2e_eval.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print("sample copy=", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
