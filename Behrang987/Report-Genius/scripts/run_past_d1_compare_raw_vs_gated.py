"""Generate D1 twice in one run: raw (no pre/post) and gated (with pre/post).

Saves a single JSON with both generated texts so they can be compared side by side.
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
from backend.domain.interference import GenerationPolicy
from backend.domain.notes.survey_notes import build_property_context, parse_notes
from backend.domain.rics_level3_schema import (
    mapping_units_for_parent,
    ordered_parent_sections,
)
from backend.llm import openai_client
from backend.pipeline.reference_mapper import (
    build_interference_messages,
    map_reference_paragraph,
)
from backend.pipeline.section_mapper import _reduce_reference_block
from backend.rag.retriever import (
    assemble_reference_baselines_per_source,
    fetch_complete_section_baselines_per_source,
    retrieve_paragraphs_for_mapping,
    _uses_reference_tier,
)
from backend.rag.types import TIER_REFERENCE

TENANT = "khanchaudhry3@gmail.com"
SECTION_ID = "D1"
SECTION_TITLE = "Chimney stacks"
OBSERVATIONS = [
    "The front right chimney stack appears to abut the rainwater gutter, "
    "and there is a gap between the stack and the wall. We cannot confirm "
    "waterproofing. The lead flashing requires redressing, and the lead "
    "flashings are made of lead. One of the chimney stacks appear to have "
    "been removed. The property would have had four, but it is now three. "
    "The chimney shows weathering and requires repointing. Close inspection "
    "will be required. However, not urgent."
]


def _id_to_unit(schema):
    return {
        sec.id: sec
        for parent in ordered_parent_sections(schema)
        for sec in mapping_units_for_parent(schema, parent.id)
    }


def _retrieve_source_blocks(tenant_id, schema, title, observations, property_context, interference_level):
    tier = TIER_REFERENCE if _uses_reference_tier(interference_level) else "master"
    candidate_ids = [SECTION_ID]
    alias_id = schema.paragraph_section_id(SECTION_ID)
    if alias_id and alias_id != SECTION_ID:
        candidate_ids.append(alias_id)

    for cid in candidate_ids:
        blocks = fetch_complete_section_baselines_per_source(
            tenant_id,
            paragraph_section_id=cid,
            tier=tier,
            allowed_doc_keys=None,
            property_context=property_context,
        )
        if blocks:
            return blocks, [h for b in blocks for h in b.hits]

    for cid in candidate_ids:
        cand_hits = retrieve_paragraphs_for_mapping(
            tenant_id,
            section_label=title,
            paragraph_section_id=cid,
            observations=observations,
            interference_level=interference_level,
            retrieval_level="paragraph",
            allowed_doc_keys=None,
            property_context=property_context,
        )
        if not cand_hits:
            continue
        cand_blocks = assemble_reference_baselines_per_source(
            cand_hits,
            paragraph_section_id=cid,
            tenant_id=tenant_id,
            tier=tier,
            allowed_doc_keys=None,
            property_context=property_context,
        )
        if cand_blocks:
            return cand_blocks, cand_hits
    return [], []


def _call_llm(messages):
    out, usage = openai_client.chat_text_with_usage(
        messages,
        model=settings.mapping_model,
        max_tokens=settings.max_tokens_mapping,
        temperature=float(settings.mapping_temperature),
        call_label="mapping-d1-compare",
    )
    return (out or "").strip(), usage


def main() -> int:
    draft_id = (
        "past-e2e-d1-compare-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    )
    schema = template_discoverer.ensure_canonical_schema(TENANT)
    id_to_unit = _id_to_unit(schema)
    unit = id_to_unit.get(SECTION_ID)
    title = getattr(unit, "label", None) or SECTION_TITLE

    survey_notes = parse_notes(f"{SECTION_ID} {title}\n" + "\n".join(OBSERVATIONS))
    property_context = build_property_context(
        survey_notes, property_type="terraced house", tenure="freehold"
    )
    policy = GenerationPolicy.resolve("assist", 3)
    interference_level = policy.interference_level

    source_blocks, hits = _retrieve_source_blocks(
        TENANT, schema, title, OBSERVATIONS, property_context, interference_level
    )
    raw_blocks = [b.text.strip() for b in source_blocks if (b.text or "").strip()]
    raw_baseline = "\n\n".join(raw_blocks)
    if not raw_baseline:
        print("NO_RAG_MATCH: no D1 past-report scaffolds retrieved")
        return 1

    # ── Path A: RAW — no before-LLM reduce, no after-LLM strip ──────────────
    raw_messages = build_interference_messages(
        interference_level,
        observations=OBSERVATIONS,
        baseline=raw_baseline,
        schema=schema,
        section_id=SECTION_ID,
        section_title=title,
        rating_value=None,
        reference_blocks=raw_blocks,
        mode=policy.mode,
        preferences=policy.preferences,
        tenant_id=TENANT,
    )
    raw_text, raw_usage = _call_llm(raw_messages)

    # ── Path B: GATED — same pre/post processing as production ──────────────
    gated_blocks = []
    for block in source_blocks:
        reduced = _reduce_reference_block(
            block.text,
            OBSERVATIONS,
            mappable=True,
            rating_value=None,
        )
        if reduced.strip():
            gated_blocks.append(reduced)
    # Fallback: if gate emptied everything, still run on empty-safe baseline path
    # via map_reference_paragraph (production would author from notes).
    if not gated_blocks:
        gated_text, gated_usage = "", None
        gated_baseline = ""
    else:
        gated_baseline = "\n\n".join(gated_blocks)
        gated_text, gated_usage = map_reference_paragraph(
            gated_baseline,
            OBSERVATIONS,
            schema,
            interference_level,
            section_id=SECTION_ID,
            section_title=title,
            rating_value=None,
            reference_blocks=gated_blocks,
            mode=policy.mode,
            preferences=policy.preferences,
            tenant_id=TENANT,
        )

    print("tenant=", TENANT)
    print("draft=", draft_id)
    print("retrieved_source_blocks=", len(raw_blocks))
    print("retrieved_hits=", len(hits))
    print("raw_baseline_chars=", len(raw_baseline))
    print("gated_baseline_chars=", len(gated_baseline) if gated_blocks else 0)
    print("gated_blocks_kept=", len(gated_blocks))

    print("\n========== RAW (no pre/post processing) ==========\n")
    print(raw_text)
    print("\n========== GATED (with pre/post processing) ==========\n")
    print(gated_text)

    payload = {
        "draft_id": draft_id,
        "tenant_id": TENANT,
        "section_id": SECTION_ID,
        "section_title": title,
        "observations": OBSERVATIONS,
        "retrieved_source_block_count": len(raw_blocks),
        "retrieved_hit_count": len(hits),
        "raw": {
            "mode": "no_pre_post_processing",
            "baseline_chars": len(raw_baseline),
            "baseline_block_count": len(raw_blocks),
            "generated_text": raw_text,
            "llm_usage": raw_usage,
        },
        "gated": {
            "mode": "with_pre_post_processing",
            "baseline_chars": len(gated_baseline) if gated_blocks else 0,
            "baseline_block_count": len(gated_blocks),
            "generated_text": gated_text,
            "llm_usage": gated_usage,
        },
    }
    out_path = _ROOT / "docs" / f"{draft_id}-output.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nsaved=", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
