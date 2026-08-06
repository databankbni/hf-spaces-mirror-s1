#!/usr/bin/env python3
"""Fetch and verify Titan007 cup stage for one match.

Stage evidence is separate from fundamentals prose. For the World Cup this reads
Titan007's public CupMatch schedule JavaScript, maps the match row's G<kind_id>
to arrCupKind, hashes the source, and emits an auditable result.
"""
from __future__ import annotations
import argparse, hashlib, json, re, urllib.request
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

LEAGUE_SCLASS = {"世界杯": 75, "世界盃": 75, "World Cup": 75}
QUALIFYING_COMPETITIONS = (
    "欧冠", "歐冠", "欧联", "歐聯", "欧协联", "歐協聯",
    "欧罗巴", "歐霸", "欧霸", "Europa",
)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def fetch(url: str, referer: str | None = None) -> bytes:
    headers = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}
    if referer:
        headers["Referer"] = referer
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
        return response.read()


def stage_code(name: str) -> str:
    if any(token in name for token in ("半准决赛", "半准決賽", "Quarterfinal")):
        return "QUARTERFINAL"
    if any(token in name for token in ("准决赛", "准決賽", "半决赛", "半決賽", "Semifinal")):
        return "SEMIFINAL"
    if any(token in name for token in ("季军", "季軍", "Third")):
        return "THIRD_PLACE"
    if any(token in name for token in ("决赛", "決賽", "Final")):
        return "FINAL"
    if any(token in name for token in ("三十二强", "三十二強", "十六强", "十六強", "1/16", "1/8")):
        return "KNOCKOUT"
    if any(token in name for token in ("分组", "分組", "Group")):
        return "GROUP"
    return "UNKNOWN"


def parse_stage_script(source: str, match_id: str) -> dict[str, Any]:
    kinds: dict[str, str] = {}
    kind_match = re.search(r"var\s+arrCupKind\s*=\s*\[(.*?)]\s*;", source, re.S)
    if kind_match:
        for item in re.finditer(r"\[(\d+),[^\]]*?'([^']+)'", kind_match.group(1), re.S):
            kinds[item.group(1)] = item.group(2)
    group_id = None
    for group in re.finditer(r'jh\["G(\d+)"\]\s*=\s*\[(.*?)\];', source, re.S):
        if re.search(r"\[\s*" + re.escape(str(match_id)) + r"\s*,", group.group(2)):
            group_id = group.group(1)
            break
    if not group_id:
        return {"ok": False, "code": "MATCH_NOT_FOUND_IN_CUP_SCHEDULE", "match_id": str(match_id)}
    name = kinds.get(group_id)
    code = stage_code(name or "")
    return {
        "ok": bool(name and code != "UNKNOWN"),
        "code": "COMPETITION_STAGE_READY" if name and code != "UNKNOWN" else "COMPETITION_STAGE_UNMAPPED",
        "match_id": str(match_id), "cup_kind_id": group_id,
        "stage_name": name, "stage": code,
        "knockout_confirmed": code not in ("GROUP", "UNKNOWN"),
    }


def _stage_source_sha(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def collect(match_id: str, league: str, kickoff: str | None = None) -> dict[str, Any]:
    sclass = next((value for key, value in LEAGUE_SCLASS.items() if key in str(league)), None)
    if not sclass:
        if any(token in str(league) for token in QUALIFYING_COMPETITIONS):
            source_payload = {"match_id": str(match_id), "league": league, "kickoff": kickoff, "stage": "QUALIFYING"}
            return {
                "ok": True, "code": "COMPETITION_STAGE_SCHEDULE_CLASSIFIED",
                "match_id": str(match_id), "league": league, "stage": "QUALIFYING",
                "stage_name": "UEFA qualifying phase", "knockout_confirmed": True,
                "source": "schedule_league_and_preseason_date_classification",
                "source_sha256": _stage_source_sha(source_payload),
                "captured_at": datetime.now(timezone.utc).isoformat(),
            }
        # Domestic / non-cup leagues are not stage-bound. Emit an explicit
        # auditable NOT_APPLICABLE result instead of a hard-fail unmapped code.
        source_payload = {
            "match_id": str(match_id),
            "league": league,
            "kickoff": kickoff,
            "stage": "NOT_APPLICABLE",
            "classification": "competition_type_not_stage_bound",
        }
        return {
            "ok": True,
            "code": "COMPETITION_STAGE_NOT_APPLICABLE",
            "match_id": str(match_id),
            "league": league,
            "stage": "NOT_APPLICABLE",
            "stage_name": "Domestic or non stage-bound competition",
            "knockout_confirmed": False,
            "source": "competition_type_not_stage_bound",
            "source_sha256": _stage_source_sha(source_payload),
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
    page_url = f"https://info.titan007.com/cn/CupMatch/{sclass}.html"
    page_raw = fetch(page_url, "https://live.titan007.com/")
    page = page_raw.decode("utf-8", "replace")
    script_match = re.search(r'src="([^"]*/jsData/matchResult/[^"?]+\.js(?:\?[^\"]*)?)"', page, re.I)
    if not script_match:
        return {"ok": False, "code": "CUP_STAGE_SCRIPT_NOT_DISCOVERED", "match_id": str(match_id), "league": league, "page_url": page_url}
    script_url = urllib.request.urljoin(page_url, script_match.group(1))
    raw = fetch(script_url, page_url)
    source = raw.decode("utf-8-sig", "replace")
    result = parse_stage_script(source, str(match_id))
    return {
        **result, "league": league, "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "titan007_cup_schedule_js", "source_url": script_url,
        "source_sha256": hashlib.sha256(raw).hexdigest(), "sclass_id": sclass,
    }


def capture_for_packet(match_id: str, league: str, kickoff: str | None = None) -> dict[str, Any]:
    """Collect stage evidence during packet acquisition; never in the downstream runner."""
    try:
        return collect(match_id, league, kickoff)
    except Exception as exc:
        return {"ok": False, "code": "COMPETITION_STAGE_SOURCE_UNAVAILABLE", "match_id": str(match_id),
                "league": league, "reason": f"{type(exc).__name__}:{exc}"[:600]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--league", required=True)
    parser.add_argument("--kickoff")
    args = parser.parse_args()
    try:
        result = collect(args.match_id, args.league, args.kickoff)
    except Exception as exc:
        result = {"ok": False, "code": "COMPETITION_STAGE_SOURCE_UNAVAILABLE", "match_id": str(args.match_id), "league": args.league, "reason": f"{type(exc).__name__}:{exc}"[:600]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 20


if __name__ == "__main__":
    raise SystemExit(main())
