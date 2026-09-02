from __future__ import annotations

import glob
import os
from typing import List, Optional

import yaml

from .models import BugSpec

REQUIRED = ("id", "title", "app", "category", "ground_truth", "report")


def load_spec(path: str) -> BugSpec:
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        raise ValueError("{0} is missing required field(s): {1}".format(path, ", ".join(missing)))
    return BugSpec(
        id=str(data["id"]), title=str(data["title"]), app=str(data["app"]),
        category=str(data["category"]), ground_truth=str(data["ground_truth"]).upper(),
        control=bool(data.get("control", False)), report=str(data["report"]),
        pattern=str(data.get("pattern", "")), max_steps=int(data.get("max_steps", 15)),
        viewport=dict(data.get("viewport") or {"width": 1000, "height": 800}))


def load_suite(bugs_dir: str, only: Optional[str] = None) -> List[BugSpec]:
    specs = [load_spec(p) for p in sorted(glob.glob(os.path.join(bugs_dir, "*.yaml")))]
    if only:
        wanted = {s.strip() for s in only.split(",") if s.strip()}
        specs = [s for s in specs if s.id in wanted]
        unknown = wanted - {s.id for s in specs}
        if unknown:
            raise ValueError("unknown bug id(s): {0}".format(", ".join(sorted(unknown))))
    if not specs:
        raise ValueError("no bug specs found in {0}".format(bugs_dir))
    return specs
