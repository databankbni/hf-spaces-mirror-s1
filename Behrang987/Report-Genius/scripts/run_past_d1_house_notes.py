"""Past-report D1 (Chimney stacks) generate with property_type=house.

Runs two generations back-to-back and writes clean plaintext under
docs/past-d1-house-runs/ plus COMPARE_latest_two.txt.
"""

from __future__ import annotations

import asyncio
import json
import os
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
from backend.models.section import SectionNote
from backend.pipeline import section_mapper
from backend.rag.retriever import retrieve_past_report_baselines_hybrid
from backend.rag.types import KNOWLEDGE_SOURCE_PAST_REPORT
from backend.storage import retrieval_manifest

TENANT = "khanchaudhry3@gmail.com"
SECTION_ID = "D1"
SECTION_TITLE = "Chimney stacks"
OUT_DIR = _ROOT / "docs" / "past-d1-house-runs"
RUNS = int(os.environ.get("PAST_HOUSE_RUNS", "2"))

NOTES = """The chimney stack is of brick, with chimney pots. Clay pots show signs of cracking and spalling. TV aerial attach was okay. Chimney was reasonably aligned."""


def _clean_prose(text: str) -> str:
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    while "\n\n\n" in t:
        t = t.replace("\n\n\n", "\n\n")
    return t.strip() + "\n"


