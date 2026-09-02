"""Reuse 3 past-report D2 drafts (staining), generate 3 SP drafts, merge each.

Uses the updated D2 house notes (Building regulations + Distening).
Expects env: MAPPING_MODEL / STANDARD_PARAGRAPHS model via mapping_model,
temps 0.2, MERGE_AGENT_MODEL=gpt-5.6-luna.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.config import settings
from backend.domain import template_discoverer
from backend.merge_agent import (
    DualPathDraft,
    merge_dual_path_drafts,
    source_names_from_chunks,
    write_sources_file,
)
from backend.rag.types import KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH
from backend.standard_paragraphs.generate import generate_from_standard_paragraphs
from backend.storage import retrieval_manifest

TENANT = "khanchaudhry3@gmail.com"
SECTION_ID = "D2"
SECTION_TITLE = "Roof coverings"
OUT_ROOT = _ROOT / "docs" / "dual-path-merge-runs"

NOTES = (
    "The roof is a pitched with interlocking concrete tiles. The roof has been "
    "replaced. The date of this replacement could not be confirmed. Talk about "
    "Building regulations.Parapet walls have been rendered and the render showed "
    "cracks. Distening was observed to the parapet walls below coping stones. "
    "Flashings at the abutments of parapet walls and roof are lead. Some sections "
    "have been lifted, creating gaps. The mortar bed into the ridge tiles is "
    "deteriorated. There is some moss and lichen growth. The main roof covering "
    "is serviceable order and no deflection."
)

# 2nd–4th of the four Luna@0.2 runs (skip Distening keep: …170833).
PAST_DRAFTS = [
    _ROOT
    / "docs"
    / "past-d2-house-runs"
    / "past-d2-house-t0p2-20260808-171111"
    / "generated.txt",
    _ROOT
    / "docs"
    / "past-d2-house-runs"
    / "past-d2-house-t0p2-20260808-171117"
    / "generated.txt",
    _ROOT
    / "docs"
    / "past-d2-house-runs"
    / "past-d2-house-t0p2-20260808-171123"
    / "generated.txt",
]


def _clean(text: str) -> str:
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    while "\n\n\n" in t:
        t = t.replace("\n\n\n", "\n\n")
    return t.strip() + ("\n" if t.strip() else "")


def _generate_sp(*, draft_id: str, schema) -> dict:
    observations = [NOTES.strip()]
    text, hits, messages, guidance, issues, llm_usage, style_sample_count = (
        generate_from_standard_paragraphs(
            tenant_id=TENANT,
            schema=schema,
            section_id=SECTION_ID,
            section_title=SECTION_TITLE,
            observations=observations,
            candidate_ids=[SECTION_ID],
            force_decompose=True,
            force_decompose_llm=True,
            use_all_section_sps=False,
            style_samples_enabled=False,
        )
    )
    retrieval_manifest.record_section_retrieval(
        TENANT,
        f"{draft_id}-sp",
        section_id=SECTION_ID,
        section_title=SECTION_TITLE,
        observations=observations,
        baseline_text=guidance or "",
        hits=hits,
        status="MAPPED" if (text or "").strip() else "NO_RAG_MATCH",
        prompt_messages=messages,
        retrieved_count=len(hits),
        prompt_chunk_count=len(hits),
        knowledge_source=KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH,
        generated_text=text or "",
        retrieval_issues=list(issues or []),
        llm_usage=llm_usage,
        style_sample_count=style_sample_count,
    )
    sources = source_names_from_chunks(
        [
            {
                "source_filename": getattr(h, "source_filename", "") or "",
                "doc_id": getattr(h, "doc_id", "") or "",
                "paragraph_index": getattr(h, "paragraph_index", None),
            }
            for h in (hits or [])
        ],
        unique=False,
        include_paragraph_index=True,
    )
    return {
        "status": "MAPPED" if (text or "").strip() else "NO_RAG_MATCH",
        "generated_text": _clean(text or ""),
        "sources": sources,
        "findings": list(issues or []),
        "llm_usage": llm_usage,
    }


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_id = f"d2-triple-sp-merge-luna-t0p2-{stamp}"
    out_dir = OUT_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    schema = template_discoverer.ensure_canonical_schema(TENANT)
    merge_model = (settings.merge_agent_model or "").strip() or settings.mapping_model

    print("run_id=", run_id)
    print("mapping_model=", settings.mapping_model)
    print("mapping_temperature=", settings.mapping_temperature)
    print("sp_temperature=", settings.standard_paragraphs_temperature)
    print("merge_model=", merge_model)
    print("merge_temperature=", settings.merge_agent_temperature)

    summary: list[dict] = []

    for i, past_path in enumerate(PAST_DRAFTS, start=1):
        sample_dir = out_dir / f"sample_{i}"
        sample_dir.mkdir(parents=True, exist_ok=True)

        past_text = _clean(past_path.read_text(encoding="utf-8"))
        if "distening" in past_text.lower():
            raise SystemExit(f"Past draft still has Distening: {past_path}")

        print(f"\n{'=' * 72}\nSAMPLE {i}/3\n{'=' * 72}")
        print("past=", past_path.parent.name, "words=", len(past_text.split()))

        (sample_dir / "inspection_notes.txt").write_text(
            _clean(NOTES), encoding="utf-8"
        )
        (sample_dir / "past_report_draft.txt").write_text(past_text, encoding="utf-8")
        (sample_dir / "past_report_source.txt").write_text(
            str(past_path) + "\n", encoding="utf-8"
        )

        print("--- standard_paragraph ---")
        sp = _generate_sp(draft_id=f"{run_id}-s{i}", schema=schema)
        sp_text = sp["generated_text"]
        print("sp status=", sp["status"], "words=", len(sp_text.split()))
        (sample_dir / "standard_paragraph_draft.txt").write_text(
            sp_text, encoding="utf-8"
        )
        write_sources_file(
            sample_dir / "standard_paragraph_sources.txt",
            sp["sources"],
            header="STANDARD PARAGRAPH SOURCES",
        )

        print("--- merge ---")
        draft = DualPathDraft(
            section_id=SECTION_ID,
            section_title=SECTION_TITLE,
            inspection_notes=NOTES.strip(),
            past_report_draft=past_text,
            standard_paragraph_draft=sp_text,
        )
        merged = merge_dual_path_drafts(draft)
        merged_text = _clean(merged.merged_text or "")
        merge_status = merged.meta.get("status")
        print(
            "merge status=",
            merge_status,
            "model=",
            merged.model,
            "words=",
            len(merged_text.split()),
        )
        (sample_dir / "merged.txt").write_text(merged_text, encoding="utf-8")
        (sample_dir / "readable.txt").write_text(
            (
                f"SAMPLE {i}/3  run={run_id}\n"
                f"past_source={past_path.parent.name}\n"
                f"mapping_model={settings.mapping_model} "
                f"temp={settings.mapping_temperature}\n"
                f"sp_temp={settings.standard_paragraphs_temperature}\n"
                f"merge_model={merged.model} "
                f"merge_temp={settings.merge_agent_temperature}\n"
                f"merge_status={merge_status}\n"
                f"{'=' * 72}\n"
                f"INSPECTION NOTES\n{'=' * 72}\n\n"
                f"{_clean(NOTES)}\n"
                f"{'=' * 72}\n"
                f"PAST REPORT DRAFT\n{'=' * 72}\n\n"
                f"{past_text}\n"
                f"{'=' * 72}\n"
                f"STANDARD PARAGRAPH DRAFT\n{'=' * 72}\n\n"
                f"{sp_text}\n"
                f"{'=' * 72}\n"
                f"MERGED\n{'=' * 72}\n\n"
                f"{merged_text}"
            ),
            encoding="utf-8",
        )

        row = {
            "sample": i,
            "past_source": past_path.parent.name,
            "past_words": len(past_text.split()),
            "sp_status": sp["status"],
            "sp_words": len(sp_text.split()),
            "merge_status": merge_status,
            "merge_model": merged.model,
            "merged_words": len(merged_text.split()),
            "dir": str(sample_dir),
        }
        summary.append(row)
        (sample_dir / "meta.json").write_text(
            json.dumps(row, indent=2) + "\n", encoding="utf-8"
        )

    meta = {
        "run_id": run_id,
        "tenant_id": TENANT,
        "section_id": SECTION_ID,
        "mapping_model": settings.mapping_model,
        "mapping_temperature": settings.mapping_temperature,
        "standard_paragraphs_temperature": settings.standard_paragraphs_temperature,
        "merge_agent_model": merge_model,
        "merge_agent_temperature": settings.merge_agent_temperature,
        "samples": summary,
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    compare_lines = [
        f"run_id={run_id}",
        f"model={settings.mapping_model} temp={settings.mapping_temperature}",
        f"merge_model={merge_model} merge_temp={settings.merge_agent_temperature}",
        "",
    ]
    for row in summary:
        compare_lines.append(
            f"sample_{row['sample']}: past={row['past_source']} "
            f"sp_words={row['sp_words']} merged_words={row['merged_words']} "
            f"status={row['merge_status']}"
        )
        compare_lines.append(f"  dir={row['dir']}")
    (out_dir / "COMPARE.txt").write_text("\n".join(compare_lines) + "\n", encoding="utf-8")
    print("\nout_dir=", out_dir)
    print("compare=", out_dir / "COMPARE.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
