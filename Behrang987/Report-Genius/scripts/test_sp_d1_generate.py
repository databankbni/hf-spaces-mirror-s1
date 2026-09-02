"""One-off: generate D1 from SP memory + write retrieval manifest."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.pipeline import section_mapper
from backend.rag.types import KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH
from backend.storage import retrieval_manifest, tenant_store

TENANT = "khanchaudhry3@gmail.com"
DRAFT_ID = "sp-d1-test-20260729-hybrid"
NOTES = """D1 Chimney stacks

Chimney stack: Brick chimney with some repointing required. Flashing is cracked and lead flashing has come away. TV aerial appears to be leaning. Repairs and repointing should be carried out by a competent contractor.
"""


def main() -> int:
    print("tenant=", TENANT)
    print("draft=", DRAFT_ID)
    print("knowledge_source=", KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH)

    result = section_mapper.generate_report(
        TENANT,
        NOTES,
        property_type="terraced house",
        tenure="freehold",
        interference_level="assist",
        survey_level=3,
        report_draft_id=DRAFT_ID,
        only_section_ids=["D1"],
        knowledge_source=KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH,
    )

    d1 = next((s for s in result.sections if s.section_id.upper() == "D1"), None)
    print("\n=== D1 STATUS ===")
    if not d1:
        print("D1 section missing from result")
        print("sections=", [s.section_id for s in result.sections])
        return 1
    print("status=", d1.status)
    print("text=\n", d1.text)
    print("notes=", d1.notes)

    path = retrieval_manifest.retrieval_manifest_path(TENANT, DRAFT_ID)
    print("\n=== RETRIEVAL MANIFEST ===")
    print("path=", path)
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        sec = (data.get("sections") or {}).get("D1") or {}
        print("knowledge_source=", sec.get("knowledge_source") or data.get("knowledge_source"))
        print("status=", sec.get("status"))
        print("retrieved_chunk_count=", sec.get("retrieved_chunk_count"))
        print("requested_top_k=", sec.get("requested_top_k"))
        for i, ch in enumerate(sec.get("chunks_used") or [], 1):
            print(f"\n--- chunk {i} score={ch.get('score')} ---")
            print((ch.get("chunk_text") or "")[:500])
        # Also copy a readable summary next to samples for the user
        out = (
            _ROOT
            / "backend"
            / "standard_paragraphs"
            / "samples"
            / "d1_sp_generation_test_retrieval.json"
        )
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print("\ncopied=", out)
    else:
        print("manifest missing")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
