"""One-shot D4 past-report generate with property_type=house (hybrid top-K).

Writes machine JSON plus clean plaintext files under docs/ so generated prose
can be read and diffed without JSON ``\\n`` escapes.
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
from backend.models.section import SectionNote
from backend.pipeline import section_mapper
from backend.rag.retriever import retrieve_past_report_baselines_hybrid
from backend.rag.types import KNOWLEDGE_SOURCE_PAST_REPORT
from backend.storage import retrieval_manifest

TENANT = "khanchaudhry3@gmail.com"
OUT_DIR = _ROOT / "docs" / "past-d4-house-runs"

NOTES = """The main walls are of solid construction, approximately 285 mm thick. The damp-proof course is concealed. External ground levels appear to be at an adequate height in relation to the internal floor level.

The rendered wall surfaces show evidence of cracking. The window sills and surrounds have been rendered and painted, and cracking was also noted in these areas. The gaps where the doors and windows abut the main walls have been sealed with mortar fillets, which also exhibit cracking.

A movement-related crack was noted to the front bay. The cracks measured less than 5 mm in width. However, future movement cannot be ruled out. Please give the 4 options regarding the implications of the observed structural movement."""


def _clean_prose(text: str) -> str:
    """Normalise generated/notes text for easy reading and diffing."""
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    # Collapse 3+ blank lines to a single blank line between paragraphs.
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
    """Write a folder of clean plaintext + compact meta for side-by-side compare."""
    run_dir = OUT_DIR / draft_id
    run_dir.mkdir(parents=True, exist_ok=True)

    notes_clean = _clean_prose(notes)
    gen_clean = _clean_prose(generated)

    (run_dir / "inspection_notes.txt").write_text(notes_clean, encoding="utf-8")
    (run_dir / "generated.txt").write_text(gen_clean, encoding="utf-8")

    sources_lines = [f"{i}. {name}" for i, name in enumerate(sources, 1)]
    (run_dir / "retrieved_sources.txt").write_text(
        "\n".join(sources_lines) + ("\n" if sources_lines else ""),
        encoding="utf-8",
    )

    meta = {
        "draft_id": draft_id,
        "tenant_id": TENANT,
        "property_type": "house",
        "section_id": "D4",
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
        "files": {
            "inspection_notes": "inspection_notes.txt",
            "generated": "generated.txt",
            "sources": "retrieved_sources.txt",
        },
    }
    (run_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Single readable pack: notes then generated — open this for quick eyeballing.
    pack = (
        f"DRAFT: {draft_id}\n"
        f"STATUS: {status}\n"
        f"WORDS: {len(gen_clean.split())}  CHARS: {len(gen_clean)}\n"
        f"{'=' * 72}\n"
        f"INSPECTION NOTES\n"
        f"{'=' * 72}\n\n"
        f"{notes_clean}\n"
        f"{'=' * 72}\n"
        f"GENERATED D4\n"
        f"{'=' * 72}\n\n"
        f"{gen_clean}"
    )
    (run_dir / "readable.txt").write_text(pack, encoding="utf-8")

    # Also keep a flat copy under docs/ for the latest open-in-editor habit.
    flat = _ROOT / "docs" / f"{draft_id}-generated.txt"
    flat.write_text(gen_clean, encoding="utf-8")

    return run_dir


def export_existing_json_outputs() -> None:
    """Backfill clean plaintext from older ``*-output.json`` files if present."""
    docs = _ROOT / "docs"
    for path in sorted(docs.glob("past-d4-house-*-output.json")):
        draft_id = path.name.replace("-output.json", "")
        run_dir = OUT_DIR / draft_id
        if (run_dir / "generated.txt").exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        notes = ""
        obs = data.get("observations") or []
        if isinstance(obs, list):
            notes = "\n\n".join(str(o) for o in obs if o)
        elif isinstance(obs, str):
            notes = obs
        _write_run_bundle(
            draft_id=draft_id,
            notes=notes or NOTES,
            generated=data.get("generated_text") or "",
            status=str(data.get("status") or ""),
            unmatched=list(data.get("unmatched") or []),
            sources=list(data.get("retrieved_sources") or []),
            blocks_meta=[],
            manifest_path=retrieval_manifest.retrieval_manifest_path(
                TENANT, draft_id
            ),
        )
        print("backfilled=", run_dir)


async def main() -> int:
    # Always refresh plaintext exports for prior JSON runs so compare is ready.
    export_existing_json_outputs()

    temp_tag = f"t{settings.mapping_temperature:g}".replace(".", "p")
    draft_id = (
        "past-d4-house-"
        + temp_tag
        + "-"
        + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    )
    sid = "D4"
    title = "Main walls"
    observations = [NOTES.strip()]

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
    print("draft=", draft_id)
    print("mapping_temperature=", settings.mapping_temperature)
    print("property_type=", property_context.get("property_type"))
    print("knowledge_source=", KNOWLEDGE_SOURCE_PAST_REPORT)

    blocks, hits = retrieve_past_report_baselines_hybrid(
        TENANT,
        section_label=title,
        paragraph_section_id=sid,
        observations=observations,
        property_context=property_context,
    )
    print(f"\n--- hybrid retrieval D4 (house) ---")
    print(f"ranking_hits={len(hits)} source_blocks={len(blocks)}")
    blocks_meta: list[dict] = []
    for i, b in enumerate(blocks, 1):
        preview = (b.text or "").replace("\n", " ")[:120]
        print(f"  {i}. {b.source_filename}  chars={len(b.text or '')}  preview={preview!r}...")
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
        section_id=sid,
        raw_observations=list(observations),
        text=NOTES.strip(),
    )
    section, unmatched = await section_mapper._process_one_section(
        sid,
        schema=schema,
        tenant_id=TENANT,
        by_id={sid: note},
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
    print("\n========== GENERATED D4 ==========")
    print("status=", section.status)
    print("unmatched=", unmatched)
    print(generated)

    manifest_path = retrieval_manifest.retrieval_manifest_path(TENANT, draft_id)
    sources = [b.source_filename for b in blocks]

    out = {
        "draft_id": draft_id,
        "tenant_id": TENANT,
        "property_type": "house",
        "section_id": sid,
        "observations": observations,
        "retrieved_sources": sources,
        "retrieved_count": len(blocks),
        "status": section.status,
        "generated_text": generated,
        "unmatched": list(unmatched or []),
        "readable_dir": str(OUT_DIR / draft_id),
    }
    out_path = _ROOT / "docs" / f"{draft_id}-output.json"
    out_path.write_text(
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

    # Pointer to the two most recent generated.txt files for a quick diff.
    recent = sorted(
        (p for p in OUT_DIR.glob("past-d4-house-*/generated.txt") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if len(recent) >= 2:
        compare_path = OUT_DIR / "COMPARE_latest_two.txt"
        a = recent[1]  # older
        b = recent[0]  # newer
        compare_path.write_text(
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
        print("compare=", compare_path)

    print("\nsaved_json=", out_path)
    print("readable_dir=", run_dir)
    print("generated_txt=", run_dir / "generated.txt")
    print("readable_pack=", run_dir / "readable.txt")
    print("manifest=", manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
