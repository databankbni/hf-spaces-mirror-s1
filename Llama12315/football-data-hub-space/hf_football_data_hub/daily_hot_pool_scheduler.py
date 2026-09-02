"""Free-Space daily Crow full-roster runner driven by UptimeRobot health pings.

The Space is woken every five minutes by the existing external HTTP monitor.  A
ping in the 10:40--10:55 Asia/Shanghai window starts one background collection;
there is no HF Job, local Hermes process, model call, or prediction path.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

import requests

from .dataset_store import store, rel_hot_pool, rel_status, rel_correct_score, rel_crow_full_pool, rel_crow_full_merged_pool
from .titan007_correct_score import collect_correct_score

CROW_ROSTER_URLS = (
    "https://live.titan007.com/vbsxml/sbOddsData.js?r=007",
    "https://livestatic.titan007.com/vbsxml/sbOddsData.js?r=007",
)
CROW_SDATA_ID = re.compile(r"sData\[(\d+)\]\s*=")

TZ = ZoneInfo("Asia/Shanghai")
# Multi-slot schedule refresh (2026-07-18): four data-only 热门池 refreshes per day
# so the schedule pool (league/team/kickoff only) stays current for evening and
# overnight fixtures, not just the morning. Each window is 15 minutes wide and the
# UptimeRobot /health ping (every 5 min) launches at most one collection per slot.
# This refreshes SCHEDULE identity only; it never fetches odds, runs analysis, or
# writes predictions (data_only_guard stays all-false).
WINDOW_STARTS = (10 * 60 + 30, 12 * 60, 18 * 60)
WINDOW_LEN = 15
URLS = (
    "https://livestatic.titan007.com/vbsxml/bfdata_ut.js",
    "https://bf.titan007.com/vbsxml/bfdata_ut.js",
)
ASSIGNMENT = re.compile(r'(?P<name>[AB])\[(?P<index>\d+)\]="(?P<value>(?:[^"\\]|\\.)*)"\.split\(\'\^\'\);')
_lock = threading.Lock()
_running = False
_last_started_slot: str | None = None
_last_result: dict = {"status": "never_run"}


def _current_slot(at: datetime) -> str | None:
    """Return a per-day slot key (YYYY-MM-DD#<slot_start_minute>) if `at` falls in
    any refresh window, else None. Slot identity prevents more than one collection
    per window per day while still allowing all four daily windows."""
    minute = at.hour * 60 + at.minute
    for start in WINDOW_STARTS:
        if start <= minute <= start + WINDOW_LEN:
            return f"{at.date().isoformat()}#{start}"
    return None


def should_launch(at: datetime, last_started_slot: str | None) -> bool:
    at = at.astimezone(TZ)
    slot = _current_slot(at)
    return slot is not None and last_started_slot != slot


def _value(row: list[str] | None, index: int) -> str:
    return str(row[index]).strip() if row and len(row) > index and row[index] is not None else ""


def _kickoff(row: list[str]) -> datetime | None:
    """Use Titan007's full row timestamp; never substitute the capture date."""
    try:
        year, month_zero, day, hour, minute, second = map(int, _value(row, 12).split(","))
        return datetime(year, month_zero + 1, day, hour, minute, second, tzinfo=TZ)
    except ValueError:
        return None


def _schedule() -> dict[str, list[list[str] | None]]:
    errors: list[str] = []
    for url in URLS:
        try:
            response = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            data: dict[str, dict[int, list[str]]] = {"A": {}, "B": {}}
            for match in ASSIGNMENT.finditer(response.text):
                raw = match.group("value")
                decoded = re.sub(r"\\\\(x[0-9A-Fa-f]{2}|u[0-9A-Fa-f]{4}|[\\\"'])", lambda item: bytes(item.group(0), "ascii").decode("unicode_escape"), raw)
                data[match.group("name")][int(match.group("index"))] = decoded.split("^")
            if data["A"] and data["B"]:
                return {name: [rows.get(i) for i in range(max(rows) + 1)] for name, rows in data.items()}
            errors.append(f"{url}:arrays_missing")
        except Exception as exc:
            errors.append(f"{url}:{type(exc).__name__}")
    raise RuntimeError("schedule_fetch_failed:" + ";".join(errors))


_CROW_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://live.titan007.com/index2in1.aspx?id=3",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def _crow_ids() -> set[str]:
    """Crow roster is a filter, never the schedule source.

    Empty/blocked sbOddsData.js must return an empty set so collect() can
    still publish bfdata_ut.js identity rows. Raising here historically
    aborted the whole daily pool (2026-08-18 slot #630/#720).
    """
    errors = []
    for url in CROW_ROSTER_URLS:
        try:
            response = requests.get(url, timeout=30, headers=_CROW_HEADERS)
            response.raise_for_status()
            ids = set(CROW_SDATA_ID.findall(response.text or ""))
            if ids:
                return ids
            errors.append(f"{url}:empty:{len(response.content)}")
        except Exception as exc:
            errors.append(f"{url}:{type(exc).__name__}")
    return set()


def _rows(source: dict[str, list[list[str] | None]], at: datetime, crow_ids: set[str] | None = None) -> list[dict]:
    crow_ids = crow_ids if crow_ids is not None else None
    output: dict[str, dict] = {}
    for row in source["A"]:
        if not row:
            continue
        match_id, league, clock = _value(row, 0), _value(row, 2), _value(row, 11)
        home, away = _value(row, 5), _value(row, 8)
        if (crow_ids is not None and match_id not in crow_ids) or not league or not home or not away or not re.fullmatch(r"\d{1,2}:\d{2}", clock):
            continue
        kickoff = _kickoff(row)
        if kickoff is None:
            continue
        output[match_id] = {"match_id": match_id, "league": league, "home": re.sub(r"<[^>]+>", "", home), "away": re.sub(r"<[^>]+>", "", away), "kickoff_local": kickoff.isoformat(), "status": _value(row, 13), "has_ah": True, "has_ou": True, "hot": _value(row, 62) == "1"}
    return sorted(output.values(), key=lambda row: (row["kickoff_local"], row["match_id"]))


def _sha(rows: list[dict]) -> str:
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def collect(now_fn: Callable[[], datetime] = lambda: datetime.now(TZ), sleep_fn: Callable[[int], None] = time.sleep) -> dict:
    captured_at = now_fn().astimezone(TZ)
    try:
        roster_ids = _crow_ids()
    except Exception:
        roster_ids = set()
    schedule = _schedule()
    if roster_ids:
        rows = _rows(schedule, captured_at, roster_ids)
        roster = {
            "verified": True, "url": CROW_ROSTER_URLS[0], "size": len(roster_ids),
            "vip_host_used": False, "status": "crow_roster_ok",
        }
    else:
        # Crow filter unavailable: keep the Titan schedule identity pool so
        # /ready and /hot-matches still serve today's card. Host JC admission
        # remains the production universe; this is not a Crow-priced claim.
        rows = _rows(schedule, captured_at, None)
        roster = {
            "verified": False, "url": CROW_ROSTER_URLS[0], "size": 0,
            "vip_host_used": False, "status": "crow_roster_empty_schedule_fallback",
        }
    previous = store.load_json(rel_crow_full_merged_pool(captured_at.date().isoformat())) or {}
    previous_rows = {row["match_id"]: row for row in previous.get("matches", []) if row.get("match_id")}
    previous_rows.update({row["match_id"]: row for row in rows})
    rows = sorted(previous_rows.values(), key=lambda row: (row["kickoff_local"], row["match_id"]))
    started = [row for row in rows if row["kickoff_local"] <= captured_at.isoformat()]
    future = [row for row in rows if row["kickoff_local"] > captured_at.isoformat()]
    slot = _current_slot(captured_at) or captured_at.strftime("%H%M")
    coverage = "ALL_MATCHES_CROW_PRICED" if roster["verified"] else "SCHEDULE_IDENTITY_FALLBACK"
    pool = {
        "artifact_type": "crow_full_pool", "schema_version": 4,
        "pool_date": captured_at.date().isoformat(), "captured_at": captured_at.isoformat(),
        "capture_slot": slot,
        "source_filter": "titan007_live:Crow:赛事:所有比赛:全部:全选" if roster["verified"] else "titan007_live:bfdata_ut:schedule_identity",
        "coverage_mode": coverage, "collector": "hf_free_space_uptimerobot_trigger",
        "includes_started": True, "cloud_only": True, "accepted": bool(rows),
        "freshness_status": "CURRENT_DATE_CONFIRMED", "match_count": len(rows),
        "started_or_finished_count": len(started), "future_count": len(future),
        "match_ids": sorted(row["match_id"] for row in rows), "matches": rows,
        "roster": roster,
        "canonical_sha256": _sha(rows),
        "data_only_guard": {"model_call_performed": False, "analysis_performed": False, "final_pick_written": False, "bankroll_written": False},
    }
    if pool["accepted"]:
        store.save_json(rel_crow_full_pool(pool["pool_date"], slot), pool)
        store.save_json(rel_crow_full_merged_pool(pool["pool_date"]), pool)
        store.save_json(rel_status(pool["pool_date"]), {
            "artifact_type": "source_status", "pool_date": pool["pool_date"],
            "accepted": True, "freshness_status": pool["freshness_status"],
            "collector": pool["collector"], "capture_slot": slot,
            "canonical_sha256": pool["canonical_sha256"], "captured_at": pool["captured_at"],
        })
    return pool


def trigger_from_health_ping() -> dict:
    global _running, _last_started_slot, _last_result
    at = datetime.now(TZ)
    with _lock:
        if not should_launch(at, _last_started_slot) or _running:
            return {"scheduled_window": should_launch(at, _last_started_slot), "running": _running, "last_result": _last_result}
        _running, _last_started_slot = True, _current_slot(at.astimezone(TZ))
    def worker() -> None:
        global _running, _last_result
        try:
            _last_result = {"status": "completed", "pool": collect()}
        except Exception as exc:
            _last_result = {"status": "failed", "error": f"{type(exc).__name__}:{str(exc)[:300]}"}
        finally:
            with _lock:
                _running = False
    threading.Thread(target=worker, name="daily-hot-pool", daemon=True).start()
    return {"scheduled_window": True, "running": True, "launched": True, "slot": _last_started_slot}


def status() -> dict:
    with _lock:
        return {"running": _running, "last_started_slot": _last_started_slot, "last_result": _last_result, "windows": "10:30 / 12:00 / 18:00 (±15m) Asia/Shanghai", "trigger": "UptimeRobot GET /health"}
