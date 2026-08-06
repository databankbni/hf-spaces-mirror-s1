from __future__ import annotations

from typing import Any


def identity_conflicts(packet: dict[str, Any]) -> list[dict[str, Any]]:
    identity = packet.get("match_identity") or {}
    conflicts: list[dict[str, Any]] = []
    if not identity.get("identity_locked"):
        conflicts.append({
            "field": "match_identity.identity_locked",
            "severity": "critical",
            "sources": [identity.get("primary_source") or "unknown"],
            "values": [identity.get("block_reason") or "identity_not_locked"],
            "action": "recommendation_blocked",
        })
    for blocked in identity.get("blocked_sources", []) or []:
        conflicts.append({
            "field": "match_identity.blocked_sources",
            "severity": "high",
            "sources": [blocked.get("source", "unknown")],
            "values": [blocked.get("block_reason"), blocked.get("identity_score")],
            "action": "source_not_merged",
        })
    for amb in identity.get("ambiguous_candidates", []) or []:
        conflicts.append({
            "field": "match_identity.ambiguous_candidates",
            "severity": "medium",
            "sources": [amb.get("source", "unknown")],
            "values": [amb.get("block_reason"), amb.get("identity_score")],
            "action": "manual_confirmation_required",
        })
    return conflicts