def _write_run_bundle(
    *,
    draft_id: str,
    notes: str,
    generated: str,
    status: str,
    unmatched: list,
    sources: list[str],
    blocks_meta: list[dict],
    manifest_path: Path,
) -> Path:
    run_dir = OUT_DIR / draft_id
    run_dir.mkdir(parents=True, exist_ok=True)

    notes_clean = _clean_prose(notes)
    gen_clean = _clean_prose(generated)

    (run_dir / "inspection_notes.txt").write_text(notes_clean, encoding="utf-8")
    (run_dir / "generated.txt").write_text(gen_clean, encoding="utf-8")
    (run_dir / "retrieved_sources.txt").write_text(
        "\n".join(f"{i}. {n}" for i, n in enumerate(sources, 1))
        + ("\n" if sources else ""),
        encoding="utf-8",
    )

    meta = {
        "draft_id": draft_id,
        "tenant_id": TENANT,
        "property_type": "house",
        "section_id": SECTION_ID,
        "status": status,
        "unmatched": unmatched,
        "retrieved_count": len(sources),
        "retrieved_sources": sources,
        "char_counts": {
            "inspection_notes": len(notes_clean),
            "generated": len(gen_clean),
            "generated_words": len(gen_clean.split()),
        },
        "ranking_preview": blocks_meta,
        "manifest": str(manifest_path),
    }
    (run_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (run_dir / "readable.txt").write_text(
        (
            f"DRAFT: {draft_id}\n"
            f"STATUS: {status}\n"
            f"WORDS: {len(gen_clean.split())}  CHARS: {len(gen_clean)}\n"
            f"{'=' * 72}\n"
            f"INSPECTION NOTES\n"
            f"{'=' * 72}\n\n"
            f"{notes_clean}\n"
            f"{'=' * 72}\n"
            f"GENERATED {SECTION_ID}\n"
            f"{'=' * 72}\n\n"
            f"{gen_clean}"
        ),
        encoding="utf-8",
    )
    (_ROOT / "docs" / f"{draft_id}-generated.txt").write_text(
        gen_clean, encoding="utf-8"
    )
    return run_dir


def _write_compare_latest_two() -> Path | None:
    recent = sorted(
        (p for p in OUT_DIR.glob("past-d1-house-*/generated.txt") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
    )
    if len(recent) < 2:
        return None
    a, b = recent[-2], recent[-1]
    path = OUT_DIR / "COMPARE_latest_two.txt"
    path.write_text(
        (
            f"OLDER: {a.parent.name}\n"
            f"{'=' * 72}\n\n"
            f"{a.read_text(encoding='utf-8')}\n"
            f"{'=' * 72}\n"
            f"NEWER: {b.parent.name}\n"
            f"{'=' * 72}\n\n"
            f"{b.read_text(encoding='utf-8')}"
        ),
        encoding="utf-8",
    )
    return path


async def _one_generation(schema, id_to_unit, property_context, policy) -> str:
    temp_tag = f"t{settings.mapping_temperature:g}".replace(".", "p")
    draft_id = (
        "past-d1-house-"
        + temp_tag
        + "-"
        + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    )
    while (OUT_DIR / draft_id).exists():
        await asyncio.sleep(1.1)
        draft_id = (
            "past-d1-house-"
            + temp_tag
            + "-"
            + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        )

    observations = [NOTES.strip()]
    print("\n" + "=" * 72)
    print("draft=", draft_id)
    print("mapping_temperature=", settings.mapping_temperature)
    print("section=", SECTION_ID, SECTION_TITLE)
    print("property_type=", property_context.get("property_type"))

    blocks, hits = retrieve_past_report_baselines_hybrid(
        TENANT,
        section_label=SECTION_TITLE,
        paragraph_section_id=SECTION_ID,
        observations=observations,
        property_context=property_context,
    )
    print(f"hybrid: ranking_hits={len(hits)} source_blocks={len(blocks)}")
    blocks_meta: list[dict] = []
    for i, b in enumerate(blocks, 1):
        preview = (b.text or "").replace("\n", " ")[:100]
        print(f"  {i}. {b.source_filename}  chars={len(b.text or '')}  {preview!r}...")
        hit0 = b.hits[0] if b.hits else None
        blocks_meta.append(
            {
                "rank": i,
                "source_filename": b.source_filename,
                "chars": len(b.text or ""),
                "score": round(float(hit0.score), 6) if hit0 else None,
                "similarity_score": round(float(hit0.similarity_score), 6)
                if hit0
                else None,
                "bm25_score": round(float(hit0.bm25_score), 6) if hit0 else None,
                "fusion_score": round(float(hit0.fusion_score), 6) if hit0 else None,
            }
        )

    note = SectionNote(
        section_id=SECTION_ID,
        raw_observations=list(observations),
        text=NOTES.strip(),
    )
    section, unmatched = await section_mapper._process_one_section(
        SECTION_ID,
        schema=schema,
        tenant_id=TENANT,
        by_id={SECTION_ID: note},
        id_to_unit=id_to_unit,
        report_draft_id=draft_id,
        interference_level=policy.interference_level,
        retrieval_level="paragraph",
        allowed_doc_keys=None,
        property_context=property_context,
        policy=policy,
        knowledge_source=KNOWLEDGE_SOURCE_PAST_REPORT,
    )
    generated = section.text or ""
    print("status=", section.status, "words=", len(generated.split()))
    print(generated[:500], "..." if len(generated) > 500 else "")

    manifest_path = retrieval_manifest.retrieval_manifest_path(TENANT, draft_id)
    sources = [b.source_filename for b in blocks]
    out = {
        "draft_id": draft_id,
        "tenant_id": TENANT,
        "property_type": "house",
        "section_id": SECTION_ID,
        "observations": observations,
        "retrieved_sources": sources,
        "retrieved_count": len(blocks),
        "status": section.status,
        "generated_text": generated,
        "unmatched": list(unmatched or []),
        "readable_dir": str(OUT_DIR / draft_id),
    }
    (_ROOT / "docs" / f"{draft_id}-output.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    run_dir = _write_run_bundle(
        draft_id=draft_id,
        notes=NOTES,
        generated=generated,
        status=str(section.status),
        unmatched=list(unmatched or []),
        sources=sources,
        blocks_meta=blocks_meta,
        manifest_path=manifest_path,
    )
    print("readable_dir=", run_dir)
    return draft_id


async def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    schema = template_discoverer.ensure_canonical_schema(TENANT)
    id_to_unit = {
        sec.id: sec
        for parent in ordered_parent_sections(schema)
        for sec in mapping_units_for_parent(schema, parent.id)
    }
    property_context = build_property_context(
        parse_notes(NOTES), property_type="house", tenure="freehold"
    )
    policy = GenerationPolicy.resolve("assist", 3)

    print("tenant=", TENANT)
    print("runs=", RUNS)
    print("knowledge_source=", KNOWLEDGE_SOURCE_PAST_REPORT)

    for i in range(RUNS):
        print(f"\n>>> generation {i + 1}/{RUNS}")
        await _one_generation(schema, id_to_unit, property_context, policy)

    compare = _write_compare_latest_two()
    if compare:
        print("\ncompare=", compare)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
