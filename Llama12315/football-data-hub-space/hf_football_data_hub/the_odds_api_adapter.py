
from __future__ import annotations

"""Optional The Odds API adapter for Phase 2B.

Phase 2A can run without THE_ODDS_API_KEY. This module is included so the package
can be upgraded by adding the secret only; odds data is never allowed to replace
Titan007 AH/OU as the primary source.
"""

from typing import Any
import os


def attach_odds_crosscheck_compact(primary_identity: dict[str, Any], api_key: str | None = None) -> dict[str, Any]:
    api_key = api_key or os.getenv("THE_ODDS_API_KEY")
    if not api_key:
        return {
            "enabled": False,
            "source": "the-odds-api",
            "status": "missing_key_optional",
            "event_id": None,
            "identity_locked": False,
            "identity_score": 0,
            "has_spreads": False,
            "has_totals": False,
            "conflict_with_titan007": False,
            "decision_impact": "none",
        }
    # Deliberately conservative placeholder. Real event lookup varies by sport key
    # and coverage, so Hermes should enable Phase 2B after a separate key/quota test.
    return {
        "enabled": True,
        "source": "the-odds-api",
        "status": "configured_but_phase2b_not_auto_enabled",
        "event_id": None,
        "identity_locked": False,
        "identity_score": 0,
        "has_spreads": False,
        "has_totals": False,
        "conflict_with_titan007": False,
        "decision_impact": "none",
    }
