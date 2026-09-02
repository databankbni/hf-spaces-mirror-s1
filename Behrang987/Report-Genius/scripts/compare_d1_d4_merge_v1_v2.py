"""Re-merge latest D1/D4 past+SP drafts with v1; pack beside existing v2.

Source drafts:
  docs/dual-path-merge-runs/d1-d4-dual-path-merge-v2-luna-t0p2-20260808-232150/
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
from backend.merge_agent import DualPathDraft, merge_dual_path_drafts

SRC = (
    _ROOT
    / "docs"
    / "dual-path-merge-runs"
    / "d1-d4-dual-path-merge-v2-luna-t0p2-20260808-232150"
)
D2_COMPARE = (
    _ROOT
    / "docs"
    / "dual-path-merge-runs"
    / "d2-triple-merge-v1-vs-v2-luna-t0p2-20260808-231020"
)
OUT_ROOT = _ROOT / "docs" / "dual-path-merge-runs"
TITLES = {"D1": "Chimney stacks", "D4": "Main walls"}


def _ensure_nl(text: str) -> str:
    t = text or ""
    return t if t.endswith("\n") else t + "\n"


def main() -> int:
    if not SRC.is_dir():
        print("missing source pack:", SRC, file=sys.stderr)
        return 1

    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    run_id = f"d1-d4-merge-v1-vs-v2-luna-t0p2-{stamp}"
    out = OUT_ROOT / run_id
    out.mkdir(parents=True, exist_ok=True)

    model = (settings.merge_agent_model or "").strip() or settings.mapping_model
    temp = float(settings.merge_agent_temperature)
    print("run_id=", run_id)
    print("source=", SRC.name)
    print("model=", model, "temp=", temp)

    rows: list[dict] = []
    for sid in ("D1", "D4"):
        sdir = SRC / sid.lower()
        past = (sdir / "past_report_draft.txt").read_text(encoding="utf-8")
        sp = (sdir / "standard_paragraph_draft.txt").read_text(encoding="utf-8")
        notes = (sdir / "inspection_notes.txt").read_text(encoding="utf-8")
        v2 = (sdir / "merged.txt").read_text(encoding="utf-8")

        print(f"\n===== {sid} merge v1 =====")
        draft = DualPathDraft(
            section_id=sid,
            section_title=TITLES[sid],
            past_report_draft=past,
            standard_paragraph_draft=sp,
            inspection_notes=notes,
        )
        merged = merge_dual_path_drafts(
            draft,
            prompt_version="v1",
            temperature=temp,
            model=model,
        )
        v1 = _ensure_nl((merged.merged_text or "").strip())
        print(
            "status=",
            merged.meta.get("status"),
            "prompt=",
            merged.meta.get("prompt_version"),
            "chars=",
            len(v1.strip()),
        )

        odir = out / sid.lower()
        odir.mkdir(parents=True, exist_ok=True)
        (odir / "inspection_notes.txt").write_text(_ensure_nl(notes), encoding="utf-8")
        (odir / "past_report_draft.txt").write_text(_ensure_nl(past), encoding="utf-8")
        (odir / "standard_paragraph_draft.txt").write_text(
            _ensure_nl(sp), encoding="utf-8"
        )
        (odir / "merged_v1.txt").write_text(v1, encoding="utf-8")
        (odir / "merged_v2.txt").write_text(_ensure_nl(v2), encoding="utf-8")
        (odir / "readable.txt").write_text(
            (
                f"SECTION {sid} — {TITLES[sid]}\n"
                f"model={model} temp={temp}\n"
                f"source_drafts={SRC.name}\n\n"
                f"===== NOTES =====\n\n{notes.strip()}\n\n"
                f"===== PAST =====\n\n{past.strip()}\n\n"
                f"===== SP =====\n\n{sp.strip()}\n\n"
                f"===== MERGED v1 =====\n\n{v1.strip()}\n\n"
                f"===== MERGED v2 =====\n\n{v2.strip()}\n"
            ),
            encoding="utf-8",
        )
        rows.append(
            {
                "section_id": sid,
                "past_chars": len(past.strip()),
                "sp_chars": len(sp.strip()),
                "v1_chars": len(v1.strip()),
                "v2_chars": len(v2.strip()),
                "v1_words": len(v1.split()),
                "v2_words": len(v2.split()),
                "v1_status": merged.meta.get("status"),
                "v1_prompt_version": merged.meta.get("prompt_version"),
            }
        )

    lines = [
        f"D1/D4 merge v1 vs v2 (same past+SP as {SRC.name})",
        f"run_id={run_id}",
        f"model={model} temp={temp}",
        "Fair: only merge prompt version changes; style_block not injected.",
        "",
    ]
    for r in rows:
        lines.append(
            f"{r['section_id']}: past={r['past_chars']} sp={r['sp_chars']} "
            f"v1={r['v1_chars']} v2={r['v2_chars']} "
            f"(words v1={r['v1_words']} v2={r['v2_words']})"
        )
    lines.extend(["", f"D2 prior fair compare: {D2_COMPARE.name}", ""])
    if D2_COMPARE.is_dir():
        for i in (1, 2, 3):
            s = D2_COMPARE / f"sample_{i}"
            past = (s / "past_report_draft.txt").read_text(encoding="utf-8").strip()
            sp = (s / "standard_paragraph_draft.txt").read_text(encoding="utf-8").strip()
            v1 = (s / "merged_v1.txt").read_text(encoding="utf-8").strip()
            v2 = (s / "merged_v2.txt").read_text(encoding="utf-8").strip()
            lines.append(
                f"D2 sample_{i}: past={len(past)} sp={len(sp)} "
                f"v1={len(v1)} v2={len(v2)}"
            )

    (out / "COMPARE.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "meta.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "source": str(SRC),
                "model": model,
                "temp": temp,
                "sections": rows,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("\nout=", out)
    print("compare=", out / "COMPARE.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
