from __future__ import annotations

"""
Match Identity Lock for HF Football Data Hub Phase 1.1.

Purpose
-------
Prevent cross-source match contamination. Team aliases are used only for
candidate recall; a match is considered safe to merge only when identity checks
pass (primary match_id, kickoff, league, home/away direction, team type).

Phase 1.1 still uses Titan007 match_id as the primary anchor. Future sources
can attach to the canonical_match_key only through evaluate_cross_source_candidate.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import re
import unicodedata


IDENTITY_VERSION = "match_identity_lock_v1"
LOCK_THRESHOLD = 90
OBSERVE_THRESHOLD = 80
MAX_KICKOFF_DIFF_MINUTES = 15
HARD_TIME_MISMATCH_MINUTES = 24 * 60

TEAM_TYPE_MARKERS = {
    "women": [" women", " w", "女足", "女子", "femenino", "feminino", "ladies"],
    "u23": ["u23", "u-23", "under 23", "23岁"],
    "u21": ["u21", "u-21", "under 21", "21岁"],
    "u20": ["u20", "u-20", "under 20", "20岁"],
    "u19": ["u19", "u-19", "under 19", "19岁"],
    "reserve": ["reserve", "reserves", "ii", "b team", " b", "二队", "预备队", "后备"],
}


@dataclass
class IdentityCandidateResult:
    source: str
    source_match_id: str | None
    identity_score: int
    locked: bool
    observe_only: bool
    block_reason: str | None
    checks: dict[str, Any]


def normalize_text(value: Any) -> str:
    """Normalize team/league strings for robust but conservative matching."""
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("&", " and ")
    text = re.sub(r"[\u3000\s]+", " ", text)
    text = re.sub(r"[\(\)\[\]\{\},.;:'\"`~!@#$%^*_+=|\\/<>?-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def detect_team_type(name: Any) -> str:
    norm = f" {normalize_text(name)} "
    if not norm.strip():
        return "unknown"
    for team_type, markers in TEAM_TYPE_MARKERS.items():
        for marker in markers:
            m = f" {normalize_text(marker)} " if marker.strip().isascii() else normalize_text(marker)
            if m and m in norm:
                return team_type
    return "first_team"


def load_alias_registry(path: str | Path | None = None) -> dict[str, Any]:
    if path is None:
        path = Path(__file__).resolve().parent.parent / "config" / "team_alias_registry.json"
    path = Path(path)
    if not path.exists():
        return {"teams": []}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _aliases_for(name: str, registry: dict[str, Any] | None = None) -> set[str]:
    """Return normalized aliases for a name. The original normalized name is always included."""
    norm = normalize_text(name)
    aliases = {norm} if norm else set()
    if not norm or not registry:
        return aliases
    for team in registry.get("teams", []):
        candidates = [team.get("canonical_name", ""), *(team.get("aliases") or [])]
        normalized = {normalize_text(x) for x in candidates if x}
        if norm in normalized:
            aliases.update(normalized)
            break
    return {x for x in aliases if x}


def alias_match(expected: str | None, candidate: str | None, registry: dict[str, Any] | None = None) -> bool:
    if not expected or not candidate:
        return False
    expected_aliases = _aliases_for(expected, registry)
    cand_norm = normalize_text(candidate)
    if cand_norm in expected_aliases:
        return True
    # Conservative containment only for long names; avoids matching "city" or "fc".
    for alias in expected_aliases:
        if len(alias) >= 5 and (alias in cand_norm or cand_norm in alias):
            return True
    return False


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(text, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def kickoff_diff_minutes(a: Any, b: Any) -> int | None:
    da, db = parse_datetime(a), parse_datetime(b)
    if not da or not db:
        return None
    return int(abs((da.astimezone(timezone.utc) - db.astimezone(timezone.utc)).total_seconds()) // 60)


def _safe_get(d: dict[str, Any] | None, *keys: str) -> Any:
    if not isinstance(d, dict):
        return None
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def extract_identity_hints_from_compact(compact: dict[str, Any] | None) -> dict[str, Any]:
    """Best-effort extraction. Phase 1 compact packets may not include teams/league yet."""
    compact = compact or {}
    return {
        "match_id": _safe_get(compact, "match_id", "id"),
        "league": _safe_get(compact, "league", "联赛", "competition", "赛事"),
        "home_team": _safe_get(compact, "home_team", "主队", "home", "主"),
        "away_team": _safe_get(compact, "away_team", "客队", "away", "客"),
        "kickoff_utc": _safe_get(compact, "kickoff_utc", "kickoff", "match_time", "开赛时间"),
        "status": _safe_get(compact, "status", "比赛状态"),
    }


def build_primary_identity(
    match_id: str,
    compact: dict[str, Any] | None = None,
    identity_hint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create the primary Titan007 identity lock.

    For Phase 1.1, an explicit Titan007 match_id is considered a hard primary
    anchor. Team/league/kickoff hints improve traceability but are not required
    before additional sources are attached.
    """
    hints = extract_identity_hints_from_compact(compact)
    if identity_hint:
        hints.update({k: v for k, v in identity_hint.items() if v not in (None, "")})
    match_id = str(match_id or hints.get("match_id") or "").strip()

    if not match_id:
        score = 0
        locked = False
        block_reason = "PRIMARY_MATCH_ID_MISSING"
    else:
        score = 100
        locked = True
        block_reason = None

    home = hints.get("home_team")
    away = hints.get("away_team")
    team_type_home = detect_team_type(home)
    team_type_away = detect_team_type(away)

    return {
        "version": IDENTITY_VERSION,
        "canonical_match_key": f"titan007:{match_id}" if match_id else None,
        "identity_locked": locked,
        "primary_source": "titan007",
        "primary_match_id": match_id or None,
        "identity_score": score,
        "match_confidence": score,
        "manual_confirmation_required": not locked,
        "block_reason": block_reason,
        "league": hints.get("league"),
        "home_team": home,
        "away_team": away,
        "home_team_type": team_type_home,
        "away_team_type": team_type_away,
        "kickoff_utc": hints.get("kickoff_utc"),
        "status": hints.get("status"),
        "ambiguous_candidates": [],
        "blocked_sources": [],
        "source_match_map": {
            "titan007": {
                "match_id": match_id or None,
                "identity_score": score,
                "locked": locked,
                "anchor_type": "primary_match_id_exact",
            }
        },
        "team_alias_policy": {
            "alias_used_for": "candidate_recall_only",
            "alias_not_sufficient_for_merge": True,
            "required_confirmation_fields": [
                "source_match_id",
                "league",
                "kickoff_time",
                "home_team_alias",
                "away_team_alias",
                "home_away_direction",
                "team_type",
            ],
        },
        "cross_source_attachment_policy": {
            "min_identity_score_to_merge": LOCK_THRESHOLD,
            "observe_only_range": [OBSERVE_THRESHOLD, LOCK_THRESHOLD - 1],
            "max_kickoff_diff_minutes": MAX_KICKOFF_DIFF_MINUTES,
            "hard_time_mismatch_minutes": HARD_TIME_MISMATCH_MINUTES,
            "home_away_swapped_blocks_ah_merge": True,
            "llm_guessing_allowed": False,
        },
    }


