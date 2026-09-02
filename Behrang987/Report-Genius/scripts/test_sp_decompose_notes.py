"""Standalone test: decompose inspection notes into issues and write JSON.

Does NOT run SP retrieval or generation — decompose only.

Example:
  python scripts/test_sp_decompose_notes.py
  python scripts/test_sp_decompose_notes.py --force-llm

  python scripts/test_sp_decompose_notes.py --force-llm --section D1
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

from backend.standard_paragraphs.decompose import decompose_notes_detailed
from backend.standard_paragraphs.note_issues_manifest import record_note_issues

TENANT = "khanchaudhry3@gmail.com"

# Surveyor notes provided for standalone decompose testing (per subsection).
CASES = [
    {
        "section_id": "D1",
        "section_title": "Chimney stacks",
        "observations": [
            "Chimney stack: Brick chimney with some repointing required. "
            "Flashing is cracked and lead flashing has come away. "
            "TV aerial appears to be leaning. "
            "Repairs and repointing should be carried out by a competent contractor."
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
        "section_id": "D3",
        "section_title": "Rainwater pipes and gutters",
        "observations": [
            "Rainwater fittings: UPVC gutters and gullies present. "
            "A blockage was noted. The point of discharge is unknown. "
            "Front right rainwater downpipe discharges below ground. "
            "Some fittings are brittle and faded."
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
    {
        "section_id": "D5",
        "section_title": "Windows",
        "observations": [
            "Windows: Timber sash, double-glazed windows. "
            "Some surface rust and deterioration noted. "
            "Condensation/missing items also noted."
        ],
    },
    {
        "section_id": "D6",
        "section_title": "Outside doors (including patio doors)",
        "observations": [
            "External doors: Timber-framed external doors. No weather bar fitted."
        ],
    },
    {
        "section_id": "D7",
        "section_title": "Conservatory and porches",
        "observations": [
            "Conservatory: May require building regulation approval. "
            "Pitched glazed roof with no significant defects noted."
        ],
    },
    {
        "section_id": "D8",
        "section_title": "Other joinery and finishes",
        "observations": [
            "Surface rust/deterioration to timber boards.",
        ],
    },
    {
        "section_id": "D9",
        "section_title": "Other",
        "observations": [
            "No contamination noted.",
        ],
    },
    {
        "section_id": "F1",
        "section_title": "Electricity",
        "observations": [
            "modern electricity.",
        ],
    },
    {
        "section_id": "F2",
        "section_title": "Gas/oil",
        "observations": [
            "no smell of gas, otherwise okay.",
        ],
    },
    {
        "section_id": "F3",
        "section_title": "Water",
        "observations": [
            "super, water is lit.",
        ],
    },
    {
        "section_id": "F4",
        "section_title": "Heating",
        "observations": [
            "combination condensing boiler. The heating was functional, "
            "no whipped to radiators.",
        ],
    },
    {
        "section_id": "F5",
        "section_title": "Water heating",
        "observations": [
            "there was supply of hot water, combination condensing.",
        ],
    },
    {
        "section_id": "F6",
        "section_title": "Drainage",
        "observations": [
            "drainage, inspection chamber lifted, blockage was noted. "
            "Soil and vent stack UPVC, both balloon grating and clean rod.",
        ],
    },
    {
        "section_id": "F7",
        "section_title": "Common services",
        "observations": [
            "alarm with burglar alarm with alarm box and sensors.",
        ],
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Test SP note decompose only")
    parser.add_argument(
        "--force-llm",
        action="store_true",
        help="Always call the LLM (even for short single-issue notes)",
    )
    parser.add_argument(
        "--run-id",
        default="",
        help="Manifest id (default: sp-decompose-YYYYMMDD-HHMMSS)",
    )
    parser.add_argument(
        "--tenant",
        default=TENANT,
        help=f"Tenant id (default: {TENANT})",
    )
    parser.add_argument(
        "--section",
        default="",
        help="Optional section id filter (e.g. D1). Default: all cases.",
    )
    args = parser.parse_args()

    run_id = args.run_id.strip() or (
        "sp-decompose-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    )
    want = (args.section or "").strip().upper()
    cases = [c for c in CASES if not want or c["section_id"].upper() == want]
    if not cases:
        print(f"No cases match --section={want!r}")
        return 1

    print("tenant=", args.tenant)
    print("run_id=", run_id)
    print("force_llm=", args.force_llm)
    print("sections=", [c["section_id"] for c in cases])
    print("(decompose only — not wired into SP generation)")

    summary: dict = {
        "run_id": run_id,
        "tenant_id": args.tenant,
        "force_llm": args.force_llm,
        "sections": {},
    }

    for case in cases:
        sid = case["section_id"]
        title = case["section_title"]
        obs = list(case["observations"])
        result = decompose_notes_detailed(
            obs,
            section_id=sid,
            section_title=title,
            force_llm=args.force_llm,
            allow_when_disabled=True,
        )
        path = record_note_issues(
            args.tenant,
            run_id,
            section_id=sid,
            section_title=title,
            observations=obs,
            issues=list(result.issues),
            source="standalone_decompose_test",
            used_llm=result.used_llm,
        )
        summary["sections"][sid] = {
            "section_title": title,
            "observations": obs,
            "issues": list(result.issues),
            "issue_count": len(result.issues),
            "used_llm": result.used_llm,
            "method": result.method,
            "manifest_path": str(path),
        }
        print(f"\n=== {sid} ({title}) ===")
        print("method=", result.method, "used_llm=", result.used_llm)
        print("observations:")
        for o in obs:
            print(" -", o)
        print("issues:")
        for i, issue in enumerate(result.issues, 1):
            print(f" {i}. {issue}")

    sample_out = (
        _ROOT
        / "backend"
        / "standard_paragraphs"
        / "samples"
        / f"{run_id}.note_issues.json"
    )
    sample_out.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    first = cases[0]["section_id"]
    print("\ntenant manifest=", summary["sections"][first]["manifest_path"])
    print("sample copy=", sample_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
