
from __future__ import annotations

from typing import Any


def build_source_match_map(packet: dict[str, Any]) -> dict[str, Any]:
    identity = packet.get("match_identity") or {}
    mapping = dict(identity.get("source_match_map") or {})

    fd = packet.get("fixtures_standings_compact") or {}
    if fd.get("identity_locked") and fd.get("source_match_id"):
        mapping["football-data.org"] = {
            "match_id": fd.get("source_match_id"),
            "identity_score": fd.get("identity_score"),
            "locked": True,
            "attached_fields": ["fixture", "standings"],
        }
    odds = packet.get("odds_crosscheck_compact") or {}
    if odds.get("identity_locked") and odds.get("event_id"):
        mapping["the-odds-api"] = {
            "match_id": odds.get("event_id"),
            "identity_score": odds.get("identity_score"),
            "locked": True,
            "attached_fields": ["event", "odds_crosscheck"],
        }
    return {
        "canonical_match_key": identity.get("canonical_match_key"),
        "primary_source": identity.get("primary_source"),
        "primary_match_id": identity.get("primary_match_id"),
        "sources": mapping,
        "attached_source_count": len(mapping),
    }
