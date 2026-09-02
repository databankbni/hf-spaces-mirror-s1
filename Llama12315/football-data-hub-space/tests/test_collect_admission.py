#!/usr/bin/env python3
"""Admission/evidence binding tests for the data-only HF collector."""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import collect_api
from collector.titan007_h2h import build_portable_evidence


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode()).hexdigest()


def admission(match_id: str = "3000393") -> dict:
    value = {
        "schema_version": 1,
        "scope": "JINGCAI_ON_SALE",
        "source": "cp.titan007.com:竞彩足球:cansale=true",
        "match_id": match_id,
        "titan_match_id": match_id,
        "jc_no": "5485001",
        "cansale": True,
        "sale_status": "ON_SALE",
        "league": "日职联",
        "home": "横滨水手",
        "away": "鹿岛鹿角",
        "kickoff_local": "2099-01-01T18:00:00+08:00",
        "deadline_local": "2099-01-01T18:00:00+08:00",
        "jc_handicap": "1",
        "sp": {"home": "3.22", "draw": "3.15", "away": "2.00"},
        "competition_tier": "TIER_2",
        "formal_allowed": True,
    }
    value["admission_sha256"] = digest(value)
    return value


class FakeCollector:
    @staticmethod
    def live_packet(match_id: str) -> dict:
        packet = {
            "ok": True,
            "code": "LIVE_PACKET_READY",
            "match_id": str(match_id),
            "captured_at": "2099-01-01T10:00:00+00:00",
            "identity": {
                "league": "日职联", "home": "横滨水手",
                "away": "鹿岛鹿角",
                "kickoff": "2099-01-01T18:00:00+08:00",
            },
            "raw_payloads": [],
            "packet_sha256": "0" * 64,
        }
        return packet

    @staticmethod
    def build_market_evidence(packet: dict) -> dict:
        value = {
            "schema_version": 1,
            "match_id": str(packet["match_id"]),
            "source": "local_live_capture",
            "source_packet_sha256": str(packet["packet_sha256"]),
            "captured_at": packet["captured_at"],
            "companies": {"皇冠Crown": {"companyID": "3", "both_ok": True}},
            "source_raw_sha256": {"3:AH": "a" * 64},
            "integrity_passed": True,
            "invalid_records": [],
        }
        value["market_evidence_sha256"] = digest(value)
        return value

    @staticmethod
    def _market_evidence_valid(value: dict, *, expected_match_id: str,
                               expected_source_packet_sha: str | None = None) -> bool:
        if str(value.get("match_id")) != str(expected_match_id):
            return False
        claimed = value.get("market_evidence_sha256")
        actual = digest({k: v for k, v in value.items()
                         if k != "market_evidence_sha256"})
        return (claimed == actual
                and value.get("source_packet_sha256") == expected_source_packet_sha)


