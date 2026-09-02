"""Re-merge saved house-note drafts at temperatures 0.0 and 0.2, then compare.

Uses latest past-report house drafts + SP drafts from the prior house-merge
run (same inspection notes). Does not regenerate mapping.

Usage:
  python scripts/compare_merge_temperatures.py
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

TEMPS = (0.0, 0.2)
OUT_ROOT = _ROOT / "docs" / "dual-path-merge-runs"

_PAST = {
    "D1": (
        _ROOT
        / "docs"
        / "past-d1-house-runs"
        / "past-d1-house-20260806-123833"
        / "generated.txt"
    ),
    "D2": (
        _ROOT
        / "docs"
        / "past-d2-house-runs"
        / "past-d2-house-20260806-124051"
        / "generated.txt"
    ),
    "D4": (
        _ROOT
        / "docs"
        / "past-d4-house-runs"
        / "past-d4-house-20260806-123443"
        / "generated.txt"
    ),
}

_SP_BASE = _ROOT / "docs" / "dual-path-merge-runs" / "house-merge-20260806-021600"
_SP = {
    "D1": _SP_BASE / "d1" / "standard_paragraph_draft.txt",
    "D2": _SP_BASE / "d2" / "standard_paragraph_draft.txt",
    "D4": _SP_BASE / "d4" / "standard_paragraph_draft.txt",
}

_TITLES = {
    "D1": "Chimney stacks",
    "D2": "Roof coverings",
    "D4": "Main walls",
}

_CHECKS = {
    "D1": {
        "past_markers": [
            "condition rating 2",
            "reasonably aligned",
            "tv aerial",
            "six to twelve months",
        ],
        "sp_markers": [
            "taken down and renewed",
            "spreading",
            "frost",
            "flaunch",
        ],
    },
    "D2": {
        "past_markers": [
            "see the limitations",
            "building regulations",
            "legal adviser",
            "serviceable order",
        ],
        "sp_markers": [
            "distening",
            "interlocking concrete",
        ],
    },
    "D4": {
        "past_markers": [
            "option 1",
            "option 2",
            "option 3",
            "option 4",
            "helifix",
        ],
        "sp_markers": [
            "concealed behind mortar",
            "structural engineer should be arranged",
            "water ingress",
        ],
    },
}


def _notes_for(sid: str) -> str:
    notes_path = _PAST[sid].parent / "inspection_notes.txt"
    if notes_path.is_file():
        return notes_path.read_text(encoding="utf-8").strip()
    return ""


def _write_section_bundle(
    sec_dir: Path,
    *,
    sid: str,
    title: str,
    notes: str,
    past: str,
    sp: str,
    merges: dict[float, object],
) -> None:
    sec_dir.mkdir(parents=True, exist_ok=True)
    (sec_dir / "inspection_notes.txt").write_text(notes + "\n", encoding="utf-8")
    (sec_dir / "past_report_draft.txt").write_text(past + "\n", encoding="utf-8")
    (sec_dir / "standard_paragraph_draft.txt").write_text(sp + "\n", encoding="utf-8")

    parts = [
        f"SECTION {sid} — {title}",
        f"past_source={_PAST[sid].relative_to(_ROOT)}",
        f"sp_source={_SP[sid].relative_to(_ROOT)}",
        "",
        "===== INSPECTION NOTES =====",
        "",
        notes,
        "",
        "===== PAST-REPORT DRAFT =====",
        "",
        past,
        "",
        "===== STANDARD-PARAGRAPH DRAFT =====",
        "",
        sp,
        "",
    ]
    for temp, result in merges.items():
        label = f"t{temp:.1f}".replace(".", "p")
        merged_text = (result.merged_text or "").strip()
        (sec_dir / f"merged_{label}.txt").write_text(
            merged_text + "\n", encoding="utf-8"
        )
        parts.extend(
            [
                f"===== MERGED temperature={temp:.1f} "
                f"status={result.meta.get('status')} =====",
                "",
                merged_text,
                "",
            ]
        )
    (sec_dir / "readable.txt").write_text(
        "\n".join(parts).rstrip() + "\n", encoding="utf-8"
    )


def _compare_section(sid: str, past: str, sp: str, merges: dict[float, object]) -> str:
    lines = [f"## {sid}", ""]
    cfg = _CHECKS[sid]

    for temp, result in merges.items():
        text = (result.merged_text or "").strip()
        low = text.lower()
        past_hits = [m for m in cfg["past_markers"] if m in low]
        sp_hits = [m for m in cfg["sp_markers"] if m in low]
        past_open = past.strip().split("\n", 1)[0][:40].lower()
        keeps_opening = past_open[:20] in low if past_open else False
        lines.append(f"### temperature={temp:.1f}")
        lines.append(f"- chars: {len(text)} (past={len(past)}, sp={len(sp)})")
        lines.append(f"- past-style markers kept: {past_hits or 'none'}")
        lines.append(f"- SP-content markers kept: {sp_hits or 'none'}")
        lines.append(f"- keeps past-like opening: {keeps_opening}")
        lines.append("")

    t0 = (merges[0.0].merged_text or "").strip()
    t2 = (merges[0.2].merged_text or "").strip()
    if t0 == t2:
        lines.append("**Diff:** identical outputs at 0.0 and 0.2.")
    else:
        lines.append(
            f"**Diff:** outputs differ (len 0.0={len(t0)}, len 0.2={len(t2)})."
        )
        min_len = min(len(t0), len(t2))
        i = 0
        while i < min_len and t0[i] == t2[i]:
            i += 1
        snippet_0 = t0[max(0, i - 40) : i + 80].replace("\n", " ")
        snippet_2 = t2[max(0, i - 40) : i + 80].replace("\n", " ")
        lines.append(f"- first diff @0.0: …{snippet_0}…")
        lines.append(f"- first diff @0.2: …{snippet_2}…")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = _ROOT / "docs" / "dual-path-merge-runs" / f"temp-compare-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    analysis_parts = [
        f"# Merge temperature compare ({stamp})",
        "",
        "Same inputs merged at temperature 0.0 and 0.2 "
        "(model=gpt-5.4-nano, reasoning_effort=none).",
        "",
    ]
    all_meta: dict = {
        "run_id": out_dir.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "temperatures": list(TEMPS),
        "sections": {},
    }

    for sid in ("D1", "D2", "D4"):
        past = _PAST[sid].read_text(encoding="utf-8").strip()
        sp = _SP[sid].read_text(encoding="utf-8").strip()
        notes = _notes_for(sid)
        title = _TITLES[sid]
        print(f"\n========== {sid} ==========")
        print("past=", _PAST[sid].relative_to(_ROOT))
        print("sp=", _SP[sid].relative_to(_ROOT))

        merges: dict[float, object] = {}
        for temp in TEMPS:
            print(f"--- merge temperature={temp:.1f} ---")
            draft = DualPathDraft(
                section_id=sid,
                section_title=title,
                past_report_draft=past,
                standard_paragraph_draft=sp,
                past_report_source=str(_PAST[sid].relative_to(_ROOT)),
                standard_paragraph_source=str(_SP[sid].relative_to(_ROOT)),
                inspection_notes=notes,
            )
            result = merge_dual_path_drafts(draft, temperature=temp)
            merges[temp] = result
            print(
                "status=",
                result.meta.get("status"),
                "chars=",
                len(result.merged_text or ""),
            )

        _write_section_bundle(
            out_dir / sid.lower(),
            sid=sid,
            title=title,
            notes=notes,
            past=past,
            sp=sp,
            merges=merges,
        )
        analysis_parts.append(_compare_section(sid, past, sp, merges))
        all_meta["sections"][sid] = {
            "past_source": str(_PAST[sid].relative_to(_ROOT)),
            "sp_source": str(_SP[sid].relative_to(_ROOT)),
            "past_chars": len(past),
            "sp_chars": len(sp),
            "merges": {
                f"{temp:.1f}": {
                    "status": merges[temp].meta.get("status"),
                    "chars": len(merges[temp].merged_text or ""),
                    "model": merges[temp].model,
                    "llm_usage": merges[temp].llm_usage,
                    "meta": merges[temp].meta,
                }
                for temp in TEMPS
            },
        }

    analysis = "\n".join(analysis_parts).rstrip() + "\n"
    (out_dir / "ANALYSIS.md").write_text(analysis, encoding="utf-8")
    (out_dir / "meta.json").write_text(
        json.dumps(all_meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nWrote {out_dir}")
    print(analysis)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
