
from __future__ import annotations

from typing import Any


def phase2_source_conflicts(packet: dict[str, Any]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    fd = packet.get("fixtures_standings_compact") or {}
    if fd.get("enabled") and fd.get("status") == "identity_not_locked":
        conflicts.append({
            "field": "fixtures_standings_compact.identity",
            "severity": "medium",
            "sources": ["titan007", "football-data.org"],
            "values": fd.get("ambiguous_candidates") or [],
            "action": "confidence_down",
        })
    if fd.get("enabled") and fd.get("status") in {"FOOTBALL_DATA_FORBIDDEN_OR_PLAN_LIMIT", "error"}:
        conflicts.append({
            "field": "fixtures_standings_compact.api",
            "severity": "low",
            "sources": ["football-data.org"],
            "values": [fd.get("error") or fd.get("status")],
            "action": "risk_flag",
        })
    weather = packet.get("weather_compact") or {}
    if weather.get("weather_available") and weather.get("risk_flags"):
        conflicts.append({
            "field": "weather_compact.ou_weather_risk",
            "severity": "medium",
            "sources": ["open-meteo"],
            "values": weather.get("risk_flags"),
            "action": "confidence_down_for_ou",
        })
    odds = packet.get("odds_crosscheck_compact") or {}
    if odds.get("conflict_with_titan007"):
        conflicts.append({
            "field": "odds_crosscheck_compact.market_conflict",
            "severity": "medium",
            "sources": ["titan007", "the-odds-api"],
            "values": odds.get("conflict_detail") or [],
            "action": "confidence_down",
        })
    return conflicts


def summarize_source_conflicts(conflicts: list[dict[str, Any]]) -> dict[str, Any]:
    has_conflict = bool(conflicts)
    actions = sorted({c.get("action") for c in conflicts if c.get("action")})
    decision_impact = "none"
    if any(a == "recommendation_blocked" for a in actions):
        decision_impact = "block"
    elif any(a in {"confidence_down", "confidence_down_for_ou"} for a in actions):
        decision_impact = "confidence_down"
    elif actions:
        decision_impact = "risk_flag"
    return {
        "has_conflict": has_conflict,
        "conflict_count": len(conflicts),
        "conflict_type": [c.get("field") for c in conflicts],
        "decision_impact": decision_impact,
        "conflicts": conflicts[:8],
    }
