"""E2E past-report generate for D2 + D4 with explicit per-section notes.

Mirrors ``scripts/test_sp_d2_d4_generate_eval.py`` / ``test_sp_decompose_generate.py``:

- Inspection notes are declared per subsection (not one shared blob).
- The cross-section notes router is bypassed: the entire note for D2 is used
  only for D2 generation, and the entire note for D4 only for D4.
- Past-report scaffolds are retrieved for that subsection and mapped with the
  full note text in the prompt.
- Writes retrieval + evaluation JSON under the tenant data dir (and a docs copy).

Example:
  python scripts/run_past_d2_d4_generate.py
  python scripts/run_past_d2_d4_generate.py --skip-eval
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.domain import template_discoverer
from backend.domain.interference import GenerationPolicy
from backend.domain.notes.survey_notes import build_property_context, parse_notes
from backend.domain.rics_level3_schema import (
    mapping_units_for_parent,
    ordered_parent_sections,
)
from backend.models.section import SectionNote
from backend.pipeline import section_mapper
from backend.rag.types import KNOWLEDGE_SOURCE_PAST_REPORT
from backend.storage import retrieval_manifest

TENANT = "khanchaudhry3@gmail.com"

# Explicit per-section notes — same contract as SP e2e CASES.
# The whole observation list for a section is locked to that section only.
CASES: list[dict] = [
    {
        "section_id": "D1",
        "section_title": "Chimney stacks",
        "observations": [
            "The front right chimney stack appears to abut the rainwater gutter, "
            "and there is a gap between the stack and the wall. We cannot confirm "
            "waterproofing. The lead flashing requires redressing, and the lead "
            "flashings are made of lead. One of the chimney stacks appear to have "
            "been removed. The property would have had four, but it is now three. "
            "The chimney shows weathering and requires repointing. Close inspection "
            "will be required. However, not urgent."
        ],
    },
    {
        "section_id": "D2",
        "section_title": "Roof coverings",
        "observations": [
            "The roof tiles are new and heavier, internally we noted, shakes and "
            "new strutting support has been provided. We noted that underfelt not "
            "lapped inside of the gutter. The roof is butterfly roof and could not "
            "be inspected as there was no available vantage point. The verges of "
            "the roof at the rear is cracked. I noted moss and lichen growth. "
            "Roof lights have been installed on the roof. There are solar panels "
            "as well."
        ],
    },
    {
        "section_id": "D4",
        "section_title": "Main walls",
        "observations": [
            "There is history of underpinning at the property, which may have loan "
            "security implications. I could not ascertain whether the building "
            "contains RAAC. Confirm the implications. No hazardous material. "
            "There is lintel defect. I noted masonry bees. I noted crack to the "
            "front bay, which requires installation of Helifix bars and also "
            "resin injection, and also repair to the lintel."
        ],
    },
]


def _case_for(section_id: str) -> dict:
    sid = section_id.strip().upper()
    for case in CASES:
        if case["section_id"].upper() == sid:
            return case
    known = [c["section_id"] for c in CASES]
    raise SystemExit(f"Unknown section {section_id!r}. Known: {known}")


def _id_to_unit(schema) -> dict[str, object]:
    return {
        sec.id: sec
        for parent in ordered_parent_sections(schema)
        for sec in mapping_units_for_parent(schema, parent.id)
    }


async def _run_section(
    *,
    tenant_id: str,
    draft_id: str,
    case: dict,
    schema,
    id_to_unit: dict[str, object],
    property_context: dict,
    policy,
) -> dict:
    """Map one subsection from its locked observations (no notes router)."""
    sid = case["section_id"]
    title = case["section_title"]
    observations = [o.strip() for o in case["observations"] if str(o).strip()]
    note = SectionNote(
        section_id=sid,
        raw_observations=list(observations),
        text="\n".join(observations),
    )
    by_id = {sid: note}

    print(f"\n========== GENERATE {sid} (past_report, router bypassed) ==========")
    print("locked_observations=")
    for i, o in enumerate(observations, 1):
        print(f"  {i}. {o}")

    section, unmatched = await section_mapper._process_one_section(
        sid,
        schema=schema,
        tenant_id=tenant_id,
        by_id=by_id,
        id_to_unit=id_to_unit,
        report_draft_id=draft_id,
        interference_level=policy.interference_level,
        retrieval_level="paragraph",
        allowed_doc_keys=None,
        property_context=property_context,
        policy=policy,
        knowledge_source=KNOWLEDGE_SOURCE_PAST_REPORT,
    )

    print("status=", section.status)
    print("unmatched=", unmatched)
    print("generated_text=\n", section.text)

    return {
        "section_id": sid,
        "title": title,
        "observations": observations,
        "status": section.status,
        "generated_text": section.text or "",
        "unmatched": list(unmatched or []),
        "notes": section.notes or "",
    }


async def _async_main(args: argparse.Namespace) -> int:
    draft_id = args.draft_id.strip() or (
        "past-e2e-d2-d4-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    )
    want = [s.strip().upper() for s in args.sections.split(",") if s.strip()]
    cases = [_case_for(s) for s in want]

    print("tenant=", args.tenant)
    print("draft=", draft_id)
    print("knowledge_source=", KNOWLEDGE_SOURCE_PAST_REPORT)
    print("router=bypassed (explicit per-section notes)")

    schema = template_discoverer.ensure_canonical_schema(args.tenant)
    id_to_unit = _id_to_unit(schema)
    # Property context only — do not use parse_notes_to_sections for routing.
    joined_notes = "\n\n".join(
        f"{c['section_id']} {c['section_title']}\n" + "\n".join(c["observations"])
        for c in cases
    )
    survey_notes = parse_notes(joined_notes)
    property_context = build_property_context(
        survey_notes, property_type="terraced house", tenure="freehold"
    )
    policy = GenerationPolicy.resolve("assist", 3)

    results: list[dict] = []
    for case in cases:
        results.append(
            await _run_section(
                tenant_id=args.tenant,
                draft_id=draft_id,
                case=case,
                schema=schema,
                id_to_unit=id_to_unit,
                property_context=property_context,
                policy=policy,
            )
        )

    mpath = retrieval_manifest.retrieval_manifest_path(args.tenant, draft_id)
    out = {
        "draft_id": draft_id,
        "tenant_id": args.tenant,
        "knowledge_source": KNOWLEDGE_SOURCE_PAST_REPORT,
        "router_bypassed": True,
        "sections": results,
        "retrieval_manifest_path": str(mpath),
    }
    out_path = _ROOT / "docs" / f"{draft_id}-output.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print()
    print("saved=", out_path)
    print("manifest=", mpath)

    if mpath.is_file():
        data = json.loads(mpath.read_text(encoding="utf-8"))
        for sid in want:
            sec = (data.get("sections") or {}).get(sid) or {}
            print()
            print("--- retrieval", sid, "---")
            print("status=", sec.get("status"))
            print("observations_in_manifest=")
            for o in sec.get("observations") or []:
                print(" -", o)
            print(
                "retrieved_count=",
                sec.get("retrieved_count") or sec.get("retrieved_chunk_count"),
            )

    if args.skip_eval:
        return 0

    from scripts.run_past_d2_d4_eval import main as eval_main

    print("\n========== EVALUATION ==========")
    sys.argv = [sys.argv[0], draft_id]
    return await eval_main()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="E2E past-report D2/D4 with explicit per-section notes"
    )
    parser.add_argument("--tenant", default=TENANT)
    parser.add_argument(
        "--draft-id",
        default="",
        help="Retrieval/eval manifest id (default: past-e2e-d2-d4-<timestamp>)",
    )
    parser.add_argument(
        "--sections",
        default="D2,D4",
        help="Comma-separated section ids from CASES (default: D2,D4)",
    )
    parser.add_argument(
        "--skip-eval",
        action="store_true",
        help="Skip coverage evaluation after generate",
    )
    args = parser.parse_args()
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