def evaluate_cross_source_candidate(
    primary_identity: dict[str, Any],
    candidate: dict[str, Any],
    registry: dict[str, Any] | None = None,
) -> IdentityCandidateResult:
    """Score whether an external-source candidate is the same match.

    Hard blockers are conservative: league mismatch, team-type mismatch, swapped
    home/away direction, or large kickoff difference blocks automatic merging.
    """
    registry = registry or load_alias_registry()
    score = 0
    checks: dict[str, Any] = {}
    hard_block: str | None = None

    primary_mid = str(primary_identity.get("primary_match_id") or "")
    source_mid = str(candidate.get("source_match_id") or candidate.get("match_id") or "")
    source = str(candidate.get("source") or "unknown")

    if source == primary_identity.get("primary_source") and source_mid and source_mid == primary_mid:
        score += 100
        checks["same_source_match_id_exact"] = True
    else:
        checks["same_source_match_id_exact"] = False

    p_league = primary_identity.get("league")
    c_league = candidate.get("league") or candidate.get("competition")
    if p_league and c_league:
        league_match = normalize_text(p_league) == normalize_text(c_league)
        checks["league_match"] = league_match
        if league_match:
            score += 20
        else:
            hard_block = "LEAGUE_MISMATCH"
    else:
        checks["league_match"] = None

    diff = kickoff_diff_minutes(primary_identity.get("kickoff_utc"), candidate.get("kickoff_utc") or candidate.get("kickoff"))
    checks["kickoff_time_diff_minutes"] = diff
    if diff is not None:
        if diff <= MAX_KICKOFF_DIFF_MINUTES:
            score += 25
        elif diff > HARD_TIME_MISMATCH_MINUTES:
            hard_block = hard_block or "KICKOFF_TIME_HARD_MISMATCH"
        else:
            hard_block = hard_block or "KICKOFF_TIME_MISMATCH"

    p_home, p_away = primary_identity.get("home_team"), primary_identity.get("away_team")
    c_home = candidate.get("home_team") or candidate.get("home")
    c_away = candidate.get("away_team") or candidate.get("away")

    home_match = alias_match(p_home, c_home, registry) if p_home and c_home else None
    away_match = alias_match(p_away, c_away, registry) if p_away and c_away else None
    swapped = bool(
        p_home and p_away and c_home and c_away
        and alias_match(p_home, c_away, registry)
        and alias_match(p_away, c_home, registry)
    )
    checks["home_team_alias_match"] = home_match
    checks["away_team_alias_match"] = away_match
    checks["home_away_direction_match"] = (home_match is True and away_match is True)
    checks["home_away_swapped"] = swapped
    if swapped:
        hard_block = hard_block or "HOME_AWAY_SWAPPED"
    if home_match is True:
        score += 20
    if away_match is True:
        score += 20
    if home_match is True and away_match is True:
        score += 10

    p_htype = primary_identity.get("home_team_type") or detect_team_type(p_home)
    p_atype = primary_identity.get("away_team_type") or detect_team_type(p_away)
    c_htype = candidate.get("home_team_type") or detect_team_type(c_home)
    c_atype = candidate.get("away_team_type") or detect_team_type(c_away)
    team_type_match = (p_htype in (None, "unknown") or c_htype in (None, "unknown") or p_htype == c_htype) and (
        p_atype in (None, "unknown") or c_atype in (None, "unknown") or p_atype == c_atype
    )
    checks["team_type_match"] = team_type_match
    checks["team_types"] = {"primary_home": p_htype, "candidate_home": c_htype, "primary_away": p_atype, "candidate_away": c_atype}
    if team_type_match:
        score += 10
    else:
        hard_block = hard_block or "TEAM_TYPE_MISMATCH"

    score = min(score, 100)
    locked = hard_block is None and score >= LOCK_THRESHOLD
    observe_only = hard_block is None and OBSERVE_THRESHOLD <= score < LOCK_THRESHOLD
    block_reason = hard_block
    if block_reason is None and not locked:
        block_reason = "IDENTITY_SCORE_BELOW_LOCK_THRESHOLD"

    return IdentityCandidateResult(
        source=source,
        source_match_id=source_mid or None,
        identity_score=score,
        locked=locked,
        observe_only=observe_only,
        block_reason=block_reason,
        checks=checks,
    )


def attach_candidate_or_block(primary_identity: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of primary_identity with candidate merged into source_match_map or blocked_sources."""
    identity = json.loads(json.dumps(primary_identity, ensure_ascii=False))
    result = evaluate_cross_source_candidate(identity, candidate)
    result_dict = asdict(result)
    if result.locked:
        identity.setdefault("source_match_map", {})[result.source] = result_dict
    else:
        identity.setdefault("blocked_sources", []).append(result_dict)
        identity["identity_locked"] = False if result.block_reason and result.identity_score < LOCK_THRESHOLD else identity.get("identity_locked", False)
    if result.observe_only:
        identity.setdefault("ambiguous_candidates", []).append(result_dict)
    return identity
