
from hf_football_data_hub.data_completeness import compute_data_completeness_score, prediction_quality_guard
from hf_football_data_hub.source_match_map import build_source_match_map
from hf_football_data_hub.phase2_conflict_detector import summarize_source_conflicts


def _base_packet():
    return {
        "match_identity": {
            "identity_locked": True,
            "identity_score": 100,
            "canonical_match_key": "titan007:123",
            "primary_source": "titan007",
            "primary_match_id": "123",
            "source_match_map": {"titan007": {"match_id": "123", "locked": True, "identity_score": 100}},
        },
        "titan007_compact": {"crown": {"ah": {}, "ou": {}}, "data_quality": {"ok": True}},
        "fixtures_standings_compact": {"status": "ok", "fixtures_standings_available": True, "source_match_id": "fd-1", "identity_locked": True, "identity_score": 94, "fixture": {"matchday": 1}},
        "weather_compact": {"weather_available": True},
    }


def test_source_match_map_attaches_football_data():
    m = build_source_match_map(_base_packet())
    assert m["canonical_match_key"] == "titan007:123"
    assert "football-data.org" in m["sources"]


def test_data_completeness_allows_phase2_packet():
    p = _base_packet()
    p["source_match_map"] = build_source_match_map(p)
    score = compute_data_completeness_score(p)
    assert score["overall_score"] >= 65
    guard = prediction_quality_guard({**p, "data_completeness_score": score, "source_conflict_audit": {"decision_impact": "none"}})
    assert guard["decision_allowed"] is True


def test_conflict_summary_blocks_when_recommendation_blocked():
    s = summarize_source_conflicts([{"field": "x", "action": "recommendation_blocked"}])
    assert s["has_conflict"] is True
    assert s["decision_impact"] == "block"
