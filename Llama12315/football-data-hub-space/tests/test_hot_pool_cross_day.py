#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hf_football_data_hub.daily_hot_pool_scheduler import TZ, _rows


class CrossDaySchedulerTests(unittest.TestCase):
    def test_retains_tomorrow_hot_match_using_row_timestamp(self):
        row = [""] * 63
        row[0], row[2], row[5], row[8] = "cross-day", "测试联赛", "主队", "客队"
        row[11], row[12], row[13], row[39], row[40], row[62] = (
            "02:45", "2026,6,15,02,45,00", "0", "", "2.5", "1"
        )
        league = [""] * 11
        league[0], league[10] = "测试联赛", "1"
        source: dict[str, list[list[str] | None]] = {"A": [row], "B": [league]}
        captured = datetime.fromisoformat("2026-07-14T10:45:00+08:00").astimezone(TZ)

        rows = _rows(source, captured)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kickoff_local"], "2026-07-15T02:45:00+08:00")


if __name__ == "__main__":
    unittest.main(verbosity=2)
