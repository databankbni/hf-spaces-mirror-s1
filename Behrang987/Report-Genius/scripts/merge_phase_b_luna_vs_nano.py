"""Merge Phase B past+SP drafts for each model (full-stack pack).

Reads:
  docs/dual-path-merge-runs/luna-vs-nano-*/phase_b_generate_only/{gpt54nano,gpt56luna}/

Writes:
  .../phase_c_merge_phase_b/{gpt54nano,gpt56luna}/{d1,d2,d4}/merged.txt

Usage:
  python scripts/merge_phase_b_luna_vs_nano.py
  python scripts/merge_phase_b_luna_vs_nano.py --run-dir docs/dual-path-merge-runs/luna-vs-nano-20260808-070102
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.merge_agent import DualPathDraft, merge_dual_path_drafts

MODELS = (
    ("gpt-5.4-nano", "gpt54nano"),
    ("gpt-5.6-luna", "gpt56luna"),
)
TITLES = {
    "D1": "Chimney stacks",
    "D2": "Roof coverings",
    "D4": "Main walls",
}
MERGE_TEMP = 0.2
PROMPT = "v2"


def _clean(text: str) -> str:
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return t + ("\n" if t else "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--run-dir",
        type=Path,
        default=_ROOT
        / "docs"
        / "dual-path-merge-runs"
        / "luna-vs-nano-20260808-070102",
    )
    args = ap.parse_args()
    run_dir: Path = args.run_dir
    if not run_dir.is_absolute():
        run_dir = _ROOT / run_dir
    gen = run_dir / "phase_b_generate_only"
    out = run_dir / "phase_c_merge_phase_b"
    if not gen.is_dir():
        print("missing", gen)
        return 1
    out.mkdir(parents=True, exist_ok=True)

    meta: dict = {
        "phase": "merge_phase_b_drafts",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(gen.relative_to(_ROOT)),
        "merge_temperature": MERGE_TEMP,
        "prompt_version": PROMPT,
        "note": "Each model merges its own Phase B past+SP drafts (full stack).",
        "models": {},
    }

    for model, tag in MODELS:
        print(f"=== {model} ===")
        model_dir = out / tag
        model_dir.mkdir(parents=True, exist_ok=True)
        mmeta: dict = {"model": model, "sections": {}}
        for sid in ("D1", "D2", "D4"):
            src = gen / tag / sid.lower()
            past = (src / "past_report_draft.txt").read_text(encoding="utf-8")
            sp = (src / "standard_paragraph_draft.txt").read_text(encoding="utf-8")
            notes = (src / "inspection_notes.txt").read_text(encoding="utf-8")
            draft = DualPathDraft(
                section_id=sid,
                section_title=TITLES[sid],
                past_report_draft=past,
                standard_paragraph_draft=sp,
                past_report_source=f"phase_b/{tag}/past",
                standard_paragraph_source=f"phase_b/{tag}/sp",
                inspection_notes=notes,
            )
            result = merge_dual_path_drafts(
                draft,
                temperature=MERGE_TEMP,
                prompt_version=PROMPT,
                model=model,
            )
            sec = model_dir / sid.lower()
            sec.mkdir(parents=True, exist_ok=True)
            (sec / "past_report_draft.txt").write_text(_clean(past), encoding="utf-8")
            (sec / "standard_paragraph_draft.txt").write_text(
                _clean(sp), encoding="utf-8"
            )
            (sec / "inspection_notes.txt").write_text(_clean(notes), encoding="utf-8")
            for name in (
                "past_report_sources.txt",
                "standard_paragraph_sources.txt",
            ):
                p = src / name
                if p.is_file():
                    (sec / name).write_text(
                        p.read_text(encoding="utf-8"), encoding="utf-8"
                    )
            merged = _clean(result.merged_text or "")
            (sec / "merged.txt").write_text(merged, encoding="utf-8")
            status = result.meta.get("status")
            (sec / "readable.txt").write_text(
                (
                    f"SECTION {sid} — {TITLES[sid]}\n"
                    f"model={model}\n"
                    f"merge_temp={MERGE_TEMP} prompt={PROMPT}\n"
                    f"merge_status={status} merge_model={result.model}\n\n"
                    f"===== PAST =====\n\n{past.strip()}\n\n"
                    f"===== SP =====\n\n{sp.strip()}\n\n"
                    f"===== MERGED =====\n\n{merged}"
                ),
                encoding="utf-8",
            )
            print(
                f"  {sid}: status={status} model={result.model} "
                f"chars={len(merged.strip())}"
            )
            mmeta["sections"][sid] = {
                "status": status,
                "merge_model": result.model,
                "past_chars": len(past.strip()),
                "sp_chars": len(sp.strip()),
                "merged_chars": len(merged.strip()),
                "llm_usage": result.llm_usage,
            }
        (model_dir / "meta.json").write_text(
            json.dumps(mmeta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        meta["models"][tag] = mmeta

    lines = [
        "# Phase C — merge Phase B drafts (full stack per model)",
        "",
        f"Merge temp={MERGE_TEMP}, prompt={PROMPT}.",
        "Each model merges its own Phase B past+SP outputs.",
        "",
    ]
    for sid in ("D1", "D2", "D4"):
        n = meta["models"]["gpt54nano"]["sections"][sid]
        l = meta["models"]["gpt56luna"]["sections"][sid]
        lines.extend(
            [
                f"## {sid}",
                f"- nano: past={n['past_chars']} sp={n['sp_chars']} "
                f"merged={n['merged_chars']}",
                f"- luna: past={l['past_chars']} sp={l['sp_chars']} "
                f"merged={l['merged_chars']}",
                "",
            ]
        )
    (out / "COMPARE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("Wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
