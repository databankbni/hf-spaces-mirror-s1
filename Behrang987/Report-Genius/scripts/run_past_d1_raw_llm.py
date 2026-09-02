"""One-off: D1 past-report mapping with NO pre/post anti-bleed processing.

Compares against the normal gated path by feeding raw retrieved scaffolds to the
LLM and returning the model output without property-type / rating / expansion
stripping.
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
from backend.pipeline.reference_mapper import build_interference_messages
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


def main() -> int:
    draft_id = (
        "past-e2e-d1-raw-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
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
    tier = TIER_REFERENCE if _uses_reference_tier(interference_level) else "master"

    candidate_ids = [SECTION_ID]
    alias_id = schema.paragraph_section_id(SECTION_ID)
    if alias_id and alias_id != SECTION_ID:
        candidate_ids.append(alias_id)

    source_blocks = []
    hits = []
    for cid in candidate_ids:
        blocks = fetch_complete_section_baselines_per_source(
            TENANT,
            paragraph_section_id=cid,
            tier=tier,
            allowed_doc_keys=None,
            property_context=property_context,
        )
        if blocks:
            source_blocks = blocks
            hits = [h for b in blocks for h in b.hits]
            break

    if not source_blocks:
        for cid in candidate_ids:
            cand_hits = retrieve_paragraphs_for_mapping(
                TENANT,
                section_label=title,
                paragraph_section_id=cid,
                observations=OBSERVATIONS,
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
                tenant_id=TENANT,
                tier=tier,
                allowed_doc_keys=None,
                property_context=property_context,
            )
            if cand_blocks:
                source_blocks = cand_blocks
                hits = cand_hits
                break

    raw_blocks = [b.text.strip() for b in source_blocks if (b.text or "").strip()]
    raw_baseline = "\n\n".join(raw_blocks)
    if not raw_baseline:
        print("NO_RAG_MATCH: no D1 past-report scaffolds retrieved")
        return 1

    print("tenant=", TENANT)
    print("draft=", draft_id)
    print("mode=RAW (no before-LLM reduce, no after-LLM strip)")
    print("retrieved_source_blocks=", len(raw_blocks))
    print("retrieved_hits=", len(hits))
    print("raw_baseline_chars=", len(raw_baseline))

    messages = build_interference_messages(
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

    out, usage = openai_client.chat_text_with_usage(
        messages,
        model=settings.mapping_model,
        max_tokens=settings.max_tokens_mapping,
        temperature=float(settings.mapping_temperature),
        call_label="mapping-raw-d1",
    )
    text = (out or "").strip()

    print("\n========== RAW LLM OUTPUT (D1) ==========\n")
    print(text)
    print("\n========== USAGE ==========")
    print(json.dumps(usage or {}, indent=2))

    payload = {
        "draft_id": draft_id,
        "tenant_id": TENANT,
        "mode": "raw_no_pre_post_processing",
        "section_id": SECTION_ID,
        "observations": OBSERVATIONS,
        "retrieved_source_block_count": len(raw_blocks),
        "retrieved_hit_count": len(hits),
        "raw_baseline_chars": len(raw_baseline),
        "generated_text": text,
        "llm_usage": usage,
        "system_prompt": messages[0]["content"] if messages else "",
        "user_prompt": messages[1]["content"] if len(messages) > 1 else "",
    }
    out_path = _ROOT / "docs" / f"{draft_id}-output.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nsaved=", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
