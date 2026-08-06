#!/usr/bin/env python3
"""Tests for free-Space daily collection triggered by an UptimeRobot health ping.

2026-07-18: schedule refresh moved from a single morning window to three data-only
windows per day (10:30 / 12:00 / 18:00, each ±15m). Slot identity allows
one collection per window per day; odds/analysis/prediction are never triggered.
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hf_football_data_hub.daily_hot_pool_scheduler import should_launch, _current_slot


class FreeSchedulerTests(unittest.TestCase):
    def test_uptime_ping_in_morning_window_launches_once_per_slot(self):
        at = datetime.fromisoformat("2026-07-14T10:42:00+08:00")
        slot = _current_slot(at)
        self.assertIsNotNone(slot)
        self.assertTrue(should_launch(at, None))
        # same slot already collected -> no relaunch
        self.assertFalse(should_launch(at, slot))

    def test_all_three_daily_windows_launch(self):
        for hhmm in ("10:42", "12:05", "18:10"):
            at = datetime.fromisoformat(f"2026-07-14T{hhmm}:00+08:00")
            self.assertTrue(should_launch(at, None), hhmm)

    def test_each_window_is_a_distinct_slot(self):
        morning = _current_slot(datetime.fromisoformat("2026-07-14T10:42:00+08:00"))
        evening = _current_slot(datetime.fromisoformat("2026-07-14T18:10:00+08:00"))
        self.assertNotEqual(morning, evening)
        # having run the morning slot must NOT block the evening slot
        self.assertTrue(should_launch(datetime.fromisoformat("2026-07-14T18:10:00+08:00"), morning))

    def test_uptime_ping_outside_windows_never_launches(self):
        for hhmm in ("09:00", "11:00", "13:00", "16:00", "20:00", "23:30"):
            at = datetime.fromisoformat(f"2026-07-14T{hhmm}:00+08:00")
            self.assertIsNone(_current_slot(at), hhmm)
            self.assertFalse(should_launch(at, None), hhmm)

    def test_same_slot_next_day_is_new_slot(self):
        day1 = _current_slot(datetime.fromisoformat("2026-07-14T10:42:00+08:00"))
        day2 = _current_slot(datetime.fromisoformat("2026-07-15T10:42:00+08:00"))
        self.assertNotEqual(day1, day2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
