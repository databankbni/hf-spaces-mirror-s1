#!/usr/bin/env python3
"""Capture Titan007 pre-match fundamentals as a hashed, fail-closed evidence artifact.

The collector is intentionally conservative: source retrieval or parsing failure is
an explicit diagnostic result, never a model-supplied substitute for fundamentals.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from html import unescape
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import titan007_relay_transport as relay_transport

ROOT = Path(os.getenv('HF_COLLECTOR_ROOT') or Path(__file__).resolve().parents[1])
SNAPSHOTS = ROOT / "fundamental_snapshots"
ATTEMPTS = 3
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://vip.titan007.com/",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(value)
    temp.replace(path)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def fetch(url: str) -> tuple[bytes, int]:
    """Direct egress first, read-only relay fallback (see titan007_relay_transport)."""
    return relay_transport.fetch(url, HEADERS, timeout=25, attempts=ATTEMPTS)


def decode(raw: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace")


def strip_html(value: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", value)).split())


def section(text: str, marker: str, limit: int = 24000) -> str:
    index = text.find(marker)
    return "" if index < 0 else text[index:index + limit]


def count_rows(block: str) -> int:
    return len(re.findall(r"<tr\b", block, flags=re.I))


def infer_competition_stage(league: str, briefing: str, page_title: str = "") -> str:
    text = f"{page_title} {briefing}"
    competition = f"{league} {page_title}"
    uefa_qualifying = any(token in competition for token in ("欧冠", "歐冠", "欧联", "歐聯", "欧协联", "歐協聯"))
    if uefa_qualifying and any(token in text for token in ("首回合", "次回合", "第一回合", "第二回合", "首輪", "次輪")):
        return "QUALIFYING"
    if any(token in text for token in ("淘汰赛", "淘汰賽", "半决赛", "半決賽", "准决赛", "準決賽", "决赛", "決賽", "十六强", "十六強", "八强", "八強", "四强", "四強")):
        return "KNOCKOUT"
    if any(token in text for token in ("小组赛", "小組賽", "分组赛", "分組賽")):
        return "GROUP"
    return "UNKNOWN"


def lineup_injury_verification(source_text: str, injury_section_present: bool, source_no_data: bool = False) -> dict:
    explicit_no_absence = any(token in source_text for token in (
        "无伤停", "無傷停", "没有伤停", "沒有傷停", "阵容完整", "陣容完整",
        "均无伤停", "均無傷停", "无缺阵", "無缺陣", "无缺陣", "無缺阵",
        "双方确认无缺阵", "雙方確認無缺陣",
    ))
    verified = bool(injury_section_present and explicit_no_absence)
    status = "EXPLICIT_NO_ABSENCE" if verified else "SOURCE_NO_DATA" if source_no_data else "UNAVAILABLE"
    return {
        "verified": verified,
        "status": status,
        "source_class": "match_bound_briefing_and_injury_section" if verified else "none",
    }


def parse_summary(text: str) -> dict:
    title = strip_html(re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S).group(1)) if re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S) else ""
    standings = section(text, "integralDiv")
    recent = section(text, "近6")
    lineup_section = section(text, "陣容情況") or section(text, "阵容情况")
    injuries = section(text, "缺陣原因") or section(text, "缺阵原因") or section(text, "傷停") or section(text, "伤停")
    standings_text = strip_html(standings)
    plain = strip_html(text)
    briefing = ""
    briefing_match = re.search(r"賽前簡報\s*(.{0,2400}?)(?:本賽季數據統計比較|主隊戰績統計)", plain, re.S)
    if briefing_match:
        briefing = " ".join(briefing_match.group(1).split())
    competition_stage = infer_competition_stage("", briefing, title)
    stage_verified = competition_stage in {"QUALIFYING", "KNOCKOUT", "GROUP"}
    stage_source_class = "match_bound_briefing" if stage_verified else "unverified_prose"
    recent_form_summary = briefing[:600] if briefing else None
    page_has_standings = all(marker in text for marker in ("賽", "積分", "排名")) and "近6" in text
    lineup_plain = strip_html(lineup_section or injuries)
    previous_lineup_available = any(token in lineup_plain for token in ("上一場陣容", "上一场阵容")) and any(token in lineup_plain for token in ("首發", "首发"))
    source_no_data = bool(injuries) and any(token in strip_html(injuries) for token in ("暫無數據", "暂无数据"))
    lineup = lineup_injury_verification(f"{briefing} {lineup_plain}", bool(injuries), source_no_data)
    return {
        "page_title": title,
        "standings_section_present": bool(standings),
        "standings_fields_present": page_has_standings,
        "recent_form_marker_present": bool(recent),
        "recent_form_rows": count_rows(recent),
        "injury_section_present": bool(injuries),
        "lineup_section_present": bool(lineup_section),
        "previous_lineup_available": previous_lineup_available,
        "absence_table_present": bool(injuries),
        "absence_data_status": lineup["status"],
        "lineup_injury_verification": lineup,
        "competition_stage": competition_stage,
        "knockout_confirmed": competition_stage == "KNOCKOUT",
        "competition_stage_verified": stage_verified,
        "competition_stage_source_class": stage_source_class,
        "briefing_present": bool(briefing),
        "briefing_sha256": hashlib.sha256(briefing.encode()).hexdigest() if briefing else None,
        "briefing_excerpt": recent_form_summary,
    }


def _parse_utc(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _recent_verified_artifact(match_id: str, *, now_utc: datetime, max_age_seconds: int) -> dict | None:
    """Find the newest prior fundamentals artifact whose referenced raw page still hashes.

    This fallback is only for a transient transport failure after a live packet's
    separate market/identity refresh. It never manufactures basic facts and it
    refuses expired, malformed, cross-match, or hash-mismatched evidence.
    """
    candidates = []
    for path in (SNAPSHOTS / str(match_id)).glob("*.json"):
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
            captured = _parse_utc(artifact.get("captured_at"))
            raw_path = Path(str(artifact.get("raw_path", "")))
            expected = str(artifact.get("raw_sha256", ""))
            if not (artifact.get("ok") and artifact.get("directional_eligible") and artifact.get("match_id") == str(match_id) and captured and raw_path.is_file() and len(expected) == 64):
                continue
            age_seconds = round((now_utc - captured).total_seconds())
            if age_seconds < 0 or age_seconds > max_age_seconds:
                continue
            if hashlib.sha256(raw_path.read_bytes()).hexdigest() != expected:
                continue
            candidates.append((captured, age_seconds, artifact, path))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    if not candidates:
        return None
    captured, age_seconds, artifact, path = max(candidates, key=lambda item: item[0])
    return {**artifact, "fallback_used": True, "fallback_reason": "LIVE_FETCH_FAILED_RECENT_HASHED_ARTIFACT", "evidence_age_seconds": age_seconds, "fallback_artifact_path": str(path), "live_fetch_error": None}


def capture(match_id: str, *, max_fallback_age_seconds: int = 600) -> dict:
    captured_at = now()
    captured_dt = _parse_utc(captured_at) or datetime.now(timezone.utc)
    url = f"https://zq.titan007.com/analysis/{match_id}.htm"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    try:
        raw, attempts = fetch(url)
    except Exception as exc:
        fallback = _recent_verified_artifact(str(match_id), now_utc=captured_dt, max_age_seconds=max_fallback_age_seconds)
        if fallback:
            fallback["captured_at"] = captured_at
            fallback["source_url"] = url
            fallback["attempts"] = ATTEMPTS
            fallback["live_fetch_error"] = f"{type(exc).__name__}:{str(exc)[:180]}"
            return fallback
        return {
            "ok": False,
            "code": "FUNDAMENTALS_SOURCE_UNAVAILABLE",
            "match_id": str(match_id),
            "captured_at": captured_at,
            "source_url": url,
            "attempts": ATTEMPTS,
            "error": f"{type(exc).__name__}:{str(exc)[:180]}",
            "fallback_used": False,
            "directional_eligible": False,
        }
    digest = hashlib.sha256(raw).hexdigest()
    raw_path = SNAPSHOTS / str(match_id) / "raw" / f"{stamp}_{digest[:12]}.html"
    atomic_bytes(raw_path, raw)
    summary = parse_summary(decode(raw))
    required = summary["standings_section_present"] and summary["standings_fields_present"] and summary["recent_form_marker_present"] and summary["recent_form_rows"] >= 8
    artifact = {
        "ok": required,
        "code": "FUNDAMENTALS_READY" if required else "FUNDAMENTALS_INCOMPLETE",
        "match_id": str(match_id),
        "captured_at": captured_at,
        "source_url": url,
        "attempts": attempts,
        "raw_sha256": digest,
        "raw_path": str(raw_path),
        "summary": summary,
        "directional_eligible": required,
    }
    target = SNAPSHOTS / str(match_id) / f"{stamp}_{digest[:12]}.json"
    atomic_json(target, artifact)
    artifact["artifact_path"] = str(target)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", required=True)
    args = parser.parse_args()
    result = capture(args.match_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 20


if __name__ == "__main__":
    sys.exit(main())
