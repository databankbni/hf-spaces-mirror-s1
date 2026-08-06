
from __future__ import annotations

"""Open-Meteo weather adapter for Phase 2.

No API key is required for the default public forecast endpoint. This adapter
uses a conservative stadium/city registry and never fabricates stadium-level
precision when only city-level coordinates are available.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import math
import requests

from .match_identity_resolver import normalize_text, parse_datetime

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def _load_registry(path: str | Path | None = None) -> dict[str, Any]:
    if path is None:
        path = Path(__file__).resolve().parent.parent / "config" / "stadium_geo_registry.json"
    path = Path(path)
    if not path.exists():
        return {"version": "stadium_geo_registry_v1", "matches": {}, "teams": {}, "cities": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _geo_from_registry(primary_identity: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any] | None:
    canonical = primary_identity.get("canonical_match_key")
    if canonical and canonical in (registry.get("matches") or {}):
        return registry["matches"][canonical]
    mid = primary_identity.get("primary_match_id")
    if mid and f"titan007:{mid}" in (registry.get("matches") or {}):
        return registry["matches"][f"titan007:{mid}"]
    home = normalize_text(primary_identity.get("home_team"))
    teams = registry.get("teams") or {}
    for key, geo in teams.items():
        names = [key, geo.get("team"), geo.get("canonical_name"), *(geo.get("aliases") or [])]
        if home and home in {normalize_text(x) for x in names if x}:
            return geo
    return None


def _nearest_hour_index(times: list[str], kickoff: datetime | None) -> int | None:
    if not times or not kickoff:
        return None
    best_i = None
    best_diff = math.inf
    for i, t in enumerate(times):
        dt = parse_datetime(t)
        if not dt:
            continue
        diff = abs((dt.astimezone(timezone.utc) - kickoff.astimezone(timezone.utc)).total_seconds())
        if diff < best_diff:
            best_diff = diff
            best_i = i
    return best_i


def _risk_from_weather(w: dict[str, Any]) -> dict[str, Any]:
    precip = float(w.get("precipitation") or 0)
    wind = float(w.get("wind_speed_10m") or 0)
    gust = float(w.get("wind_gusts_10m") or 0)
    risk_flags = []
    ou_weather_risk = "neutral"
    if precip >= 2.5:
        risk_flags.append("moderate_or_heavy_precipitation")
        ou_weather_risk = "under_risk"
    if wind >= 28 or gust >= 40:
        risk_flags.append("strong_wind")
        ou_weather_risk = "under_risk"
    if precip == 0 and wind < 12:
        ou_weather_risk = "neutral"
    return {"ou_weather_risk": ou_weather_risk, "risk_flags": risk_flags}


def attach_weather_compact(primary_identity: dict[str, Any], registry_path: str | None = None) -> dict[str, Any]:
    registry = _load_registry(registry_path)
    geo = _geo_from_registry(primary_identity, registry)
    if not geo:
        return {
            "enabled": True,
            "source": "open-meteo",
            "status": "geo_missing",
            "weather_available": False,
            "geo_confidence": None,
            "decision_impact": "none",
        }
    lat = geo.get("latitude")
    lon = geo.get("longitude")
    if lat is None or lon is None:
        return {
            "enabled": True,
            "source": "open-meteo",
            "status": "geo_invalid",
            "weather_available": False,
            "decision_impact": "none",
        }
    kickoff = parse_datetime(primary_identity.get("kickoff_utc"))
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,precipitation,wind_speed_10m,wind_gusts_10m,weather_code,cloud_cover",
        "timezone": "UTC",
        "forecast_days": 3,
    }
    try:
        r = requests.get(OPEN_METEO_URL, params=params, timeout=20)
        if r.status_code >= 400:
            return {"enabled": True, "source": "open-meteo", "status": "http_error", "http_status": r.status_code, "weather_available": False, "decision_impact": "risk_flag_only"}
        data = r.json()
    except Exception as exc:
        return {"enabled": True, "source": "open-meteo", "status": "error", "error": str(exc)[-300:], "weather_available": False, "decision_impact": "risk_flag_only"}
    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    idx = _nearest_hour_index(times, kickoff)
    if idx is None:
        return {"enabled": True, "source": "open-meteo", "status": "kickoff_hour_not_found", "weather_available": False, "decision_impact": "risk_flag_only"}
    def val(key: str):
        arr = hourly.get(key) or []
        return arr[idx] if idx < len(arr) else None
    weather = {
        "time_utc": times[idx],
        "temperature_2m": val("temperature_2m"),
        "precipitation": val("precipitation"),
        "wind_speed_10m": val("wind_speed_10m"),
        "wind_gusts_10m": val("wind_gusts_10m"),
        "weather_code": val("weather_code"),
        "cloud_cover": val("cloud_cover"),
    }
    risk = _risk_from_weather(weather)
    return {
        "enabled": True,
        "source": "open-meteo",
        "status": "ok",
        "weather_available": True,
        "geo": {
            "stadium": geo.get("stadium"),
            "city": geo.get("city"),
            "country": geo.get("country"),
            "latitude": lat,
            "longitude": lon,
            "geo_confidence": geo.get("confidence") or "city_level",
        },
        "kickoff_weather": weather,
        **risk,
        "raw_returned": False,
        "decision_impact": "risk_flag_only",
    }
