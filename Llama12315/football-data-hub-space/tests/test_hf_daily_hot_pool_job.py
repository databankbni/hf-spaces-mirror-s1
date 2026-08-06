#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.hf_daily_hot_pool_job import TZ, build_pool


class DailyHotPoolJobTests(unittest.TestCase):
    def row(self, match_id: str) -> dict:
        return {"match_id": match_id, "league": "测试联赛", "home": "主队", "away": "客队", "kickoff_local": "2026-07-13T18:30:00+08:00", "status": "0", "has_ah": True, "has_ou": True}

    def test_stable_two_capture_pool_is_cloud_only_and_accepted(self):
        at1 = datetime.fromisoformat("2026-07-13T10:40:00+08:00")
        at2 = datetime.fromisoformat("2026-07-13T10:45:00+08:00")
        pool = build_pool(at1, [self.row("1"), self.row("2")], at2, [self.row("1"), self.row("2")])
        self.assertTrue(pool["accepted"])
        self.assertEqual(pool["collector"], "hf_scheduled_job")
        self.assertTrue(pool["cloud_only"])
        self.assertEqual(pool["freshness_status"], "CURRENT_DATE_CONFIRMED_STABLE")

    def test_unstable_pool_is_not_accepted_or_uploaded(self):
        at1 = datetime.fromisoformat("2026-07-13T10:40:00+08:00")
        at2 = datetime.fromisoformat("2026-07-13T10:45:00+08:00")
        pool = build_pool(at1, [self.row("1"), self.row("2")], at2, [self.row("3"), self.row("4")])
        self.assertFalse(pool["accepted"])
        self.assertEqual(pool["freshness_status"], "DEGRADED_UNSTABLE_POOL")

    def test_cross_day_upcoming_hot_matches_are_retained(self):
        first_at = datetime.fromisoformat("2026-07-14T10:40:00+08:00")
        second_at = datetime.fromisoformat("2026-07-14T10:45:00+08:00")
        today = self.row("today")
        today["kickoff_local"] = "2026-07-14T19:35:00+08:00"
        tomorrow = self.row("tomorrow")
        tomorrow["kickoff_local"] = "2026-07-15T02:45:00+08:00"
        pool = build_pool(first_at, [today, tomorrow], second_at, [today, tomorrow])
        self.assertTrue(pool["accepted"])
        self.assertEqual(pool["raw_hot_count"], 2)
        self.assertEqual(pool["today_hot_count"], 1)
        self.assertEqual(pool["upcoming_hot_count"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
