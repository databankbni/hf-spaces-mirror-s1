"""Build fixture pairs + run dual-path merge on saved past + SP drafts.

Uses existing generated prose only (no note re-generation):

- D2 / D4: same messy inspection notes on both paths
  - past: docs/past-e2e-d2-d4-20260803-080048-output.json
  - SP:   backend/standard_paragraphs/samples/sp-d2-d4-f6-notes-and-sp-only-prose.json
- D1: past-report draft from past-e2e-d1-compare; no matching SP generated
  draft was found for those notes, so D1 is recorded but merge is skipped
  unless --d1-house-as-past is used with an SP stub (not default).

Usage:
  python scripts/run_dual_path_merge_fixtures.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.merge_agent import DualPathDraft, merge_dual_path_drafts

_PAST_D2_D4 = _ROOT / "docs" / "past-e2e-d2-d4-20260803-080048-output.json"
_SP_D2_D4 = (
    _ROOT
    / "backend"
    / "standard_paragraphs"
    / "samples"
    / "sp-d2-d4-f6-notes-and-sp-only-prose.json"
)
_PAST_D1 = _ROOT / "docs" / "past-e2e-d1-compare-20260804-090141-output.json"
_HOUSE_D1 = (
    _ROOT
    / "docs"
    / "past-d1-house-runs"
    / "past-d1-house-20260805-123044"
    / "generated.txt"
)
_OUT_ROOT = _ROOT / "docs" / "dual-path-merge-runs"


def _load_d2_d4_drafts() -> list[DualPathDraft]:
    past = json.loads(_PAST_D2_D4.read_text(encoding="utf-8"))
    sp = json.loads(_SP_D2_D4.read_text(encoding="utf-8"))
    by_past = {s["section_id"]: s for s in past["sections"]}
    drafts: list[DualPathDraft] = []
    for sid in ("D2", "D4"):
        psec = by_past[sid]
        ssec = sp["sections"][sid]
        notes = ssec.get("inspection_notes") or ""
        if not notes and psec.get("observations"):
            notes = psec["observations"][0]
        drafts.append(
            DualPathDraft(
                section_id=sid,
                section_title=ssec.get("section_title") or psec.get("title") or sid,
                past_report_draft=psec["generated_text"],
                standard_paragraph_draft=ssec[
                    "generated_text_standard_paragraphs_only"
                ],
                past_report_source=str(_PAST_D2_D4.relative_to(_ROOT)),
                standard_paragraph_source=str(_SP_D2_D4.relative_to(_ROOT)),
                inspection_notes=notes,
            )
        )
    return drafts


def _load_d1_past_only() -> DualPathDraft:
    """D1 past draft exists; matching SP generated prose was not found."""
    past = json.loads(_PAST_D1.read_text(encoding="utf-8"))
    text = past["raw"]["generated_text"]
    notes = " ".join(past.get("observations") or [])
    # Prefer latest house past-report prose when present (newer voice sample).
    if _HOUSE_D1.is_file():
        text = _HOUSE_D1.read_text(encoding="utf-8").strip()
        house_notes = (
            _HOUSE_D1.parent / "inspection_notes.txt"
        ).read_text(encoding="utf-8").strip()
        if house_notes:
            notes = house_notes
        past_src = str(_HOUSE_D1.relative_to(_ROOT))
    else:
        past_src = str(_PAST_D1.relative_to(_ROOT))
    return DualPathDraft(
        section_id="D1",
        section_title=past.get("section_title") or "Chimney stacks",
        past_report_draft=text,
        standard_paragraph_draft="",
        past_report_source=past_src,
        standard_paragraph_source="",
        inspection_notes=notes,
    )


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = _OUT_ROOT / f"merge-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    drafts = _load_d2_d4_drafts()
    d1 = _load_d1_past_only()
    drafts = [d1, *drafts]

    results = []
    for draft in drafts:
        print(f"\n========== MERGE {draft.section_id} ==========")
        print("past_source=", draft.past_report_source)
        print("sp_source=", draft.standard_paragraph_source or "(none)")
        if not (draft.standard_paragraph_draft or "").strip():
            print(
                "SKIP merge LLM: no matching standard-paragraph draft on disk "
                "for these notes. Saving past-report draft only."
            )
            result = merge_dual_path_drafts(draft)
        else:
            result = merge_dual_path_drafts(draft)
        print("status=", result.meta.get("status"))
        print("model=", result.model)
        print("merged_chars=", len(result.merged_text or ""))

        sec_dir = out_dir / draft.section_id.lower()
        sec_dir.mkdir(parents=True, exist_ok=True)
        (sec_dir / "past_report_draft.txt").write_text(
            draft.past_report_draft or "", encoding="utf-8"
        )
        (sec_dir / "standard_paragraph_draft.txt").write_text(
            draft.standard_paragraph_draft or "", encoding="utf-8"
        )
        (sec_dir / "merged.txt").write_text(
            result.merged_text or "", encoding="utf-8"
        )
        (sec_dir / "inspection_notes.txt").write_text(
            draft.inspection_notes or "", encoding="utf-8"
        )
        readable = (
            f"SECTION {draft.section_id} — {draft.section_title}\n"
            f"status={result.meta.get('status')}\n"
            f"past_source={draft.past_report_source}\n"
            f"sp_source={draft.standard_paragraph_source or '(none)'}\n\n"
            f"===== INSPECTION NOTES =====\n\n"
            f"{draft.inspection_notes}\n\n"
            f"===== PAST-REPORT DRAFT =====\n\n"
            f"{draft.past_report_draft}\n\n"
            f"===== STANDARD-PARAGRAPH DRAFT =====\n\n"
            f"{draft.standard_paragraph_draft or '(none — merge skipped)'}\n\n"
            f"===== MERGED =====\n\n"
            f"{result.merged_text}\n"
        )
        (sec_dir / "readable.txt").write_text(readable, encoding="utf-8")
        results.append(
            {
                "section_id": result.section_id,
                "section_title": result.section_title,
                "status": result.meta.get("status"),
                "model": result.model,
                "llm_usage": result.llm_usage,
                "past_report_source": result.past_report_source,
                "standard_paragraph_source": result.standard_paragraph_source,
                "merged_chars": len(result.merged_text or ""),
                "merged_text": result.merged_text,
            }
        )

    meta = {
        "run_id": out_dir.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "D2/D4 use note-matched past-report + SP-only drafts. "
            "D1 has past-report prose only (no matching SP generated draft "
            "found for those chimney notes)."
        ),
        "sections": results,
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    compare_lines = [
        f"Dual-path merge run: {out_dir.name}",
        meta["note"],
        "",
    ]
    for r in results:
        compare_lines.append(
            f"{r['section_id']}: status={r['status']} "
            f"merged_chars={r['merged_chars']} → {r['section_id'].lower()}/readable.txt"
        )
    (out_dir / "COMPARE.txt").write_text(
        "\n".join(compare_lines) + "\n", encoding="utf-8"
    )
    print(f"\nWrote {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
