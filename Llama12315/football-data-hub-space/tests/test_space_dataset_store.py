#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hf_football_data_hub.dataset_store import DatasetStore, packet_lookup_days, shanghai_day


class FakeApi:
    def __init__(self):
        self.calls = []

    def upload_file(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True}


class DatasetStoreUploadTests(unittest.TestCase):
    def test_remote_packet_preserves_local_live_origin_through_hf_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DatasetStore()
            store.root = Path(tmp)
            packet = {
                "captured_at": "2999-01-01T00:00:00+00:00",
                "freshness_contract": {
                    "source_mode": "hf_remote_packet",
                    "origin_source_mode": "local_live_packet",
                    "live_refresh_performed": True,
                    "captured_at": "2999-01-01T00:00:00+00:00",
                    "max_age_seconds": 999999999,
                },
            }
            with patch.object(store, "load_json", return_value=packet):
                _, freshness = store.packet_with_freshness("data/compact_packets/2999-01-01/1.json")
        self.assertTrue(freshness["eligible_for_directional_analysis"])
        self.assertEqual(freshness["source_mode"], "hf_remote_packet")
        self.assertEqual(freshness["origin_source_mode"], "local_live_packet")

    def test_configured_space_store_uploads_compact_artifact_to_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DatasetStore()
            store.root = Path(tmp)
            fake = FakeApi()
            configured = SimpleNamespace(has_remote_dataset=True, hf_dataset_repo="Llama12315/football-data-hub", hf_token="test-token")
            with patch("hf_football_data_hub.dataset_store.settings", configured), \
                 patch.object(store, "_upload_file_if_configured", return_value=True) as upload:
                result = store.save_json("data/hot_match_pool/2026-07-14.json", {"accepted": True})
        self.assertTrue(result["remote_uploaded"])
        upload.assert_called_once()

    def test_packet_lookup_days_cover_shanghai_neighbors(self):
        today = shanghai_day()
        self.assertEqual(packet_lookup_days(), [today, shanghai_day(-1), shanghai_day(1)])
        self.assertEqual(packet_lookup_days(today)[0], today)
        self.assertIn(shanghai_day(-1), packet_lookup_days(today))
        self.assertEqual(packet_lookup_days("2026-08-01"), ["2026-08-01"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
