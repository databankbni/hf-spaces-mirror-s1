from hf_football_data_hub.quality import score_packet, detect_source_conflicts

def test_quality_blocks_missing_odds():
    packet = {"match_id": "1", "titan007_compact": {"data_quality": {"ok": False}}}
    q = score_packet(packet)
    assert q["recommendation_allowed"] is False
    assert "odds_core" in q["missing_critical_fields"]

def test_kicked_off_conflict_blocks():
    packet = {"titan007_compact": {"比赛已开球": True}}
    conflicts = detect_source_conflicts(packet)
    assert any(c["action"] == "recommendation_blocked" for c in conflicts)
