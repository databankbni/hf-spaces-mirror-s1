from __future__ import annotations

from typing import Any


def score_packet(packet: dict[str, Any]) -> dict:
    identity = packet.get("match_identity", {})
    if identity:
        identity_score = int(identity.get("identity_score", 0) or 0) if identity.get("identity_locked") else 0
    else:
        identity_score = 100 if packet.get("match_id") else 0

    titan = packet.get("titan007_compact", {})
    dq = titan.get("data_quality", {})
    odds_ok = bool(dq.get("ok")) and bool(titan.get("crown", {}).get("ah") or titan.get("crown", {}).get("ou"))
    odds_score = 90 if odds_ok else 40

    kicked = bool(titan.get("比赛已开球"))
    missing_critical = []
    if identity_score < 80:
        missing_critical.append("match_identity_lock")
    if odds_score < 85:
        missing_critical.append("odds_core")
    if kicked:
        missing_critical.append("already_kicked_off")

    recommendation_allowed = not missing_critical

    return {
        "overall": int((identity_score * 0.35) + (odds_score * 0.65)),
        "identity": identity_score,
        "odds": odds_score,
        "form": 0,
        "standings": 0,
        "advanced_stats": 0,
        "injury_lineup": 0,
        "weather": 0,
        "historical": 0,
        "missing_critical_fields": missing_critical,
        "missing_noncritical_fields": [
            "form_layer_phase2",
            "standings_layer_phase2",
            "injury_lineup_phase2",
            "advanced_stats_phase3",
            "weather_optional_phase1_if_no_coords",
        ],
        "recommendation_allowed": recommendation_allowed,
    }


def detect_source_conflicts(packet: dict) -> list[dict]:
    conflicts: list[dict] = []
    identity = packet.get("match_identity", {})
    if identity and not identity.get("identity_locked"):
        conflicts.append({
            "field": "match_identity",
            "severity": "high",
            "sources": ["packet_identity"],
            "values": [identity.get("block_reason", "identity_not_locked")],
            "action": "recommendation_blocked",
        })
    titan = packet.get("titan007_compact", {})
    for msg in titan.get("cross_book_signals", []) or []:
        conflicts.append({
            "field": "odds_layer.cross_book",
            "severity": "medium",
            "sources": ["titan007:crown", "titan007:pinnacle"],
            "values": [msg],
            "action": "risk_flag",
        })
    if titan.get("比赛已开球"):
        conflicts.append({
            "field": "match_status",
            "severity": "high",
            "sources": ["titan007"],
            "values": ["already_kicked_off"],
            "action": "recommendation_blocked",
        })
    return conflicts
