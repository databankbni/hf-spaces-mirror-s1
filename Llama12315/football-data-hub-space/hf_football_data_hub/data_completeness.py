
from __future__ import annotations

from typing import Any


def _score_bool(ok: bool, yes: int = 100, no: int = 0) -> int:
    return yes if ok else no


def compute_data_completeness_score(packet: dict[str, Any]) -> dict[str, Any]:
    identity = packet.get("match_identity") or {}
    titan = packet.get("titan007_compact") or {}
    fd = packet.get("fixtures_standings_compact") or {}
    weather = packet.get("weather_compact") or {}
    source_map = packet.get("source_match_map") or {}

    identity_score = 100 if identity.get("identity_locked") and int(identity.get("identity_score") or 0) >= 90 else 0

    # Conservative heuristics; vendor compact schemas vary across Hermes versions.
    crown = titan.get("crown") or titan.get("Crown") or titan.get("皇冠") or {}
    pinnacle = titan.get("pinnacle") or titan.get("Pinnacle") or titan.get("平博") or {}
    ah_ok = bool((crown.get("ah") or crown.get("AH")) or (pinnacle.get("ah") or pinnacle.get("AH")) or titan.get("handicap"))
    ou_ok = bool((crown.get("ou") or crown.get("OU")) or (pinnacle.get("ou") or pinnacle.get("OU")) or titan.get("over_under"))
    ah_score = 90 if ah_ok else 50 if titan else 0
    ou_score = 90 if ou_ok else 50 if titan else 0

    attached = (source_map.get("attached_source_count") or len(source_map.get("sources") or {})) if source_map else 1
    cross_book = 70 if attached >= 2 else 55

    # Raw/history depth is summarized by vendor packet; if unavailable, give compact-only baseline.
    odds_history_depth = 80 if titan else 0
    freshness = 90 if titan else 0
    standings = 85 if fd.get("fixtures_standings_available") and fd.get("status") == "ok" else 0
    form = 35 if fd.get("fixture") else 0
    injury = 0  # Phase 3
    weather_score = 80 if weather.get("weather_available") else 0

    # Weighted to avoid one missing optional source blocking Phase 2A.
    overall = round(
        identity_score * 0.18 + ah_score * 0.16 + ou_score * 0.16 + cross_book * 0.08 +
        odds_history_depth * 0.10 + freshness * 0.08 + standings * 0.12 + form * 0.04 +
        weather_score * 0.08
    )
    if identity_score == 0:
        overall = 0
    if overall >= 80:
        grade, limit = "A", "STRICT50_ALLOWED_WITH_EV_AND_STRONG_REVIEW"
    elif overall >= 65:
        grade, limit = "B", "LOW_STAKE_OR_SOFT_PICK_ONLY"
    elif overall >= 50:
        grade, limit = "C", "SOFT_NO_BET_OR_SHADOW_ONLY"
    else:
        grade, limit = "D", "DATA_INCOMPLETE_BLOCK"
    return {
        "identity_lock": identity_score,
        "ah_coverage": ah_score,
        "ou_coverage": ou_score,
        "cross_book_coverage": cross_book,
        "odds_history_depth": odds_history_depth,
        "data_freshness": freshness,
        "standings_available": standings,
        "recent_form_available": form,
        "injury_available": injury,
        "weather_available": weather_score,
        "overall_score": overall,
        "grade": grade,
        "decision_limit": limit,
        "phase2_market_plus_structured_mode": True,
        "phase3_sources_missing": True,
    }


def prediction_quality_guard(packet: dict[str, Any]) -> dict[str, Any]:
    score = packet.get("data_completeness_score") or compute_data_completeness_score(packet)
    conflicts = packet.get("source_conflict_audit") or {}
    reasons = []
    allowed = True
    if score.get("overall_score", 0) < 50:
        allowed = False
        reasons.append("DATA_INCOMPLETE_BLOCK")
    if conflicts.get("decision_impact") == "block":
        allowed = False
        reasons.append("SOURCE_CONFLICT_BLOCK")
    return {
        "data_completeness_grade": score.get("grade"),
        "phase1_1_market_only_mode": False,
        "phase2_structured_sources_enabled": True,
        "phase3_sources_missing": True,
        "decision_allowed": allowed,
        "decision_limit": score.get("decision_limit"),
        "source_conflict_impact": conflicts.get("decision_impact", "none"),
        "reason": reasons,
    }
