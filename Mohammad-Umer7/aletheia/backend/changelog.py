"""The Mind-Change Log: an append-only JSONL ledger of every belief change."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from backend import memory

CHANGELOG_PATH = memory.DATA_DIR / "changelog.jsonl"


def append_entry(entry: dict) -> dict:
    """Append one event (with UTC timestamp) and return it."""
    stamped = {"ts": datetime.now(timezone.utc).isoformat(), **entry}
    CHANGELOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CHANGELOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(stamped, ensure_ascii=False) + "\n")
    return stamped


def read_entries(newest_first: bool = True) -> list[dict]:
    if not CHANGELOG_PATH.exists():
        return []
    entries = []
    with CHANGELOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return list(reversed(entries)) if newest_first else entries
