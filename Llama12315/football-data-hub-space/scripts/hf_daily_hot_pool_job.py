#!/usr/bin/env python3
"""Cloud-only daily Titan007 Crow full-roster collector for Hugging Face Jobs.

Runs independently of Hermes. It retrieves Titan007's public static schedule,
fetches the Crow company roster, keeps every Crow-priced fixture including started fixtures, writes
only compact JSON to the HF Dataset, and then proves the Space can read it.

/// script
requires-python = ">=3.11"
dependencies = ["huggingface_hub>=0.23", "requests>=2.31"]
///
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
try:
    from huggingface_hub import HfApi, hf_hub_download
except ModuleNotFoundError:
    HfApi = None
    hf_hub_download = None

TZ = ZoneInfo("Asia/Shanghai")
DATASET_REPO = os.environ.get("HF_DATASET_REPO", "Llama12315/football-data-hub")
SPACE_URL = os.environ.get("HF_SPACE_URL", "https://llama12315-football-data-hub-space.hf.space").rstrip("/")
TOKEN = os.environ.get("HF_TOKEN")
REQUEST_TIMEOUT = int(os.environ.get("HOT_POOL_REQUEST_TIMEOUT_SECONDS", "30"))
SCHEDULE_URLS = (
    "https://livestatic.titan007.com/vbsxml/bfdata_ut.js",
    "https://bf.titan007.com/vbsxml/bfdata_ut.js",
)
ARRAY_ASSIGNMENT = re.compile(r'(?P<name>[AB])\[(?P<index>\d+)\]="(?P<value>(?:[^"\\]|\\.)*)"\.split\(\'\^\'\);')
CROW_ROSTER_URLS = ("https://live.titan007.com/vbsxml/sbOddsData.js?r=007", "https://livestatic.titan007.com/vbsxml/sbOddsData.js?r=007")
CROW_SDATA_ID = re.compile(r"sData\[(\d+)\]\s*=")


def now() -> datetime:
    return datetime.now(TZ)


def row_value(row: list[str] | None, index: int) -> str:
    return str(row[index]).strip() if row and len(row) > index and row[index] is not None else ""


def parse_schedule(script: str) -> dict[str, list[list[str] | None]]:
    rows: dict[str, dict[int, list[str]]] = {"A": {}, "B": {}}
    for match in ARRAY_ASSIGNMENT.finditer(script):
        raw = match.group("value")
        value = re.sub(
            r"\\\\(x[0-9A-Fa-f]{2}|u[0-9A-Fa-f]{4}|[\\\"'])",
            lambda item: bytes(item.group(0), "ascii").decode("unicode_escape"), raw,
        )
        rows[match.group("name")][int(match.group("index"))] = value.split("^")
    if not rows["A"] or not rows["B"]:
        raise RuntimeError("static_schedule_arrays_missing")
    return {name: [items.get(index) for index in range(max(items) + 1)] for name, items in rows.items()}


def fetch_schedule() -> dict[str, list[list[str] | None]]:
    errors: list[str] = []
    for url in SCHEDULE_URLS:
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            return parse_schedule(response.text)
        except Exception as exc:
            errors.append(f"{url}:{type(exc).__name__}")
    raise RuntimeError("schedule_fetch_failed:" + ";".join(errors))


def kickoff(row: list[str], day: str, clock: str) -> str:
    raw = row_value(row, 12)
    try:
        year, month_zero, date_, hour, minute, second = map(int, raw.split(","))
        return datetime(year, month_zero + 1, date_, hour, minute, second, tzinfo=TZ).isoformat()
    except (TypeError, ValueError):
        hour, minute = map(int, clock.split(":"))
        return f"{day}T{hour:02d}:{minute:02d}:00+08:00"


def fetch_crow_roster() -> tuple[set[str], str]:
    errors = []
    for url in CROW_ROSTER_URLS:
        try:
            command = ["curl", "--http1.1", "--compressed", "--connect-timeout", "10", "--max-time", str(REQUEST_TIMEOUT), "-fsSL", "-A", "Mozilla/5.0", "-e", "https://live.titan007.com/index2in1.aspx?id=3", url]
            completed = subprocess.run(command, capture_output=True, timeout=REQUEST_TIMEOUT + 10, check=False)
            if completed.returncode != 0:
                raise RuntimeError(f"curl_{completed.returncode}")
            body = completed.stdout.decode("utf-8", errors="replace")
            ids = set(CROW_SDATA_ID.findall(body))
            if ids:
                return ids, url
            errors.append(f"{url}:empty:{len(body)}")
        except Exception as exc:
            errors.append(f"{url}:{type(exc).__name__}")
    raise RuntimeError("crow_roster_fetch_failed:" + ";".join(errors))


def crow_rows(source: dict[str, list[list[str] | None]], captured: datetime,
              crow_ids: set[str]) -> list[dict]:
    output: list[dict] = []
    for row in source["A"]:
        if not row:
            continue
        match_id, league = row_value(row, 0), row_value(row, 2)
        home, away, clock = row_value(row, 5), row_value(row, 8), row_value(row, 11)
        if match_id not in crow_ids or not league or not home or not away:
            continue
        start = datetime.fromisoformat(kickoff(row, captured.date().isoformat(), clock))
        output.append({
            "match_id": match_id, "league": league,
            "home": re.sub(r"<[^>]+>", "", home), "away": re.sub(r"<[^>]+>", "", away),
            "kickoff_local": start.isoformat(), "status": row_value(row, 13),
            "has_ah": True, "has_ou": True,
            "hot": row_value(row, 62) == "1",
        })
    return sorted({item["match_id"]: item for item in output}.values(), key=lambda item: (item["kickoff_local"], item["match_id"]))


def capture() -> tuple[datetime, list[dict], str, int]:
    captured = now()
    crow_ids, roster_url = fetch_crow_roster()
    return captured, crow_rows(fetch_schedule(), captured, crow_ids), roster_url, len(crow_ids)


def canonical(items: list[dict]) -> str:
    return hashlib.sha256(json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_pool(*args) -> dict:
    """Build a full Crow pool; accepts the legacy two-capture test shape."""
    if len(args) == 1 and isinstance(args[0], list):
        captures = args[0]
    elif len(args) == 4:
        first_at, first, second_at, second = args
        captures = [(first_at, first, "", 0), (second_at, second, "", 0)]
    else:
        raise TypeError("build_pool expects captures or two capture pairs")
    latest = captures[-1]
    legacy_mode = len(args) == 4
    by_id = {}
    for _, rows, _, _ in captures:
        by_id.update({item["match_id"]: item for item in rows})
    if legacy_mode:
        first_ids = {item["match_id"] for item in captures[0][1]}
        second_ids = {item["match_id"] for item in captures[-1][1]}
        union = first_ids | second_ids
        overlap = len(first_ids & second_ids) / len(union) if union else 0.0
        accepted = bool(second_ids) and overlap >= 0.5
    else:
        overlap, accepted = 1.0, bool(by_id)
    matches = sorted(by_id.values(), key=lambda item: (item["kickoff_local"], item["match_id"]))
    latest_iso = latest[0].isoformat()
    started = [item for item in matches if item["kickoff_local"] <= latest_iso]
    future = [item for item in matches if item["kickoff_local"] > latest_iso]
    return {
        "artifact_type": "crow_full_pool", "schema_version": 4, "pool_date": latest[0].date().isoformat(),
        "captured_at": latest[0].isoformat(), "source_filter": "titan007_live:Crow:赛事:所有比赛:全部:全选",
        "coverage_mode": "ALL_MATCHES_CROW_PRICED", "collector": "hf_scheduled_job", "cloud_only": True,
        "accepted": accepted,
        "freshness_status": ("CURRENT_DATE_CONFIRMED_STABLE" if legacy_mode and accepted else
                             "DEGRADED_UNSTABLE_POOL" if legacy_mode else "CURRENT_DATE_CONFIRMED"),
        "stable": accepted if legacy_mode else True, "overlap_ratio": round(overlap, 4),
        "includes_started": True, "started_or_finished_count": len(started), "future_count": len(future),
        "raw_crow_count": len(matches), "raw_hot_count": len(matches),
        "today_count": len([x for x in matches if x["kickoff_local"][:10] == latest[0].date().isoformat()]),
        "today_hot_count": len([x for x in matches if x["kickoff_local"][:10] == latest[0].date().isoformat()]),
        "upcoming_hot_count": len(future), "match_count": len(matches), "match_ids": sorted(by_id), "matches": matches,
        "captures": [{"captured_at": at.isoformat(), "match_count": len(rows), "sha256": canonical(rows), "roster_url": url, "roster_size": size} for at, rows, url, size in captures],
        "canonical_sha256": canonical(matches),
        "data_only_guard": {"model_call_performed": False, "analysis_performed": False, "final_pick_written": False, "bankroll_written": False},
    }

def upload(api: HfApi, day: str, pool: dict) -> None:
    root = Path("/tmp/hf-hot-pool")
    pool_file, status_file = root / "pool.json", root / "status.json"
    root.mkdir(parents=True, exist_ok=True)
    status = {"artifact_type": "source_status", "pool_date": day, "accepted": pool["accepted"], "freshness_status": pool["freshness_status"], "collector": "hf_scheduled_job", "captured_at": pool["captured_at"], "canonical_sha256": pool["canonical_sha256"]}
    try:
        from hf_football_data_hub.titan007_correct_score import collect_correct_score
        correct_score = collect_correct_score()
        correct_score_file = root / "correct_score.json"
        correct_score_file.write_text(json.dumps(correct_score, ensure_ascii=False, indent=2), encoding="utf-8")
        api.upload_file(path_or_fileobj=str(correct_score_file), path_in_repo=f"data/correct_score/{day}.json", repo_id=DATASET_REPO, repo_type="dataset", token=TOKEN, commit_message=f"correct score {day}")
        status["correct_score"] = {"configured": True, "available_match_count": correct_score.get("coverage_match_count", 0), "match_ids": correct_score.get("match_ids", []), "crow_or_crown": False, "source": correct_score.get("source"), "captured_at": correct_score.get("captured_at"), "canonical_sha256": correct_score.get("canonical_sha256"), "blocking": False}
    except Exception as exc:
        status["correct_score"] = {"configured": True, "available_match_count": 0, "crow_or_crown": False, "source": "titan007_jingcai_score_market", "status": "collect_failed", "error": f"{type(exc).__name__}:{str(exc)[:200]}", "blocking": False}
    pool_file.write_text(json.dumps(pool, ensure_ascii=False, indent=2), encoding="utf-8")
    status_file.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    api.upload_file(path_or_fileobj=str(pool_file), path_in_repo=f"data/crow_full_pool/{day}/merged.json", repo_id=DATASET_REPO, repo_type="dataset", token=TOKEN, commit_message=f"hot pool {day}")
    api.upload_file(path_or_fileobj=str(status_file), path_in_repo=f"data/source_status/{day}.json", repo_id=DATASET_REPO, repo_type="dataset", token=TOKEN, commit_message=f"hot pool status {day}")


def verify(day: str, expected_sha: str) -> dict:
    filename = f"data/crow_full_pool/{day}/merged.json"
    downloaded = hf_hub_download(repo_id=DATASET_REPO, repo_type="dataset", filename=filename, token=TOKEN, force_download=True)
    dataset_pool = json.loads(Path(downloaded).read_text(encoding="utf-8"))
    if dataset_pool.get("canonical_sha256") != expected_sha:
        raise RuntimeError("dataset_readback_sha_mismatch")
    response = requests.get(f"{SPACE_URL}/hot-matches", params={"date_": day}, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    space_pool = response.json()
    if not space_pool.get("ok") or space_pool.get("canonical_sha256") != expected_sha:
        raise RuntimeError("space_readback_mismatch")
    return {"dataset_readback": True, "space_readback": True, "space_match_count": len(space_pool.get("matches", []))}


def main() -> int:
    if not TOKEN:
        raise RuntimeError("HF_TOKEN is required for Dataset write/readback")
    pool = build_pool([capture()])
    if not pool["accepted"]:
        print(json.dumps({"ok": False, "pool": pool}, ensure_ascii=False))
        return 20
    api = HfApi(token=TOKEN)
    upload(api, pool["pool_date"], pool)
    verification = verify(pool["pool_date"], pool["canonical_sha256"])
    print(json.dumps({"ok": True, "pool_date": pool["pool_date"], "match_count": pool["match_count"], "verification": verification}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
