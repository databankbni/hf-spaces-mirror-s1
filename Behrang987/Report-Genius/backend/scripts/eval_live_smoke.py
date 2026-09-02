#!/usr/bin/env python3
"""Live smoke test for backend.evaluation against a real generated report.

Feeds a downloaded RICS report .txt (generated prose) plus the matching retrieval
manifest (surveyor notes + baseline paragraphs) through the real
``evaluate_report`` path, then prints the rollup and the manifest location.

    python backend/scripts/eval_live_smoke.py \
        --report-txt "../RICS_Report_1784838610593.txt" \
        --report-id c56b92c9a13b4f8fa8caf2c13e4ea159 \
        --limit 6

Requires OPENAI_API_KEY (shell or repo .env). Costs one judge call per section.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_dotenv_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv_file(REPO_ROOT / ".env")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.config import settings  # noqa: E402
from backend.evaluation import evaluate_report, evaluation_manifest_path  # noqa: E402
from backend.models.report import GeneratedSection, ReportResult  # noqa: E402

_HEADING = re.compile(r"^([A-Z][0-9]{0,2})\.\s+(.+?)\s*$")
_RULE = re.compile(r"^-{5,}$")
_PLACEHOLDER = "[NOT GENERATED]"


def parse_report_txt(path: Path) -> list[tuple[str, str, str]]:
    """Return [(section_id, title, prose)] for sections that have real prose."""
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[tuple[str, str, str]] = []
    current: tuple[str, str] | None = None
    buf: list[str] = []

    def flush() -> None:
        if current is None:
            return
        text = "\n".join(buf).strip()
        if text and _PLACEHOLDER not in text:
            out.append((current[0], current[1], text))

    for idx, line in enumerate(lines):
        heading = _HEADING.match(line)
        next_is_rule = idx + 1 < len(lines) and _RULE.match(lines[idx + 1].strip())
        if heading and next_is_rule:
            flush()
            current = (heading.group(1), heading.group(2))
            buf = []
            continue
        if _RULE.match(line.strip()):
            continue
        if current is not None:
            buf.append(line)
    flush()
    return out


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-txt", required=True)
    ap.add_argument("--report-id", required=True, help="Existing retrieval manifest id")
    ap.add_argument("--tenant-id", default="default")
    ap.add_argument("--limit", type=int, default=0, help="0 = all sections")
    ap.add_argument("--sections", default="", help="Comma-separated ids, e.g. D1,D3")
    args = ap.parse_args()

    txt_path = Path(args.report_txt)
    if not txt_path.is_absolute():
        txt_path = (Path.cwd() / txt_path).resolve()
    if not txt_path.is_file():
        print(f"report txt not found: {txt_path}")
        return 2

    parsed = parse_report_txt(txt_path)
    wanted = {s.strip().upper() for s in args.sections.split(",") if s.strip()}
    if wanted:
        parsed = [p for p in parsed if p[0].upper() in wanted]
    if args.limit > 0:
        parsed = parsed[: args.limit]

    result = ReportResult(
        tenant_id=args.tenant_id,
        schema_version=2,
        sections=[
            GeneratedSection(section_id=sid, title=title, text=text)
            for sid, title, text in parsed
        ],
    )

    from backend.evaluation.judge_llm import (
        is_available,
        resolved_model,
        resolved_provider,
    )

    print("── config ────────────────────────────────────────────────")
    print(f"evaluation_enabled       : {settings.evaluation_enabled}")
    print(f"evaluation_llm_coverage  : {settings.evaluation_llm_coverage}")
    print(f"evaluation_llm_faithful. : {settings.evaluation_llm_faithfulness}")
    print(f"provider                 : {resolved_provider()}")
    print(f"model                    : {resolved_model()}")
    print(f"concurrency              : {settings.evaluation_concurrency}")
    print(f"openai key present       : {bool(settings.openai_api_key)}")
    print(f"gemini key present       : {bool(settings.gemini_api_key)}")
    print(f"judge available          : {is_available()}")
    print(f"sections parsed from txt : {len(parsed)}")

    evaluation = await evaluate_report(
        result, report_id=args.report_id, by_id=None
    )
    if evaluation is None:
        print("\nevaluate_report returned None (EVALUATION_ENABLED is false).")
        return 1

    print("\n── rollup ────────────────────────────────────────────────")
    print(f"status            : {evaluation.status}")
    print(f"coverage_rate     : {_pct(evaluation.coverage_rate)}")
    print(f"note atoms judged : {evaluation.total_note_atoms}")
    print(f"covered atoms     : {evaluation.covered_note_atoms}")
    print(f"faithfulness      : {_pct(evaluation.faithfulness_score)}")
    print(f"model             : {evaluation.model}")
    print(f"error             : {evaluation.error}")

    print("\n── per section ───────────────────────────────────────────")
    for sec in evaluation.sections:
        print(
            f"{sec.section_id:<4} {_pct(sec.coverage_rate):>7}  "
            f"cov={sec.covered_count} part={sec.partial_count} "
            f"miss={sec.missing_count}  notes={len(sec.observations)}"
            + (f"  ERROR={sec.error}" if sec.error else "")
        )

    if evaluation.missing_facts:
        print("\n── missing / partial facts ───────────────────────────────")
        for ref in evaluation.missing_facts:
            print(f"  [{ref.section_id}] {ref.fact}")

    first = next((s for s in evaluation.sections if s.note_judgments), None)
    if first is not None:
        print(f"\n── sample judgments ({first.section_id}) ─────────────────")
        print(
            json.dumps(
                [j.model_dump() for j in first.note_judgments],
                indent=2,
                ensure_ascii=False,
            )
        )

    path = evaluation_manifest_path(args.tenant_id, args.report_id)
    print("\n── manifest ──────────────────────────────────────────────")
    print(f"path   : {path}")
    print(f"exists : {path.is_file()}")
    if path.is_file():
        print(f"bytes  : {path.stat().st_size}")
        print(f"keys   : {sorted(json.loads(path.read_text(encoding='utf-8')))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
