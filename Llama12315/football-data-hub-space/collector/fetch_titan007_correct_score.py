#!/usr/bin/env python3
"""Fetch Titan007 JingCai correct-score odds when available.

This is an optional enrichment probe. It intentionally does NOT claim Crown/Crow
coverage: the currently discovered Titan007 source is the JingCai score page
(typeID=102), which only covers matches with score-market sales.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from typing import Any

URL = "https://cp.titan007.com/buy/jingcai.aspx?typeID=102&oddstype=2"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<.*?>", " ", text, flags=re.S))).strip()


def fetch_page() -> str:
    req = urllib.request.Request(URL, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse_page(src: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    row_starts = list(re.finditer(r"<tr id=\"row_(\d+)\"", src, re.I))
    for idx, m in enumerate(row_starts):
        start = m.start()
        end = row_starts[idx + 1].start() if idx + 1 < len(row_starts) else len(src)
        block = src[start:end]
        jc_id = m.group(1)
        mid_m = re.search(r"AsianOdds_n\.aspx\?id=(\d+)", block)
        if not mid_m:
            continue
        titan_id = mid_m.group(1)
        home_m = re.search(r'id="HomeTeam_' + re.escape(titan_id) + r'"[^>]*>(.*?)</a>', block, re.S)
        away_m = re.search(r'id="GuestTeam_' + re.escape(titan_id) + r'"[^>]*>(.*?)</a>', block, re.S)
        kickoff_m = re.search(r'<td[^>]*(?:title="开赛时间：([^"]+)"|style="color:#008;display:none;"[^>]*>([^<]+))', block, re.S)
        league_m = re.search(r"<a href='//info\.titan007\.com/cn/CupMatch/\d+\.html'[^>]*>(.*?)</a>", block, re.S)
        odds: dict[str, float] = {}
        # Each cell contains <b>score</b><br><span ...>decimal odds</span>.
        for cell in re.finditer(r"<td[^>]*id=\"cell_" + re.escape(jc_id) + r"_\d+\"[^>]*>([\s\S]*?)</td>", block, re.I):
            body = cell.group(1)
            score_m = re.search(r"<b>(.*?)</b>", body, re.S | re.I)
            price_m = re.search(r"<span[^>]*>(.*?)</span>", body, re.S | re.I)
            if not score_m or not price_m:
                continue
            score = clean(score_m.group(1)).replace("其它", "其他")
            price_text = clean(price_m.group(1))
            try:
                price = float(price_text)
            except ValueError:
                continue
            odds[score] = price
        out.append({
            "titan_match_id": titan_id,
            "jingcai_match_id": jc_id,
            "league": clean(league_m.group(1)) if league_m else None,
            "kickoff": clean(kickoff_m.group(1) or kickoff_m.group(2)) if kickoff_m else None,
            "home": clean(home_m.group(1)) if home_m else None,
            "away": clean(away_m.group(1)) if away_m else None,
            "correct_score_odds": odds,
            "correct_score_count": len(odds),
        })
    return out


def aggregate_paths(odds: dict[str, float]) -> dict[str, Any]:
    # Overround-normalized implied probabilities over the visible 31 outcomes.
    probs: dict[str, float] = {}
    inv_sum = 0.0
    for k, v in odds.items():
        if v > 0:
            inv_sum += 1.0 / v
    if inv_sum > 0:
        probs = {k: (1.0 / v) / inv_sum for k, v in odds.items() if v > 0}
    agg = {
        "visible_outcomes": len(probs),
        "overround_visible": inv_sum,
        "p_home_win_by_2plus_visible_norm": 0.0,
        "p_home_win_by_1_visible_norm": 0.0,
        "p_draw_or_away_visible_norm": 0.0,
        "p_total_le_2_visible_norm": 0.0,
        "p_total_eq_3_visible_norm": 0.0,
        "p_total_ge_4_visible_norm": 0.0,
        "top_scores": sorted(probs.items(), key=lambda kv: kv[1], reverse=True)[:8],
        "note": "Normalized over listed score buckets only; 'other' buckets are grouped and not decomposed.",
    }
    for score, p in probs.items():
        m = re.match(r"^(\d+):(\d+)$", score)
        if not m:
            # other buckets cannot be decomposed safely; keep out of path sums.
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


def fetch_for_packet(match_id: str, identity: dict[str, Any] | None = None) -> dict[str, Any]:
    """Capture optional score evidence during immutable packet acquisition."""
    try:
        src = fetch_page()
        rows = parse_page(src)
        row = next((item for item in rows if str(item["titan_match_id"]) == str(match_id)), None)
    except Exception as exc:
        return {"ok": False, "code": "CORRECT_SCORE_SOURCE_UNAVAILABLE", "match_id": str(match_id),
                "source": "titan007_jingcai_correct_score", "crow_or_crown": False,
                "blocking": False, "reason": type(exc).__name__}
    if not row:
        return {"ok": False, "code": "CORRECT_SCORE_UNAVAILABLE_FOR_MATCH", "match_id": str(match_id),
                "source": "titan007_jingcai_correct_score", "crow_or_crown": False,
                "blocking": False, "reason": "match_id_not_in_titan007_jingcai_score_page"}
    return {"ok": True, "code": "CORRECT_SCORE_READY", "match_id": str(match_id),
            "source": "titan007_jingcai_correct_score", "source_url": URL,
            "crow_or_crown": False, "blocking": False,
            "captured_at": datetime.now(timezone.utc).isoformat(), "match": row,
            "path_aggregation": aggregate_paths(row["correct_score_odds"])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-id")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    src = fetch_page()
    rows = parse_page(src)
    result: dict[str, Any] = {
        "ok": True,
        "source": "titan007_jingcai_correct_score",
        "source_url": URL,
        "bookmaker": "JingCai_official_score_market_not_Crow",
        "crow_or_crown": False,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "coverage_match_count": len(rows),
    }
    if args.list or not args.match_id:
        result["matches"] = [{k: r[k] for k in ("titan_match_id", "jingcai_match_id", "league", "kickoff", "home", "away", "correct_score_count")} for r in rows]
    else:
        row = next((r for r in rows if str(r["titan_match_id"]) == str(args.match_id)), None)
        if not row:
            result.update({"ok": False, "code": "CORRECT_SCORE_UNAVAILABLE_FOR_MATCH", "match_id": str(args.match_id), "reason": "match_id_not_in_titan007_jingcai_score_page"})
        else:
            result.update({"code": "CORRECT_SCORE_READY", "match": row, "path_aggregation": aggregate_paths(row["correct_score_odds"])})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 20


if __name__ == "__main__":
    raise SystemExit(main())
