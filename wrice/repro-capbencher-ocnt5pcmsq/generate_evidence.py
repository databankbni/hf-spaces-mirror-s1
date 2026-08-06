"""Generate evidence bundle JSON for CapBencher reproduction."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from capbencher.simulation import generate_evidence_bundle


def write_bundle(out_file: Path) -> None:
    bundle = generate_evidence_bundle()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    evidence_dir = Path(__file__).parent / "evidence"
    out_file = evidence_dir / "bundle.json"
    write_bundle(out_file)
    print(f"Evidence bundle written to {out_file}")
