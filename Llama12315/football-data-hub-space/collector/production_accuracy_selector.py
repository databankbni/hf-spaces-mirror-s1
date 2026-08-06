#!/usr/bin/env python3
"""Production AH direction source promoted from the validated E2 research track.

One immutable pre-match packet produces one hash-bound direction candidate:
Crown opening low-water anchor + five-company current majority confirmation.
No result fields, no network access, no independent ledger or publication path.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

try:
    from scripts.competition_tier_policy import classify as classify_tier
except ModuleNotFoundError:  # direct scripts/hermes_hf_client.py execution
    from competition_tier_policy import classify as classify_tier

COMPANIES = ("3", "24", "31", "14", "17")
SOURCE_ID = "ah_opening_anchor_five_book_majority_v1"
REQUIRED_CURRENT_VOTES = 4


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _num(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _side(quote: dict[str, Any] | None) -> str | None:
    quote = quote or {}
    home = _num(quote.get("water")); away = _num(quote.get("opponent_water"))
    if home is None or away is None or abs(home - away) < 1e-12:
        return None
    return "home" if home < away else "away"


def _tier(packet: dict[str, Any]) -> dict[str, Any]:
    identity = packet.get("identity") or {}
    stage = str(
        ((packet.get("competition_stage_evidence") or {}).get("stage"))
        or (((packet.get("fundamentals") or {}).get("summary") or {}).get("competition_stage"))
        or ""
    )
    return classify_tier(
        str(identity.get("league") or ""), str(identity.get("home") or ""),
        str(identity.get("away") or ""), competition_stage=stage,
    )


def _feature_payload(packet: dict[str, Any]) -> dict[str, Any]:
    companies: dict[str, Any] = {}
    odds = packet.get("odds") or {}
    for cid in COMPANIES:
        ah = ((odds.get(cid) or {}).get("AH") or {})
        companies[cid] = {
            "opening": {key: (ah.get("opening") or {}).get(key) for key in ("line", "water", "opponent_water")},
            "current": {key: (ah.get("current") or {}).get(key) for key in ("line", "water", "opponent_water")},
            "kicked_off": bool(ah.get("kicked_off")),
        }
    return {
        "schema_version": 1,
        "direction_source": SOURCE_ID,
        "match_id": str(packet.get("match_id") or ""),
        "source_packet_sha256": str(packet.get("packet_sha256") or ""),
        "captured_at": packet.get("captured_at"),
        "companies": companies,
    }


def build_accuracy_features(packet: dict[str, Any]) -> dict[str, Any]:
    features = _feature_payload(packet)
    features["accuracy_features_sha256"] = hashlib.sha256(_canonical(features)).hexdigest()
    return features


def accuracy_features_valid(features: dict[str, Any] | None, *, expected_match_id: str,
                            expected_source_packet_sha: str | None = None) -> bool:
    if not isinstance(features, dict):
        return False
    expected = str(features.get("accuracy_features_sha256") or "")
    body = {key: value for key, value in features.items() if key != "accuracy_features_sha256"}
    actual = hashlib.sha256(_canonical(body)).hexdigest()
    source_sha = str(features.get("source_packet_sha256") or "")
    return bool(
        expected == actual and str(features.get("match_id") or "") == str(expected_match_id)
        and features.get("direction_source") == SOURCE_ID
        and len(source_sha) == 64
        and (expected_source_packet_sha is None or source_sha == expected_source_packet_sha)
        and set((features.get("companies") or {})) == set(COMPANIES)
    )


def build_evidence(packet: dict[str, Any]) -> dict[str, Any]:
    embedded = packet.get("accuracy_features")
    if accuracy_features_valid(
        embedded,
        expected_match_id=str(packet.get("match_id") or ""),
    ):
        features = dict(embedded)
        source = "packet_accuracy_features"
    else:
        features = build_accuracy_features(packet)
        source = "packet_odds_projection"
    companies = features["companies"]
    anchor = _side((companies.get("3") or {}).get("opening"))
    current_sides = {cid: _side((companies.get(cid) or {}).get("current")) for cid in COMPANIES}
    valid = [side for side in current_sides.values() if side in {"home", "away"}]
    home_votes = valid.count("home"); away_votes = valid.count("away")
    majority = "home" if home_votes > away_votes else "away" if away_votes > home_votes else None
    votes = max(home_votes, away_votes)
    tier = _tier(packet)
    reason_codes: list[str] = []
    if anchor not in {"home", "away"}:
        reason_codes.append("CROWN_OPENING_ANCHOR_UNAVAILABLE")
    if len(valid) < REQUIRED_CURRENT_VOTES:
        reason_codes.append("FIVE_COMPANY_CURRENT_VOTES_LT4")
    if majority is None:
        reason_codes.append("FIVE_COMPANY_CURRENT_MAJORITY_UNAVAILABLE")
    if anchor and majority and anchor != majority:
        reason_codes.append("OPENING_ANCHOR_CURRENT_MAJORITY_DISAGREE")
    if tier.get("primary_accuracy_eligible") is not True:
        reason_codes.append("PRIMARY_TIER_INELIGIBLE")
    if any((companies.get(cid) or {}).get("kicked_off") for cid in COMPANIES):
        reason_codes.append("POST_KICKOFF_MARKET_FORBIDDEN")
    crown_current = (companies.get("3") or {}).get("current") or {}
    if any(crown_current.get(key) in (None, "") for key in ("line", "water", "opponent_water")):
        reason_codes.append("CROWN_CURRENT_OFFER_INCOMPLETE")
    eligible = bool(
        not reason_codes and anchor == majority and votes >= REQUIRED_CURRENT_VOTES
        and len(valid) >= REQUIRED_CURRENT_VOTES
    )
    if anchor in {"home", "away"} and majority in {"home", "away"}:
        anchor_majority_relation = "agree" if anchor == majority else "disagree"
    else:
        anchor_majority_relation = "unknown"
    # Challenger is observational only: five-company current AH majority without
    # requiring the opening anchor. Never grants production A authority.
    challenger_blockers: list[str] = []
    if len(valid) < REQUIRED_CURRENT_VOTES:
        challenger_blockers.append("FIVE_COMPANY_CURRENT_VOTES_LT4")
    if majority is None:
        challenger_blockers.append("FIVE_COMPANY_CURRENT_MAJORITY_UNAVAILABLE")
    if tier.get("primary_accuracy_eligible") is not True:
        challenger_blockers.append("PRIMARY_TIER_INELIGIBLE")
    if any((companies.get(cid) or {}).get("kicked_off") for cid in COMPANIES):
        challenger_blockers.append("POST_KICKOFF_MARKET_FORBIDDEN")
    if any(crown_current.get(key) in (None, "") for key in ("line", "water", "opponent_water")):
        challenger_blockers.append("CROWN_CURRENT_OFFER_INCOMPLETE")
    challenger_eligible = bool(
        not challenger_blockers
        and majority in {"home", "away"}
        and votes >= REQUIRED_CURRENT_VOTES
        and len(valid) >= REQUIRED_CURRENT_VOTES
    )
    evidence: dict[str, Any] = {
        "schema_version": 2,
        "source_id": SOURCE_ID,
        "source": source,
        "match_id": str(packet.get("match_id") or ""),
        "packet_sha256": str(packet.get("packet_sha256") or ""),
        "accuracy_features_sha256": features.get("accuracy_features_sha256"),
        "captured_pre_match": not any((companies.get(cid) or {}).get("kicked_off") for cid in COMPANIES),
        "selected_market": "AH",
        "selected_side": anchor if eligible else None,
        "opening_anchor": {"company_id": "3", "side": anchor},
        "current_majority": {
            "side": majority, "votes": votes, "valid_votes": len(valid),
            "home_votes": home_votes, "away_votes": away_votes, "company_sides": current_sides,
        },
        "anchor_majority_relation": anchor_majority_relation,
        "tracks": {"E1": anchor in {"home", "away"}, "E2": eligible},
        "eligible": eligible,
        "reason_codes": sorted(set(reason_codes)),
        "competition_tier": tier,
        "production_authority": True,
        "publication_allowed": True,
        "non_account": False,
        "challenger_shadow": {
            "source_id": "five_current_consensus_ah_v1",
            "selected_market": "AH",
            "selected_side": majority if challenger_eligible else None,
            "eligible_shadow": challenger_eligible,
            "reason_codes": sorted(set(challenger_blockers)),
            "votes": votes,
            "valid_votes": len(valid),
            "production_authority": False,
            "publication_allowed": False,
            "non_account": True,
            "note": (
                "Shadow-only majority AH challenger; does not create Strategy-A. "
                "Promotion requires pre-registered prospective gates."
            ),
        },
    }
    evidence["evidence_sha256"] = hashlib.sha256(_canonical(evidence)).hexdigest()
    return evidence
