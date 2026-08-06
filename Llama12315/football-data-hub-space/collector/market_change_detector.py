#!/usr/bin/env python3
"""Canonical, side-effect-free market delta detection for data-only monitoring."""
from __future__ import annotations

import hashlib
import json
from typing import Any

WATER_THRESHOLD = 0.03
LINE_THRESHOLD = 0.25


def _number(value: Any) -> float | None:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def canonical(snapshot: dict[str, Any]) -> dict[str, Any]:
    identity = snapshot.get("identity", {})
    crown = snapshot.get("markets", {}).get("Crown", {})
    ah, ou = crown.get("AH", {}), crown.get("OU", {})
    return {
        "match_id": str(snapshot.get("match_id", "")),
        "identity": {key: identity.get(key) for key in ("league", "home", "away", "kickoff")},
        # Capture time/provenance must be persisted with the newest packet, but
        # they are not market-change triggers. Otherwise every polling pass is
        # a synthetic change and causes unnecessary Dataset uploads.
        "source_mode": str(snapshot.get("source_mode", "unknown")),
        "remote_packet_found": bool(snapshot.get("remote_packet_found", False)),
        "live_refresh_performed": bool(snapshot.get("freshness_contract", {}).get("live_refresh_performed", False)),
        "eligible_for_directional_analysis": bool(snapshot.get("freshness_contract", {}).get("eligible_for_directional_analysis", False)),
        "freshness_tier": str(snapshot.get("freshness_contract", {}).get("freshness_tier", "")),
        "max_age_seconds": _number(snapshot.get("freshness_contract", {}).get("max_age_seconds")),

        "crown": {
            "AH": {"line": _number(ah.get("line")), "home_water": _number(ah.get("home_water")), "away_water": _number(ah.get("away_water"))},
            "OU": {"line": _number(ou.get("line")), "over_water": _number(ou.get("over_water")), "under_water": _number(ou.get("under_water"))},
        },
    }


def digest(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(canonical(snapshot), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def compare(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    old, new = canonical(previous), canonical(current)
    events: list[str] = []
    fail_closed = False
    if old["match_id"] != new["match_id"] or old["identity"] != new["identity"]:
        events.append("IDENTITY_CONFLICT")
        fail_closed = True
    for market, water_keys in (("AH", ("home_water", "away_water")), ("OU", ("over_water", "under_water"))):
        old_market, new_market = old["crown"][market], new["crown"][market]
        old_line, new_line = old_market["line"], new_market["line"]
        if old_line is None or new_line is None:
            if old_line != new_line:
                events.append(f"CROWN_{market}_AVAILABILITY")
        elif abs(new_line - old_line) >= LINE_THRESHOLD - 1e-9:
            events.append(f"CROWN_{market}_LINE")
        for key in water_keys:
            before, after = old_market[key], new_market[key]
            if before is None or after is None:
                if before != after:
                    events.append(f"CROWN_{market}_AVAILABILITY")
            elif abs(after - before) >= WATER_THRESHOLD - 1e-9:
                events.append(f"CROWN_{market}_WATER")
    events = sorted(set(events))
    return {
        "changed": bool(events),
        "event_types": events,
        "fail_closed": fail_closed,
        "previous_canonical_sha256": digest(previous),
        "current_canonical_sha256": digest(current),
        "raw_payload_changed": previous.get("raw_payload_sha256") != current.get("raw_payload_sha256"),
    }
