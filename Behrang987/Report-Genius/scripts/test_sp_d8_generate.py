"""One-off: generate D8 from SP memory + write retrieval manifest."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.pipeline import section_mapper
from backend.rag.types import KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH
from backend.storage import retrieval_manifest

TENANT = "khanchaudhry3@gmail.com"
DRAFT_ID = "sp-d8-test-20260729"
SECTION_ID = "D8"
NOTES = """D8 Other joinery and finishes

Surface rust/deterioration to timber boards.
"""


def main() -> int:
    print("tenant=", TENANT)
    print("draft=", DRAFT_ID)
    print("section=", SECTION_ID)

    result = section_mapper.generate_report(
        TENANT,
        NOTES,
        property_type="terraced house",
        tenure="freehold",
        interference_level="assist",
        survey_level=3,
        report_draft_id=DRAFT_ID,
        only_section_ids=[SECTION_ID],
        knowledge_source=KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH,
    )

    sec_out = next(
        (s for s in result.sections if s.section_id.upper() == SECTION_ID), None
    )
    print(f"\n=== {SECTION_ID} STATUS ===")
    if not sec_out:
        print(f"{SECTION_ID} missing; sections=", [s.section_id for s in result.sections])
        return 1
    print("status=", sec_out.status)
    print("text=\n", sec_out.text)

    path = retrieval_manifest.retrieval_manifest_path(TENANT, DRAFT_ID)
    print("\n=== RETRIEVAL MANIFEST ===")
    print("path=", path)
    if not path.is_file():
        print("manifest missing")
        return 2
    data = json.loads(path.read_text(encoding="utf-8"))
    sec = (data.get("sections") or {}).get(SECTION_ID) or {}
    print("status=", sec.get("status"))
    print("retrieved_chunk_count=", sec.get("retrieved_chunk_count"))
    print("generated_text=\n", (sec.get("generated_text") or "")[:800])
    print("\n--- retrieved labels/scores ---")
    for i, ch in enumerate(sec.get("chunks_used") or [], 1):
        print(
            f"{i}. cosine={ch.get('score')} fusion={ch.get('fusion_score')} "
            f"text={(ch.get('chunk_text') or '')[:120]!r}"
        )
    out = (
        _ROOT
        / "backend"
        / "standard_paragraphs"
        / "samples"
        / "d8_sp_generation_test_retrieval.json"
    )
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\ncopied=", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
