"""Re-merge the D2 triple pack with v2; compare against existing v1 merges.

Reuses past + SP drafts from:
  docs/dual-path-merge-runs/d2-triple-sp-merge-luna-t0p2-20260808-172240/

Does not regenerate SP. Merge model/temp from env (expect Luna @ 0.2).

Usage:
  MERGE_AGENT_MODEL=gpt-5.6-luna MERGE_AGENT_TEMPERATURE=0.2 \\
    python scripts/compare_d2_triple_merge_v1_v2.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.config import settings
from backend.merge_agent import DualPathDraft, merge_dual_path_drafts

V1_PACK = (
    _ROOT
    / "docs"
    / "dual-path-merge-runs"
    / "d2-triple-sp-merge-luna-t0p2-20260808-172240"
)
OUT_ROOT = _ROOT / "docs" / "dual-path-merge-runs"
SECTION_ID = "D2"
SECTION_TITLE = "Roof coverings"

# Soft-overreach / scaffold markers to score (case-insensitive).
_MARKERS = [
    "reasonably aligned",
    "no significant defects",
    "structural defect",
    "pointing appearing defective",
    "pointing in this area has deteriorated",
    "thermal element",
    "building regulations",
    "legal adviser",
    "staining",
    "distening",
    "distension",
    "scaffolding",
]


def _clean(text: str) -> str:
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    while "\n\n\n" in t:
        t = t.replace("\n\n\n", "\n\n")
    return t.strip() + ("\n" if t.strip() else "")


def _count_marker(text: str, marker: str) -> int:
    return len(re.findall(re.escape(marker), text or "", flags=re.IGNORECASE))


def main() -> int:
    if not V1_PACK.is_dir():
        print("missing v1 pack:", V1_PACK, file=sys.stderr)
        return 1

    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    run_id = f"d2-triple-merge-v1-vs-v2-luna-t0p2-{stamp}"
    out_dir = OUT_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    merge_model = (settings.merge_agent_model or "").strip() or settings.mapping_model
    merge_temp = float(settings.merge_agent_temperature)
    print("run_id=", run_id)
    print("source_v1_pack=", V1_PACK.name)
    print("merge_model=", merge_model, "merge_temp=", merge_temp)

    rows: list[dict] = []
    compare_lines = [
        f"run_id={run_id}",
        f"source_v1_pack={V1_PACK.name}",
        f"merge_model={merge_model} merge_temp={merge_temp}",
        "Fair compare: same past + SP drafts; only prompt version changes.",
        "",
    ]

    for i in (1, 2, 3):
        src = V1_PACK / f"sample_{i}"
        past = _clean((src / "past_report_draft.txt").read_text(encoding="utf-8"))
        sp = _clean((src / "standard_paragraph_draft.txt").read_text(encoding="utf-8"))
        notes = _clean((src / "inspection_notes.txt").read_text(encoding="utf-8"))
        v1_text = _clean((src / "merged.txt").read_text(encoding="utf-8"))

        sample_dir = out_dir / f"sample_{i}"
        sample_dir.mkdir(parents=True, exist_ok=True)
        (sample_dir / "inspection_notes.txt").write_text(notes, encoding="utf-8")
        (sample_dir / "past_report_draft.txt").write_text(past, encoding="utf-8")
        (sample_dir / "standard_paragraph_draft.txt").write_text(sp, encoding="utf-8")
        (sample_dir / "merged_v1.txt").write_text(v1_text, encoding="utf-8")

        print(f"\n===== SAMPLE {i}/3 — merge v2 =====")
        draft = DualPathDraft(
            section_id=SECTION_ID,
            section_title=SECTION_TITLE,
            inspection_notes=notes.strip(),
            past_report_draft=past,
            standard_paragraph_draft=sp,
        )
        merged = merge_dual_path_drafts(
            draft,
            prompt_version="v2",
            temperature=merge_temp,
            model=merge_model,
        )
        v2_text = _clean(merged.merged_text or "")
        status = merged.meta.get("status")
        used_ver = merged.meta.get("prompt_version")
        print(
            "status=",
            status,
            "prompt_version=",
            used_ver,
            "words=",
            len(v2_text.split()),
        )
        (sample_dir / "merged_v2.txt").write_text(v2_text, encoding="utf-8")
        (sample_dir / "readable.txt").write_text(
            (
                f"SAMPLE {i}  {run_id}\n"
                f"merge_model={merge_model} temp={merge_temp}\n"
                f"{'=' * 72}\nNOTES\n{'=' * 72}\n\n{notes}\n"
                f"{'=' * 72}\nMERGED v1\n{'=' * 72}\n\n{v1_text}\n"
                f"{'=' * 72}\nMERGED v2\n{'=' * 72}\n\n{v2_text}"
            ),
            encoding="utf-8",
        )

        marker_v1 = {m: _count_marker(v1_text, m) for m in _MARKERS}
        marker_v2 = {m: _count_marker(v2_text, m) for m in _MARKERS}
        row = {
            "sample": i,
            "past_source": (src / "past_report_source.txt")
            .read_text(encoding="utf-8")
            .strip()
            if (src / "past_report_source.txt").is_file()
            else "",
            "v1_words": len(v1_text.split()),
            "v2_words": len(v2_text.split()),
            "v2_status": status,
            "v2_prompt_version": used_ver,
            "markers_v1": marker_v1,
            "markers_v2": marker_v2,
        }
        rows.append(row)
        (sample_dir / "meta.json").write_text(
            json.dumps(row, indent=2) + "\n", encoding="utf-8"
        )

        compare_lines.append(f"--- sample_{i} ---")
        compare_lines.append(
            f"words: v1={row['v1_words']}  v2={row['v2_words']}  "
            f"delta={row['v2_words'] - row['v1_words']:+d}"
        )
        compare_lines.append("marker hits (count):")
        for m in _MARKERS:
            a, b = marker_v1[m], marker_v2[m]
            if a or b:
                flag = "  <<" if a != b else ""
                compare_lines.append(f"  {m!r}: v1={a} v2={b}{flag}")
        compare_lines.append(f"  dir={sample_dir}")
        compare_lines.append("")

    # Short qualitative verdict stub (filled after manual-style heuristics).
    verdict = [
        "# D2 triple merge: v1 vs v2",
        "",
        f"- Pack: `{run_id}`",
        f"- Source drafts: `{V1_PACK.name}` (same past + SP; only merge prompt changes)",
        f"- Model: `{merge_model}` @ temperature `{merge_temp}`",
        "",
        "## Word counts",
        "",
        "| Sample | v1 words | v2 words | Δ |",
        "|--------|----------|----------|---|",
    ]
    for r in rows:
        verdict.append(
            f"| {r['sample']} | {r['v1_words']} | {r['v2_words']} | "
            f"{r['v2_words'] - r['v1_words']:+d} |"
        )

    verdict.extend(
        [
            "",
            "## Marker deltas (scaffold / fidelity signals)",
            "",
            "Counts are case-insensitive substring hits in merged prose.",
            "",
        ]
    )
    for r in rows:
        verdict.append(f"### Sample {r['sample']}")
        verdict.append("")
        verdict.append("| Marker | v1 | v2 |")
        verdict.append("|--------|----|----|")
        for m in _MARKERS:
            a = r["markers_v1"][m]
            b = r["markers_v2"][m]
            if a or b:
                verdict.append(f"| {m} | {a} | {b} |")
        verdict.append("")

    # Auto notes for common expectations.
    auto = []
    for r in rows:
        s = r["sample"]
        if r["markers_v2"].get("distening", 0) or r["markers_v2"].get("distension", 0):
            auto.append(f"- Sample {s}: v2 still has Distening/Distension (bad).")
        if r["markers_v1"].get("staining", 0) and not r["markers_v2"].get("staining", 0):
            auto.append(f"- Sample {s}: v2 dropped staining (check if notes filter over-cut).")
        if r["v2_words"] + 40 < r["v1_words"]:
            auto.append(f"- Sample {s}: v2 shorter by {r['v1_words'] - r['v2_words']} words.")
        if r["v2_words"] > r["v1_words"] + 40:
            auto.append(f"- Sample {s}: v2 longer by {r['v2_words'] - r['v1_words']} words.")
        for soft in (
            "reasonably aligned",
            "no significant defects",
            "structural defect",
        ):
            if r["markers_v1"].get(soft, 0) and not r["markers_v2"].get(soft, 0):
                auto.append(f"- Sample {s}: v2 dropped soft scaffold phrase `{soft}`.")
            elif (not r["markers_v1"].get(soft, 0)) and r["markers_v2"].get(soft, 0):
                auto.append(f"- Sample {s}: v2 introduced soft scaffold phrase `{soft}`.")

    verdict.extend(["## Auto observations", ""])
    if auto:
        verdict.extend(auto)
    else:
        verdict.append("- No strong automatic length/marker deltas flagged.")
    verdict.extend(
        [
            "",
            "## Files",
            "",
            f"- Per sample: `sample_N/merged_v1.txt`, `merged_v2.txt`, `readable.txt`",
            f"- Marker table: `COMPARE.txt`",
            "",
        ]
    )

    (out_dir / "COMPARE.txt").write_text("\n".join(compare_lines) + "\n", encoding="utf-8")
    (out_dir / "VERDICT.md").write_text("\n".join(verdict) + "\n", encoding="utf-8")
    (out_dir / "meta.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "source_v1_pack": str(V1_PACK),
                "merge_model": merge_model,
                "merge_agent_temperature": merge_temp,
                "v2_prompt_version_requested": "v2",
                "samples": rows,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("\nout_dir=", out_dir)
    print("compare=", out_dir / "COMPARE.txt")
    print("verdict=", out_dir / "VERDICT.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
