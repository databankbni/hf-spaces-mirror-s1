"""A/B compare merge prompt v1 (preserved) vs v2 (hybrid notes filter).

Uses the same house-note past + SP drafts as the temperature compare.
Runs each prompt version once at temperature 0.0 for a clean contrast.

Usage:
  python scripts/compare_merge_prompts.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.merge_agent import (
    DualPathDraft,
    merge_dual_path_drafts,
    source_names_from_manifest_section,
    write_sources_file,
)

VERSIONS = ("v1", "v2")
TEMPERATURE = 0.0
_SP_MANIFEST = (
    _ROOT
    / ".rics_v2_data"
    / "tenants"
    / "khanchaudhry3@gmail.com"
    / "retrievals"
    / "house-merge-20260806-021600-sp.json"
)

_PAST = {
    "D1": (
        _ROOT
        / "docs"
        / "past-d1-house-runs"
        / "past-d1-house-t0p5-20260808-061444"
        / "generated.txt"
    ),
    "D2": (
        _ROOT
        / "docs"
        / "past-d2-house-runs"
        / "past-d2-house-t0p5-20260808-061708"
        / "generated.txt"
    ),
    "D4": (
        _ROOT
        / "docs"
        / "past-d4-house-runs"
        / "past-d4-house-t0p5-20260808-061929"
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

# Markers that should ideally be DROPPed by v2 notes filter on D1.
_HALLUCINATION_MARKERS = {
    "D1": ["spreading", "frost", "water penetration and frost"],
    "D2": [],
    "D4": [],
}

_STYLE_MARKERS = {
    "D1": ["condition rating 2", "reasonably aligned", "tv aerial"],
    "D2": ["see the limitations", "legal adviser", "serviceable order"],
    "D4": ["option 1", "option 2", "option 3", "option 4", "helifix"],
}


def _notes_for(sid: str) -> str:
    notes_path = _PAST[sid].parent / "inspection_notes.txt"
    if notes_path.is_file():
        return notes_path.read_text(encoding="utf-8").strip()
    return ""


def _past_source_names(sid: str) -> list[str]:
    src = _PAST[sid].parent / "retrieved_sources.txt"
    if not src.is_file():
        return []
    names: list[str] = []
    for line in src.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        # Lines look like "1. Some Report.pdf"
        if ". " in text[:4]:
            text = text.split(". ", 1)[1].strip()
        names.append(text)
    return names


def _write_section_sources(sec_dir: Path, sid: str) -> dict[str, list[str]]:
    past_names = _past_source_names(sid)
    sp_names = source_names_from_manifest_section(
        _SP_MANIFEST,
        sid,
        unique=False,
        include_paragraph_index=True,
    )
    write_sources_file(
        sec_dir / "past_report_sources.txt",
        past_names,
        header="Past-report retrieval sources (PDFs / docs)",
    )
    write_sources_file(
        sec_dir / "standard_paragraph_sources.txt",
        sp_names,
        header="Standard-paragraph retrieval sources",
    )
    return {"past_report_sources": past_names, "standard_paragraph_sources": sp_names}


def _analyse(sid: str, past: str, merges: dict[str, object]) -> str:
    lines = [f"## {sid}", ""]
    for version, result in merges.items():
        text = (result.merged_text or "").strip()
        low = text.lower()
        style_hits = [m for m in _STYLE_MARKERS[sid] if m in low]
        hallu_hits = [m for m in _HALLUCINATION_MARKERS[sid] if m in low]
        lines.append(f"### prompt={version}")
        lines.append(f"- chars: {len(text)} (past={len(past)})")
        lines.append(f"- past-style markers kept: {style_hits or 'none'}")
        if _HALLUCINATION_MARKERS[sid]:
            lines.append(
                f"- hallucination markers still present: {hallu_hits or 'none (good)'}"
            )
        lines.append("")

    v1 = (merges["v1"].merged_text or "").strip()
    v2 = (merges["v2"].merged_text or "").strip()
    if v1 == v2:
        lines.append("**Diff:** v1 and v2 outputs are identical.")
    else:
        lines.append(
            f"**Diff:** outputs differ (len v1={len(v1)}, len v2={len(v2)})."
        )
        min_len = min(len(v1), len(v2))
        i = 0
        while i < min_len and v1[i] == v2[i]:
            i += 1
        sn1 = v1[max(0, i - 40) : i + 100].replace("\n", " ")
        sn2 = v2[max(0, i - 40) : i + 100].replace("\n", " ")
        lines.append(f"- first diff @v1: …{sn1}…")
        lines.append(f"- first diff @v2: …{sn2}…")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = _ROOT / "docs" / "dual-path-merge-runs" / f"prompt-compare-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    analysis_parts = [
        f"# Merge prompt compare ({stamp})",
        "",
        "Same house-note past+SP drafts; temperature=0.0; reasoning_effort=none.",
        "v1 = preserved merge+style prompt; v2 = hybrid with notes-gated filter.",
        "",
    ]
    meta: dict = {
        "run_id": out_dir.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "temperature": TEMPERATURE,
        "prompt_versions": list(VERSIONS),
        "sections": {},
    }

    for sid in ("D1", "D2", "D4"):
        past = _PAST[sid].read_text(encoding="utf-8").strip()
        sp = _SP[sid].read_text(encoding="utf-8").strip()
        notes = _notes_for(sid)
        title = _TITLES[sid]
        print(f"\n========== {sid} ==========")

        merges: dict[str, object] = {}
        sec_dir = out_dir / sid.lower()
        sec_dir.mkdir(parents=True, exist_ok=True)
        (sec_dir / "inspection_notes.txt").write_text(notes + "\n", encoding="utf-8")
        (sec_dir / "past_report_draft.txt").write_text(past + "\n", encoding="utf-8")
        (sec_dir / "standard_paragraph_draft.txt").write_text(
            sp + "\n", encoding="utf-8"
        )
        sources = _write_section_sources(sec_dir, sid)

        readable = [
            f"SECTION {sid} — {title}",
            "",
            "===== INSPECTION NOTES =====",
            "",
            notes,
            "",
            "===== PAST-REPORT SOURCES =====",
            "",
            "\n".join(
                f"{i}. {n}" for i, n in enumerate(sources["past_report_sources"], 1)
            )
            or "(none)",
            "",
            "===== STANDARD-PARAGRAPH SOURCES =====",
            "",
            "\n".join(
                f"{i}. {n}"
                for i, n in enumerate(sources["standard_paragraph_sources"], 1)
            )
            or "(none)",
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

        for version in VERSIONS:
            print(f"--- merge prompt={version} ---")
            draft = DualPathDraft(
                section_id=sid,
                section_title=title,
                past_report_draft=past,
                standard_paragraph_draft=sp,
                past_report_source=str(_PAST[sid].relative_to(_ROOT)),
                standard_paragraph_source=str(_SP[sid].relative_to(_ROOT)),
                inspection_notes=notes,
            )
            result = merge_dual_path_drafts(
                draft,
                temperature=TEMPERATURE,
                prompt_version=version,
            )
            merges[version] = result
            text = (result.merged_text or "").strip()
            (sec_dir / f"merged_{version}.txt").write_text(
                text + "\n", encoding="utf-8"
            )
            readable.extend(
                [
                    f"===== MERGED prompt={version} "
                    f"status={result.meta.get('status')} =====",
                    "",
                    text,
                    "",
                ]
            )
            print("status=", result.meta.get("status"), "chars=", len(text))

        (sec_dir / "readable.txt").write_text(
            "\n".join(readable).rstrip() + "\n", encoding="utf-8"
        )
        analysis_parts.append(_analyse(sid, past, merges))
        meta["sections"][sid] = {
            "past_source": str(_PAST[sid].relative_to(_ROOT)),
            "sp_source": str(_SP[sid].relative_to(_ROOT)),
            "past_report_sources": sources["past_report_sources"],
            "standard_paragraph_sources": sources["standard_paragraph_sources"],
            "merges": {
                version: {
                    "status": merges[version].meta.get("status"),
                    "chars": len(merges[version].merged_text or ""),
                    "model": merges[version].model,
                    "llm_usage": merges[version].llm_usage,
                    "meta": merges[version].meta,
                }
                for version in VERSIONS
            },
        }

    analysis = "\n".join(analysis_parts).rstrip() + "\n"
    (out_dir / "ANALYSIS.md").write_text(analysis, encoding="utf-8")
    (out_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nWrote {out_dir}")
    print(analysis)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
