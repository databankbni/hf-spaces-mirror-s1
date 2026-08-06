from hf_football_data_hub.match_identity_resolver import (
    build_primary_identity,
    evaluate_cross_source_candidate,
    attach_candidate_or_block,
    detect_team_type,
)
from hf_football_data_hub.quality import score_packet, detect_source_conflicts


def primary_identity():
    return build_primary_identity(
        "2913640",
        compact={"match_id": "2913640"},
        identity_hint={
            "league": "Finland Veikkausliiga",
            "home_team": "KuPS",
            "away_team": "Ilves",
            "kickoff_utc": "2026-07-08T15:00:00+00:00",
        },
    )


def test_primary_titan007_match_id_locks_identity():
    identity = build_primary_identity("2913640", compact={"match_id": "2913640"})
    assert identity["canonical_match_key"] == "titan007:2913640"
    assert identity["identity_locked"] is True
    assert identity["identity_score"] == 100
    assert identity["team_alias_policy"]["alias_not_sufficient_for_merge"] is True


def test_cross_source_same_match_locks_with_alias_time_league_direction():
    result = evaluate_cross_source_candidate(primary_identity(), {
        "source": "example_source",
        "source_match_id": "abc123",
        "league": "Finland Veikkausliiga",
        "home_team": "Kuopion Palloseura",
        "away_team": "埃尔维斯",
        "kickoff_utc": "2026-07-08T15:09:00+00:00",
        "home_team_type": "first_team",
        "away_team_type": "first_team",
    })
    assert result.locked is True
    assert result.identity_score >= 90
    assert result.checks["home_away_direction_match"] is True


def test_home_away_swapped_blocks_automatic_merge():
    result = evaluate_cross_source_candidate(primary_identity(), {
        "source": "example_source",
        "source_match_id": "swapped1",
        "league": "Finland Veikkausliiga",
        "home_team": "Ilves",
        "away_team": "KuPS",
        "kickoff_utc": "2026-07-08T15:00:00+00:00",
    })
    assert result.locked is False
    assert result.block_reason == "HOME_AWAY_SWAPPED"
    assert result.checks["home_away_swapped"] is True


def test_time_mismatch_blocks_automatic_merge():
    result = evaluate_cross_source_candidate(primary_identity(), {
        "source": "example_source",
        "source_match_id": "late1",
        "league": "Finland Veikkausliiga",
        "home_team": "KuPS",
        "away_team": "Ilves",
        "kickoff_utc": "2026-07-10T15:00:00+00:00",
    })
    assert result.locked is False
    assert result.block_reason == "KICKOFF_TIME_HARD_MISMATCH"


def test_team_type_mismatch_blocks_youth_or_women_false_positive():
    assert detect_team_type("KuPS U21") == "u21"
    result = evaluate_cross_source_candidate(primary_identity(), {
        "source": "example_source",
        "source_match_id": "u21_match",
        "league": "Finland Veikkausliiga",
        "home_team": "KuPS U21",
        "away_team": "Ilves U21",
        "kickoff_utc": "2026-07-08T15:00:00+00:00",
    })
    assert result.locked is False
    assert result.block_reason == "TEAM_TYPE_MISMATCH"


def test_identity_not_locked_blocks_packet_quality_and_prediction():
    packet = {
        "match_identity": {"identity_locked": False, "identity_score": 74, "block_reason": "DATA_IDENTITY_UNCERTAIN"},
        "titan007_compact": {"data_quality": {"ok": True}, "crown": {"ah": {"current_line": "半球"}}},
    }
    q = score_packet(packet)
    conflicts = detect_source_conflicts(packet)
    assert q["recommendation_allowed"] is False
    assert "match_identity_lock" in q["missing_critical_fields"]
    assert any(c["action"] == "recommendation_blocked" for c in conflicts)


def test_attach_candidate_records_blocked_source():
    identity = attach_candidate_or_block(primary_identity(), {
        "source": "example_source",
        "source_match_id": "bad",
        "league": "Wrong League",
        "home_team": "KuPS",
        "away_team": "Ilves",
        "kickoff_utc": "2026-07-08T15:00:00+00:00",
    })
    assert identity["blocked_sources"]
    assert identity["blocked_sources"][0]["block_reason"] == "LEAGUE_MISMATCH"
