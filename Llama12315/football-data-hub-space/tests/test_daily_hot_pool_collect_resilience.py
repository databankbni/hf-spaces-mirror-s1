#!/usr/bin/env python3
"""Daily pool must still publish when Crow sbOddsData.js is empty."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hf_football_data_hub.daily_hot_pool_scheduler import TZ, _rows, collect


def _schedule_fixture() -> dict[str, list[list[str] | None]]:
    row = [""] * 63
    row[0], row[2], row[5], row[8] = "3062521", "欧冠杯", "萨迪纳摩", "维京"
    row[11], row[12], row[13], row[62] = "03:00", "2026,7,19,03,00,00", "0", "1"
    league = [""] * 11
    league[0], league[10] = "欧冠杯", "1"
    return {"A": [row], "B": [league]}


class _MemoryStore:
    def __init__(self) -> None:
        self.saved: dict[str, dict] = {}

    def load_json(self, path: str):
        return self.saved.get(path)

    def save_json(self, path: str, payload: dict):
        self.saved[path] = payload
        return {"path": path}


class CrowRosterResilienceTests(unittest.TestCase):
    def test_schedule_rows_without_crow_filter_keep_fixtures(self):
        captured = datetime.fromisoformat("2026-08-18T12:05:00+08:00").astimezone(TZ)
        rows = _rows(_schedule_fixture(), captured, None)
        self.assertEqual([row["match_id"] for row in rows], ["3062521"])

    def test_empty_crow_set_would_drop_every_row(self):
        captured = datetime.fromisoformat("2026-08-18T12:05:00+08:00").astimezone(TZ)
        rows = _rows(_schedule_fixture(), captured, set())
        self.assertEqual(rows, [])

    def test_collect_publishes_schedule_pool_when_crow_roster_empty(self):
        memory = _MemoryStore()
        captured = datetime.fromisoformat("2026-08-18T12:05:00+08:00")
        with patch("hf_football_data_hub.daily_hot_pool_scheduler.store", memory), \
             patch("hf_football_data_hub.daily_hot_pool_scheduler._crow_ids", return_value=set()), \
             patch("hf_football_data_hub.daily_hot_pool_scheduler._schedule", return_value=_schedule_fixture()):
            pool = collect(now_fn=lambda: captured, sleep_fn=lambda _s: None)
        self.assertTrue(pool["accepted"], pool)
        self.assertEqual(pool["match_ids"], ["3062521"])
        self.assertFalse(pool["roster"]["verified"])
        self.assertEqual(pool["roster"]["size"], 0)
        self.assertIn("crow_roster_empty_schedule_fallback", pool["roster"]["status"])
        self.assertIn("data/crow_full_pool/2026-08-18/merged.json", memory.saved)


if __name__ == "__main__":
    unittest.main(verbosity=2)