class CollectorBindingTests(unittest.TestCase):
    def test_portable_h2h_evidence_is_hash_bound_and_path_free(self):
        raw = ("\ufeff<html><script>var v_data = [['26-01-01',1,'联赛','#000',10,'A',20,'B',2,1,'1-0','',0,0,0,999]];</script>"
               "<h2>對賽往績</h2></html>").encode("utf-8")
        with __import__('tempfile').TemporaryDirectory() as td:
            raw_path = Path(td) / "analysis.html"
            raw_path.write_bytes(raw)
            artifact = build_portable_evidence({
                "match_id": "3000393",
                "source_url": "https://zq.titan007.com/analysis/3000393.htm",
                "captured_at": "2099-01-01T00:00:00+00:00",
                "raw_path": str(raw_path),
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
            })
        self.assertTrue(artifact["ok"])
        self.assertNotIn("raw_path", artifact)
        self.assertTrue(artifact["parsed"]["h2h_available"])
        self.assertEqual(
            artifact["evidence_sha256"],
            digest({k: v for k, v in artifact.items() if k != "evidence_sha256"}),
        )

    def test_fc_prefix_suffix_aliases_are_same_team_identity(self):
        self.assertEqual(collect_api._identity_norm("[5]FC安养"), collect_api._identity_norm("安养FC"))
        self.assertEqual(collect_api._identity_norm("FC首尔"), collect_api._identity_norm("首尔FC"))
        self.assertNotEqual(collect_api._identity_norm("FC安养"), collect_api._identity_norm("安养女足"))

    def test_jc_titan_display_aliases_match_live_board(self):
        # Live 2026-08-10 canary: 竞彩 board short names vs Titan schedule ranks.
        self.assertEqual(
            collect_api._identity_norm("布鲁马波"),
            collect_api._identity_norm("布洛马波卡纳[12]"),
        )
        self.assertEqual(
            collect_api._identity_norm("韦斯特罗"),
            collect_api._identity_norm("[8]瓦斯特拉斯"),
        )
        self.assertEqual(
            collect_api._identity_norm("佐加顿斯"),
            collect_api._identity_norm("尤尔加登[3]"),
        )
        self.assertEqual(
            collect_api._identity_norm("葡国民"),
            collect_api._identity_norm("葡萄牙国民[14]"),
        )
        self.assertNotEqual(
            collect_api._identity_norm("布鲁马波"),
            collect_api._identity_norm("天狼星"),
        )

    def test_alias_allows_admission_bind_when_titan_uses_full_name(self):
        packet = {
            "ok": True,
            "code": "LIVE_PACKET_READY",
            "match_id": "2912233",
            "identity": {
                "league": "瑞典超",
                "home": "[1]天狼星",
                "away": "布洛马波卡纳[12]",
            },
        }
        adm = admission("2912233")
        adm.update({
            "league": "瑞典超",
            "home": "天狼星",
            "away": "布鲁马波",
            "jc_no": "5488001",
        })
        adm["admission_sha256"] = digest(
            {k: v for k, v in adm.items() if k != "admission_sha256"})
        bound, receipt = collect_api._bind_jingcai_admission(
            packet, "2912233", adm)
        self.assertIsNotNone(bound)
        self.assertEqual(receipt["status"], "ADMISSION_VALID")
        self.assertTrue(receipt["checks"]["away"])

    def test_kairat_levski_short_names_bind_in_cloud(self):
        packet = {
            "ok": True,
            "code": "LIVE_PACKET_READY",
            "match_id": "3049299",
            "identity": {
                "league": "欧冠杯",
                "home": "[哈萨克超2]阿拉木图凯拉特",
                "away": "索非亚列夫斯基[保甲1]",
            },
        }
        adm = admission("3049299")
        adm.update({
            "league": "欧冠杯",
            "home": "阿拉木图",
            "away": "索列夫",
            "jc_no": "5489002",
        })
        adm["admission_sha256"] = digest(
            {k: v for k, v in adm.items() if k != "admission_sha256"})
        bound, receipt = collect_api._bind_jingcai_admission(
            packet, "3049299", adm)
        self.assertIsNotNone(bound)
        self.assertEqual(receipt["status"], "ADMISSION_VALID")
        self.assertTrue(receipt["checks"]["home"])
        self.assertTrue(receipt["checks"]["away"])

    def test_union_saint_gilloise_short_name_binds_in_cloud(self):
        self.assertTrue(
            collect_api._identity_same_team("圣吉联合", "圣吉罗斯[比甲1]"),
        )

    def test_saudi_al_hazem_legacy_jc_name_binds_in_cloud(self):
        self.assertTrue(collect_api._identity_same_team("拉斯决心", "哈森姆"))
        self.assertFalse(collect_api._identity_same_team("拉斯决心", "艾卜哈"))

    def test_remo_short_name_binds_without_rejecting_cloud_collect(self):
        # 2910852: JC board 里莫 vs Titan 瑞模贝雷. Team names are diagnostic
        # only; hash/scope/id/on_sale/league remain the hard keys.
        self.assertTrue(collect_api._identity_same_team("里莫", "瑞模贝雷"))
        self.assertFalse(collect_api._identity_same_team("里莫", "巴西国际"))
        packet = {
            "ok": True,
            "code": "LIVE_PACKET_READY",
            "match_id": "2910852",
            "identity": {
                "league": "巴西甲",
                "home": "巴西国际",
                "away": "瑞模贝雷",
            },
        }
        adm = admission("2910852")
        adm.update({
            "league": "巴西甲",
            "home": "巴西国际",
            "away": "里莫",
            "jc_no": "5486016",
        })
        adm["admission_sha256"] = digest(
            {k: v for k, v in adm.items() if k != "admission_sha256"})
        bound, receipt = collect_api._bind_jingcai_admission(
            packet, "2910852", adm)
        self.assertIsNotNone(bound)
        self.assertEqual(receipt["status"], "ADMISSION_VALID")
        self.assertTrue(receipt["checks"]["away"])
        self.assertFalse(receipt["team_name_warning"])

    def test_fuzzy_overlap_binds_without_exact_alias(self):
        # No alias required when short board name is contained in Titan identity.
        self.assertTrue(collect_api._identity_same_team("博德闪耀", "[挪超1]博德闪耀"))
        self.assertFalse(collect_api._identity_same_team("里昂", "布斯巴达"))

    def test_missing_admission_fails_closed(self):
        with patch.object(collect_api, "_collector", return_value=FakeCollector):
            result = collect_api.collect_one("3000393", None)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "JINGCAI_ADMISSION_REJECTED")
        self.assertEqual(result["admission_receipt"]["status"], "ADMISSION_MISSING")

    def test_final_packet_binds_admission_evidence_and_hash(self):
        with patch.object(collect_api, "_collector", return_value=FakeCollector):
            result = collect_api.collect_one("3000393", admission())
        self.assertTrue(result["ok"], result)
        packet = result["packet"]
        self.assertIn("jingcai_admission", packet)
        self.assertIn("market_evidence", packet)
        self.assertEqual(
            packet["market_evidence"]["source_packet_sha256"],
            packet["source_packet_sha256"],
        )
        self.assertEqual(
            packet["packet_sha256"],
            digest({k: v for k, v in packet.items()
                    if k != "packet_sha256"}),
        )
        self.assertEqual(result["market_evidence_sha256"],
                         packet["market_evidence"]["market_evidence_sha256"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
