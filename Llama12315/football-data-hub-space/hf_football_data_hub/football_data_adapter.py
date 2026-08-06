
from __future__ import annotations

"""football-data.org structured adapter for Phase 2.

This adapter is intentionally compact and conservative. It never returns raw API
payloads in the match packet. It attaches standings/fixture metadata only when a
source candidate can be mapped to the primary Titan007 identity or when it is
kept as observe-only evidence.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
import os
import requests

from .match_identity_resolver import evaluate_cross_source_candidate, normalize_text

BASE_URL = "https://api.football-data.org/v4"


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _window(primary_identity: dict[str, Any], fallback_day: str | None = None) -> tuple[str, str]:
    kickoff = _parse_dt(primary_identity.get("kickoff_utc"))
    if kickoff is None:
        if fallback_day:
            return fallback_day, fallback_day
        now = datetime.now(timezone.utc)
        return now.date().isoformat(), now.date().isoformat()
    start = (kickoff - timedelta(days=1)).date().isoformat()
    end = (kickoff + timedelta(days=1)).date().isoformat()
    return start, end


def _headers(token: str) -> dict[str, str]:
    return {"X-Auth-Token": token, "User-Agent": "Hermes-HF-Data-Hub/phase2"}


def _request_json(path: str, token: str, params: dict[str, Any] | None = None, timeout: int = 25) -> dict[str, Any]:
    r = requests.get(BASE_URL + path, headers=_headers(token), params=params or {}, timeout=timeout)
    if r.status_code == 403:
        return {"_error": "FOOTBALL_DATA_FORBIDDEN_OR_PLAN_LIMIT", "_status": r.status_code}
    if r.status_code == 429:
        return {"_error": "FOOTBALL_DATA_RATE_LIMIT", "_status": r.status_code}
    if r.status_code >= 400:
        return {"_error": "FOOTBALL_DATA_HTTP_ERROR", "_status": r.status_code, "_detail": r.text[:300]}
    try:
        return r.json()
    except Exception:
        return {"_error": "FOOTBALL_DATA_INVALID_JSON", "_status": r.status_code}


def _candidate_from_match(match: dict[str, Any]) -> dict[str, Any]:
    comp = match.get("competition") or {}
    home = match.get("homeTeam") or {}
    away = match.get("awayTeam") or {}
    return {
        "source": "football-data.org",
        "source_match_id": str(match.get("id") or ""),
        "league": comp.get("name") or comp.get("code"),
        "competition": comp.get("name") or comp.get("code"),
        "home_team": home.get("name") or home.get("shortName") or home.get("tla"),
        "away_team": away.get("name") or away.get("shortName") or away.get("tla"),
        "kickoff_utc": match.get("utcDate"),
        "status": match.get("status"),
    }


def _find_best_match(primary_identity: dict[str, Any], matches: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]]]:
    scored = []
    for m in matches:
        cand = _candidate_from_match(m)
        result = evaluate_cross_source_candidate(primary_identity, cand)
        scored.append((result.identity_score, cand, m, result))
    scored.sort(key=lambda x: x[0], reverse=True)
    ambiguous = []
    if len(scored) >= 2 and scored[0][0] - scored[1][0] < 10:
        ambiguous = [
            {"source_match_id": x[1].get("source_match_id"), "identity_score": x[0], "home": x[1].get("home_team"), "away": x[1].get("away_team")}
            for x in scored[:3]
        ]
    if not scored:
        return None, None, ambiguous
    top_score, cand, raw, result = scored[0]
    compact_result = {
        "source": result.source,
        "source_match_id": result.source_match_id,
        "identity_score": result.identity_score,
        "locked": result.locked,
        "observe_only": result.observe_only,
        "block_reason": result.block_reason,
        "checks": result.checks,
    }
    if result.locked and not ambiguous:
        return cand, raw, ambiguous
    return None, raw, ambiguous or [{"source_match_id": cand.get("source_match_id"), "identity_score": top_score, "block_reason": result.block_reason}]


def _standing_for_team(table: list[dict[str, Any]], team_name: str | None) -> dict[str, Any]:
    if not table or not team_name:
        return {}
    want = normalize_text(team_name)
    for row in table:
        team = row.get("team") or {}
        names = [team.get("name"), team.get("shortName"), team.get("tla")]
        if want in {normalize_text(x) for x in names if x}:
            return {
                "position": row.get("position"),
                "played_games": row.get("playedGames"),
                "points": row.get("points"),
                "won": row.get("won"),
                "draw": row.get("draw"),
                "lost": row.get("lost"),
                "goals_for": row.get("goalsFor"),
                "goals_against": row.get("goalsAgainst"),
                "goal_difference": row.get("goalDifference"),
            }
    return {}


def attach_football_data_compact(primary_identity: dict[str, Any], day: str | None = None, token: str | None = None) -> dict[str, Any]:
    token = token or os.getenv("FOOTBALL_DATA_API_TOKEN")
    if not token:
        return {
            "enabled": False,
            "source": "football-data.org",
            "status": "missing_token",
            "fixtures_standings_available": False,
            "decision_impact": "none",
        }

    date_from, date_to = _window(primary_identity, day)
    matches_resp = _request_json("/matches", token, params={"dateFrom": date_from, "dateTo": date_to})
    if matches_resp.get("_error"):
        return {
            "enabled": True,
            "source": "football-data.org",
            "status": "error",
            "error": matches_resp.get("_error"),
            "http_status": matches_resp.get("_status"),
            "fixtures_standings_available": False,
            "decision_impact": "risk_flag_only",
        }

    matches = matches_resp.get("matches") or []
    candidate, raw_match, ambiguous = _find_best_match(primary_identity, matches)
    if not candidate:
        return {
            "enabled": True,
            "source": "football-data.org",
            "status": "identity_not_locked",
            "fixtures_searched": len(matches),
            "ambiguous_candidates": ambiguous,
            "fixtures_standings_available": False,
            "decision_impact": "confidence_down",
        }

    comp = (raw_match or {}).get("competition") or {}
    season = (raw_match or {}).get("season") or {}
    home = (raw_match or {}).get("homeTeam") or {}
    away = (raw_match or {}).get("awayTeam") or {}
    standing_home = {}
    standing_away = {}
    standings_status = "not_requested"
    if comp.get("code"):
        standings_resp = _request_json(f"/competitions/{comp.get('code')}/standings", token, params={})
        if standings_resp.get("_error"):
            standings_status = standings_resp.get("_error")
        else:
            standings_status = "ok"
            table = []
            for standing in standings_resp.get("standings") or []:
                if standing.get("type") == "TOTAL":
                    table = standing.get("table") or []
                    break
            standing_home = _standing_for_team(table, home.get("name") or candidate.get("home_team"))
            standing_away = _standing_for_team(table, away.get("name") or candidate.get("away_team"))

    points_gap = None
    if standing_home.get("points") is not None and standing_away.get("points") is not None:
        try:
            points_gap = int(standing_home["points"]) - int(standing_away["points"])
        except Exception:
            points_gap = None

    return {
        "enabled": True,
        "source": "football-data.org",
        "status": "ok",
        "source_match_id": candidate.get("source_match_id"),
        "identity_score": 100,
        "identity_locked": True,
        "competition": {
            "id": comp.get("id"),
            "name": comp.get("name"),
            "code": comp.get("code"),
            "type": comp.get("type"),
        },
        "season": {
            "id": season.get("id"),
            "start_date": season.get("startDate"),
            "end_date": season.get("endDate"),
            "current_matchday": season.get("currentMatchday"),
        },
        "fixture": {
            "utc_date": (raw_match or {}).get("utcDate"),
            "status": (raw_match or {}).get("status"),
            "matchday": (raw_match or {}).get("matchday"),
            "stage": (raw_match or {}).get("stage"),
            "group": (raw_match or {}).get("group"),
            "home_team": home.get("name"),
            "away_team": away.get("name"),
        },
        "standings_status": standings_status,
        "home_standing": standing_home,
        "away_standing": standing_away,
        "points_gap_home_minus_away": points_gap,
        "fixtures_standings_available": bool(candidate),
        "raw_returned": False,
        "decision_impact": "risk_flag_only",
    }
