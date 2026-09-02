"""Generate past + SP for latest D1/D4 house notes, merge with prompt v2.

Usage (typical):
  MAPPING_MODEL=gpt-5.6-luna MERGE_AGENT_MODEL=gpt-5.6-luna \\
  MAPPING_TEMPERATURE=0.2 STANDARD_PARAGRAPHS_TEMPERATURE=0.2 \\
  MERGE_AGENT_TEMPERATURE=0.2 \\
  python scripts/run_d1_d4_dual_path_merge_v2.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.config import settings
from backend.domain import template_discoverer
from backend.domain.interference import GenerationPolicy
from backend.domain.notes.survey_notes import build_property_context, parse_notes
from backend.domain.rics_level3_schema import (
    mapping_units_for_parent,
    ordered_parent_sections,
)
from backend.merge_agent import (
    DualPathDraft,
    merge_dual_path_drafts,
    source_names_from_chunks,
    source_names_from_manifest_section,
    write_sources_file,
)
from backend.models.section import SectionNote
from backend.pipeline import section_mapper
from backend.rag.types import (
    KNOWLEDGE_SOURCE_PAST_REPORT,
    KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH,
)
from backend.standard_paragraphs.generate import generate_from_standard_paragraphs
from backend.storage import retrieval_manifest

TENANT = "khanchaudhry3@gmail.com"
OUT_ROOT = _ROOT / "docs" / "dual-path-merge-runs"
PROMPT_VERSION = "v2"

SECTIONS: dict[str, dict[str, str]] = {
    "D1": {
        "title": "Chimney stacks",
        "notes": (
            "The chimney stack is of brick, with chimney pots. Clay pots show "
            "signs of cracking and spalling. TV aerial attach was okay. "
            "Chimney was reasonably aligned. Flaunchings have cracked. "
            "Back guters not seen."
        ),
    },
    "D4": {
        "title": "Main walls",
        "notes": (
            "The main walls are of solid construction, approximately 285 mm "
            "thick. The damp-proof course is concealed. External ground levels "
            "appear to be at an adequate height in relation to the internal "
            "floor level.\n\n"
            "The rendered wall surfaces show evidence of cracking. The window "
            "sills and surrounds have been rendered and painted, and cracking "
            "was also noted in these areas. The gaps where the doors and "
            "windows abut the main walls have been sealed with mortar fillets, "
            "which also exhibit cracking. A \n\n"
            "movement-related crack was noted to the front bay. The cracks "
            "measured less than 5 mm in width. However, future movement cannot "
            "be ruled out. Please give the 4 options regarding the "
            "implications of the observed structural movement."
        ),
    },
}


def _clean(text: str) -> str:
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    while "\n\n\n" in t:
        t = t.replace("\n\n\n", "\n\n")
    return t.strip() + ("\n" if t.strip() else "")


def _id_to_unit(schema):
    return {
        sec.id: sec
        for parent in ordered_parent_sections(schema)
        for sec in mapping_units_for_parent(schema, parent.id)
    }


async def _generate_past(
    *,
    sid: str,
    notes: str,
    schema,
    id_to_unit,
    property_context: dict,
    policy: GenerationPolicy,
    draft_id: str,
) -> dict:
    observations = [notes.strip()]
    note = SectionNote(
        section_id=sid,
        raw_observations=list(observations),
        text=notes.strip(),
    )
    section, unmatched = await section_mapper._process_one_section(
        sid,
        schema=schema,
        tenant_id=TENANT,
        by_id={sid: note},
        id_to_unit=id_to_unit,
        report_draft_id=f"{draft_id}-past",
        interference_level=policy.interference_level,
        retrieval_level="paragraph",
        allowed_doc_keys=None,
        property_context=property_context,
        policy=policy,
        knowledge_source=KNOWLEDGE_SOURCE_PAST_REPORT,
    )
    text = _clean(section.text or "")
    manifest = str(
        retrieval_manifest.retrieval_manifest_path(TENANT, f"{draft_id}-past")
    )
    sources = source_names_from_manifest_section(manifest, sid)
    return {
        "status": section.status,
        "generated_text": text,
        "unmatched": list(unmatched or []),
        "manifest": manifest,
        "sources": sources,
    }


def _generate_sp(
    *,
    sid: str,
    title: str,
    notes: str,
    schema,
    draft_id: str,
) -> dict:
    observations = [notes.strip()]
    text, hits, messages, guidance, issues, llm_usage, style_sample_count = (
        generate_from_standard_paragraphs(
            tenant_id=TENANT,
            schema=schema,
            section_id=sid,
            section_title=title,
            observations=observations,
            candidate_ids=[sid],
            force_decompose=True,
            force_decompose_llm=True,
            use_all_section_sps=False,
            style_samples_enabled=False,
        )
    )
    retrieval_manifest.record_section_retrieval(
        TENANT,
        f"{draft_id}-sp",
        section_id=sid,
        section_title=title,
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
        "hit_count": len(hits),
        "findings": list(issues or []),
        "llm_usage": llm_usage,
        "manifest": str(
            retrieval_manifest.retrieval_manifest_path(TENANT, f"{draft_id}-sp")
        ),
        "sources": sources,
    }


async def main() -> int:
    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    run_id = f"d1-d4-dual-path-merge-v2-luna-t0p2-{stamp}"
    out_dir = OUT_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    schema = template_discoverer.ensure_canonical_schema(TENANT)
    id_to_unit = _id_to_unit(schema)
    property_context = build_property_context(
        parse_notes(SECTIONS["D1"]["notes"]),
        property_type="house",
        tenure="freehold",
    )
    policy = GenerationPolicy.resolve("assist", 3)

    merge_model = (settings.merge_agent_model or "").strip() or settings.mapping_model
    print("run_id=", run_id)
    print("tenant=", TENANT)
    print("mapping_model=", settings.mapping_model)
    print("mapping_temperature=", settings.mapping_temperature)
    print("sp_temperature=", settings.standard_paragraphs_temperature)
    print("merge_model=", merge_model)
    print("merge_temperature=", settings.merge_agent_temperature)
    print("merge_prompt_version=", PROMPT_VERSION, "(forced)")

    section_results: list[dict] = []

    for sid in ("D1", "D4"):
        meta = SECTIONS[sid]
        title = meta["title"]
        notes = meta["notes"]
        print(f"\n{'=' * 72}\nSECTION {sid} — {title}\n{'=' * 72}")

        print("--- past_report ---")
        past = await _generate_past(
            sid=sid,
            notes=notes,
            schema=schema,
            id_to_unit=id_to_unit,
            property_context=property_context,
            policy=policy,
            draft_id=run_id,
        )
        print(
            "status=",
            past["status"],
            "chars=",
            len(past["generated_text"]),
            "words=",
            len(past["generated_text"].split()),
        )

        print("--- standard_paragraph ---")
        sp = await asyncio.to_thread(
            _generate_sp,
            sid=sid,
            title=title,
            notes=notes,
            schema=schema,
            draft_id=run_id,
        )
        print(
            "status=",
            sp["status"],
            "chars=",
            len(sp["generated_text"]),
            "words=",
            len(sp["generated_text"].split()),
        )

        print("--- merge v2 ---")
        draft = DualPathDraft(
            section_id=sid,
            section_title=title,
            past_report_draft=past["generated_text"],
            standard_paragraph_draft=sp["generated_text"],
            past_report_source=f"{run_id}-past",
            standard_paragraph_source=f"{run_id}-sp",
            inspection_notes=notes,
        )
        merged = merge_dual_path_drafts(
            draft,
            prompt_version=PROMPT_VERSION,
            temperature=float(settings.merge_agent_temperature),
            model=merge_model,
        )
        merged_text = _clean(merged.merged_text or "")
        print(
            "status=",
            merged.meta.get("status"),
            "prompt_version=",
            merged.meta.get("prompt_version"),
            "chars=",
            len(merged_text),
            "words=",
            len(merged_text.split()),
        )

        sec_dir = out_dir / sid.lower()
        sec_dir.mkdir(parents=True, exist_ok=True)
        (sec_dir / "inspection_notes.txt").write_text(_clean(notes), encoding="utf-8")
        (sec_dir / "past_report_draft.txt").write_text(
            past["generated_text"], encoding="utf-8"
        )
        (sec_dir / "standard_paragraph_draft.txt").write_text(
            sp["generated_text"], encoding="utf-8"
        )
        (sec_dir / "merged.txt").write_text(merged_text, encoding="utf-8")
        past_sources = list(past.get("sources") or [])
        sp_sources = list(sp.get("sources") or [])
        write_sources_file(
            sec_dir / "past_report_sources.txt",
            past_sources,
            header="Past-report retrieval sources (PDFs / docs)",
        )
        write_sources_file(
            sec_dir / "standard_paragraph_sources.txt",
            sp_sources,
            header="Standard-paragraph retrieval sources",
        )
        past_sources_block = (
            "\n".join(f"{i}. {n}" for i, n in enumerate(past_sources, 1)) or "(none)"
        )
        sp_sources_block = (
            "\n".join(f"{i}. {n}" for i, n in enumerate(sp_sources, 1)) or "(none)"
        )
        (sec_dir / "readable.txt").write_text(
            (
                f"SECTION {sid} — {title}\n"
                f"mapping_model={settings.mapping_model} "
                f"temp={settings.mapping_temperature}\n"
                f"sp_temp={settings.standard_paragraphs_temperature}\n"
                f"merge_model={merged.model} "
                f"merge_temp={settings.merge_agent_temperature} "
                f"prompt_version={merged.meta.get('prompt_version')}\n"
                f"past_status={past['status']}  sp_status={sp['status']}  "
                f"merge={merged.meta.get('status')}\n\n"
                f"===== INSPECTION NOTES =====\n\n{_clean(notes)}\n"
                f"===== PAST-REPORT SOURCES =====\n\n{past_sources_block}\n\n"
                f"===== STANDARD-PARAGRAPH SOURCES =====\n\n{sp_sources_block}\n\n"
                f"===== PAST-REPORT DRAFT =====\n\n{past['generated_text']}\n"
                f"===== STANDARD-PARAGRAPH DRAFT =====\n\n{sp['generated_text']}\n"
                f"===== MERGED (v2) =====\n\n{merged_text}"
            ),
            encoding="utf-8",
        )
        section_results.append(
            {
                "section_id": sid,
                "section_title": title,
                "past": {
                    "status": past["status"],
                    "chars": len(past["generated_text"].strip()),
                    "words": len(past["generated_text"].split()),
                    "manifest": past.get("manifest"),
                    "sources": past_sources,
                },
                "standard_paragraph": {
                    "status": sp["status"],
                    "chars": len(sp["generated_text"].strip()),
                    "words": len(sp["generated_text"].split()),
                    "hit_count": sp.get("hit_count"),
                    "manifest": sp.get("manifest"),
                    "sources": sp_sources,
                },
                "merge": {
                    "status": merged.meta.get("status"),
                    "prompt_version": merged.meta.get("prompt_version"),
                    "model": merged.model,
                    "chars": len(merged_text.strip()),
                    "words": len(merged_text.split()),
                    "llm_usage": merged.llm_usage,
                },
            }
        )

    meta = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tenant_id": TENANT,
        "property_type": "house",
        "sections_requested": ["D1", "D4"],
        "models": {
            "mapping_model": settings.mapping_model,
            "mapping_temperature": settings.mapping_temperature,
            "standard_paragraphs_temperature": settings.standard_paragraphs_temperature,
            "merge_agent_model": merge_model,
            "merge_agent_temperature": settings.merge_agent_temperature,
            "merge_agent_prompt_version": PROMPT_VERSION,
        },
        "note": (
            "Fresh past + SP generate for latest D1/D4 house notes, "
            "merged with prompt v2 (notes-gated)."
        ),
        "sections": section_results,
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    compare = [
        f"D1/D4 dual-path merge v2: {run_id}",
        meta["note"],
        f"model={settings.mapping_model} temp={settings.mapping_temperature} "
        f"merge_prompt={PROMPT_VERSION}",
        "",
    ]
    for r in section_results:
        compare.append(
            f"{r['section_id']}: past={r['past']['status']} "
            f"chars={r['past']['chars']} | "
            f"sp={r['standard_paragraph']['status']} "
            f"chars={r['standard_paragraph']['chars']} | "
            f"merge={r['merge']['status']} "
            f"v={r['merge']['prompt_version']} "
            f"chars={r['merge']['chars']} → {r['section_id'].lower()}/"
        )
    (out_dir / "COMPARE.txt").write_text("\n".join(compare) + "\n", encoding="utf-8")
    print(f"\nWrote {out_dir}")
    print("compare=", out_dir / "COMPARE.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
