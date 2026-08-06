from __future__ import annotations

"""Titan007 JingCai correct-score odds optional enrichment.

Discovered source: https://cp.titan007.com/buy/jingcai.aspx?typeID=102&oddstype=2

Important boundary:
- This is the JingCai official score market displayed by Titan007.
- It is NOT Crow/Crown bookmaker correct-score odds.
- It is optional, non-blocking, and intended only for AH/OU depth/path checks.
"""

from datetime import datetime, timezone
from typing import Any
import hashlib
import html
import json
import re

import requests

SOURCE_URL = "https://cp.titan007.com/buy/jingcai.aspx?typeID=102&oddstype=2"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<.*?>", " ", text, flags=re.S))).strip()


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def fetch_page(timeout: int = 30) -> str:
    response = requests.get(SOURCE_URL, timeout=timeout, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


def parse_page(src: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    row_starts = list(re.finditer(r"<tr id=\"row_(\d+)\"", src, re.I))
    for idx, match in enumerate(row_starts):
        start = match.start()
        end = row_starts[idx + 1].start() if idx + 1 < len(row_starts) else len(src)
        block = src[start:end]
        jc_id = match.group(1)
        mid_m = re.search(r"AsianOdds_n\.aspx\?id=(\d+)", block)
        if not mid_m:
            continue
        titan_id = mid_m.group(1)
        home_m = re.search(r'id="HomeTeam_' + re.escape(titan_id) + r'"[^>]*>(.*?)</a>', block, re.S)
        away_m = re.search(r'id="GuestTeam_' + re.escape(titan_id) + r'"[^>]*>(.*?)</a>', block, re.S)
        kickoff_m = re.search(r'<td[^>]*(?:title="开赛时间：([^"]+)"|style="color:#008;display:none;"[^>]*>([^<]+))', block, re.S)
        league_m = re.search(r"<a href='//info\.titan007\.com/cn/CupMatch/\d+\.html'[^>]*>(.*?)</a>", block, re.S)
        odds: dict[str, float] = {}
        for cell in re.finditer(r"<td[^>]*id=\"cell_" + re.escape(jc_id) + r"_\d+\"[^>]*>([\s\S]*?)</td>", block, re.I):
            body = cell.group(1)
            score_m = re.search(r"<b>(.*?)</b>", body, re.S | re.I)
            price_m = re.search(r"<span[^>]*>(.*?)</span>", body, re.S | re.I)
            if not score_m or not price_m:
                continue
            score = _clean(score_m.group(1)).replace("其它", "其他")
            price_text = _clean(price_m.group(1))
            try:
                price = float(price_text)
            except ValueError:
                continue
            odds[score] = price
        rows.append({
            "titan_match_id": titan_id,
            "jingcai_match_id": jc_id,
            "league": _clean(league_m.group(1)) if league_m else None,
            "kickoff": _clean(kickoff_m.group(1) or kickoff_m.group(2)) if kickoff_m else None,
            "home": _clean(home_m.group(1)) if home_m else None,
            "away": _clean(away_m.group(1)) if away_m else None,
            "correct_score_odds": odds,
            "correct_score_count": len(odds),
        })
    return rows


def aggregate_paths(odds: dict[str, float]) -> dict[str, Any]:
    inv_sum = sum((1.0 / v) for v in odds.values() if isinstance(v, (int, float)) and v > 0)
    probs = {k: (1.0 / v) / inv_sum for k, v in odds.items() if isinstance(v, (int, float)) and v > 0} if inv_sum else {}
    agg: dict[str, Any] = {
        "visible_outcomes": len(probs),
        "overround_visible": inv_sum,
        "p_home_win_by_2plus_visible_norm": 0.0,
        "p_home_win_by_1_visible_norm": 0.0,
        "p_draw_or_away_visible_norm": 0.0,
        "p_total_le_2_visible_norm": 0.0,
        "p_total_eq_3_visible_norm": 0.0,
        "p_total_ge_4_visible_norm": 0.0,
        "other_buckets_present": [k for k in probs if "其他" in k],
        "top_scores": sorted(probs.items(), key=lambda kv: kv[1], reverse=True)[:8],
        "note": "Normalized over listed score buckets only; grouped '其他' buckets are not decomposed into exact scores.",
    }
    for score, p in probs.items():
        m = re.match(r"^(\d+):(\d+)$", score)
        if not m:
            continue
        h, a = int(m.group(1)), int(m.group(2))
        gd = h - a
        total = h + a
        if gd >= 2:
            agg["p_home_win_by_2plus_visible_norm"] += p
        elif gd == 1:
            agg["p_home_win_by_1_visible_norm"] += p
        else:
            agg["p_draw_or_away_visible_norm"] += p
        if total <= 2:
            agg["p_total_le_2_visible_norm"] += p
        elif total == 3:
            agg["p_total_eq_3_visible_norm"] += p
        else:
            agg["p_total_ge_4_visible_norm"] += p
    return agg


def collect_correct_score() -> dict[str, Any]:
    captured_at = datetime.now(timezone.utc).isoformat()
    src = fetch_page()
    matches = parse_page(src)
    payload = {
        "artifact_type": "titan007_jingcai_correct_score",
        "schema_version": 1,
        "source": "titan007_jingcai_score_market",
        "source_url": SOURCE_URL,
        "bookmaker": "JingCai_official_score_market_not_Crow",
        "crow_or_crown": False,
        "decision_impact": "optional_ah_ou_depth_check_only",
        "blocking": False,
        "captured_at": captured_at,
        "coverage_match_count": len(matches),
        "match_ids": sorted(row["titan_match_id"] for row in matches),
        "matches": matches,
    }
    payload["canonical_sha256"] = _sha(matches)
    return payload


def match_view(payload: dict[str, Any], match_id: str) -> dict[str, Any]:
    row = next((item for item in payload.get("matches", []) if str(item.get("titan_match_id")) == str(match_id)), None)
    base = {
        "source": payload.get("source"),
        "source_url": payload.get("source_url"),
        "bookmaker": payload.get("bookmaker"),
        "crow_or_crown": payload.get("crow_or_crown", False),
        "decision_impact": payload.get("decision_impact"),
        "blocking": False,
        "captured_at": payload.get("captured_at"),
        "coverage_match_count": payload.get("coverage_match_count"),
    }
    if not row:
        return {**base, "ok": False, "code": "CORRECT_SCORE_UNAVAILABLE_FOR_MATCH", "match_id": str(match_id), "reason": "match_id_not_in_titan007_jingcai_score_page"}
    return {**base, "ok": True, "code": "CORRECT_SCORE_READY", "match_id": str(match_id), "match": row, "path_aggregation": aggregate_paths(row.get("correct_score_odds", {}))}
