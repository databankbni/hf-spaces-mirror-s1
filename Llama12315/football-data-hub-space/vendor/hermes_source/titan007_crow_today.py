#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""titan007_crow_today.py

Scrape today's football matches from https://live.titan007.com/ and, for each
SCHEDULED match, read ONLY the Crow / 皇冠 (Crow*) Asian-handicap row from the
detail page, emitting a stable structured JSON (schema_version
crow_weak_favorite_scan.v1).

Hard rules:
- Only public, unauthenticated data. No captcha / login / paywall bypass.
- Only Crow Asian handicap. No 欧赔, no 大小球, no other bookmakers.
- Never dump full page HTML. Output structured JSON only.
- Missing fields => null / "unknown". Never fabricate.
- Throttle detail-page visits (default 800-1200ms).
"""
import argparse
import asyncio
import json
import os
import random
import re
import sys
from datetime import datetime, timezone, timedelta

SOURCE_LIST = "https://live.titan007.com/"
DETAIL_TMPL = "https://vip.titan007.com/AsianOdds_n.aspx?id={match_id}&l=0"

# ---- Handicap Chinese -> numeric mapping (absolute magnitude) -------------
HANDICAP_MAP = {
    "平手": 0.0, "平手盘": 0.0,
    "平/半": 0.25, "平手/半球": 0.25,
    "半球": 0.5,
    "半/一": 0.75, "半球/一球": 0.75,
    "一球": 1.0,
    "一/球半": 1.25, "一球/球半": 1.25,
    "球半": 1.5,
    "球半/两": 1.75, "球半/两球": 1.75,
    "两球": 2.0,
    "两/两半": 2.25, "两球/两球半": 2.25,
    "两半": 2.5, "两球半": 2.5,
    "两半/三": 2.75, "两球半/三球": 2.75,
    "三球": 3.0,
    "三球/三球半": 3.25, "三球半": 3.5,
    "三半/四": 3.75, "四球": 4.0,
}


def now_tz(tz_name):
    """Return tz-aware now. Falls back to a fixed offset if zoneinfo missing."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz_name))
    except Exception:
        # Asia/Singapore is UTC+8; default to UTC+8 as a safe regional fallback
        return datetime.now(timezone(timedelta(hours=8)))


def parse_handicap(text):
    """Parse a Chinese/numeric handicap label -> (value_float|None, is_recv_bool).

    is_recv True means the label carried 受/受让 (home is receiving => away is favorite).
    Numeric strings like '0.5' / '-0.5' / '0/0.5' are also tolerated.
    """
    if text is None:
        return None, False
    raw = str(text).strip()
    if not raw:
        return None, False
    is_recv = ("受让" in raw) or ("受" in raw)
    cleaned = raw.replace("受让", "").replace("受", "").replace("让", "").strip()

    # direct Chinese label
    if cleaned in HANDICAP_MAP:
        return HANDICAP_MAP[cleaned], is_recv

    # numeric forms: -0.5 / 0.5 / 0.25 etc.
    m = re.match(r"^-?\d+(\.\d+)?$", cleaned)
    if m:
        val = abs(float(cleaned))
        # leading '-' in Titan numeric usually means home gives handicap; we
        # only return magnitude here, direction handled by is_recv / sign caller
        return val, is_recv

    # split forms like '0/0.5' or '0.5/1'
    m2 = re.match(r"^(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)$", cleaned)
    if m2:
        a, b = float(m2.group(1)), float(m2.group(2))
        return round((a + b) / 2.0, 3), is_recv

    return None, is_recv


def classify_handicap_move(init_v, live_v):
    """升盘 / 稳盘 / 退盘 / unknown based on absolute handicap magnitude."""
    if init_v is None or live_v is None:
        return "unknown"
    if live_v > init_v + 1e-9:
        return "升盘"
    if live_v < init_v - 1e-9:
        return "退盘"
    return "稳盘"


def to_float_odds(s):
    if s is None:
        return None
    try:
        return float(str(s).strip())
    except Exception:
        return None


def classify_water_move(init_odds, live_odds):
    """降水 / 稳水 / 升水 / unknown for the home/upper side water.

    Lower odds = 降水 (money coming in / price shortening),
    higher odds = 升水.
    """
    a = to_float_odds(init_odds)
    b = to_float_odds(live_odds)
    if a is None or b is None:
        return "unknown"
    if b < a - 1e-9:
        return "降水"
    if b > a + 1e-9:
        return "升水"
    return "稳水"


# ---- Match-list scraping ---------------------------------------------------
async def scrape_match_list(page, today_str):
    """Return list of dicts: {match_id, league, kickoff_time, home, away, status}.

    Titan007's live index is a dynamic page. Match rows commonly live in a
    table whose <tr> ids look like 'tr1_<matchid>'. We read text only and never
    return raw HTML. Selectors are best-effort and may need tuning against the
    live DOM (documented in skill.md self-check section).
    """
    matches = []
    # Titan live index rows carry id 'tr1_<matchid>'. Wait for them to render.
    try:
        await page.wait_for_selector("tr[id^='tr1_']", timeout=15000)
    except Exception:
        return matches
    rows = await page.query_selector_all("tr[id^='tr1_']")
    for r in rows:
        try:
            rid = await r.get_attribute("id")
            mid = None
            if rid:
                m = re.search(r"tr1_(\d+)", rid)
                if m:
                    mid = m.group(1)
            if not mid:
                continue

            cells = await r.query_selector_all("td")
            vals = []
            for c in cells:
                t = (await c.inner_text()) or ""
                vals.append(re.sub(r"\s+", " ", t).strip())

            def cell(i):
                return vals[i].strip() if i < len(vals) and vals[i].strip() else None

            # Real Titan layout (11 cells):
            # 0 fav, 1 league, 2 time, 3 status, 4 home, 5 score, 6 away, 7 half, ...
            league = cell(1)
            kickoff = cell(2)
            status_txt = cell(3) or ""
            home = cell(4)
            score = cell(5) or ""
            away = cell(6)

            # Status: scheduled if score is '-'/empty and no live clock; finished
            # if explicit 完/完场/FT; live if a minute clock or in-play marker.
            status = "scheduled"
            joined = f"{status_txt} {score}"
            if any(k in joined for k in ["完", "Finished", "FT", "已完"]):
                status = "finished"
            elif re.search(r"\d{1,3}'", status_txt) or status_txt in ("中", "上", "下", "半") \
                    or re.search(r"\d+\s*-\s*\d+", score):
                status = "live"

            matches.append({
                "match_id": mid,
                "league": league or "unknown",
                "kickoff_time": kickoff or "unknown",
                "home": home or "unknown",
                "away": away or "unknown",
                "status": status,
            })
        except Exception:
            continue
    return matches


async def scrape_crow_row(page, match_id):
    """Visit the Asian-odds detail page and read ONLY the Crow/皇冠/Crow* row.

    Returns a dict matching the crow_asian contract or {status: missing/error}.
    The detail table lists each bookmaker as a row; the company name is in the
    first cell, then initial (init) and live (now) handicap+water columns.
    """
    url = DETAIL_TMPL.format(match_id=match_id)
    result = {
        "match_id": match_id,
        "company": "Crow",
        "initial_home_odds": None, "initial_handicap": None, "initial_away_odds": None,
        "live_home_odds": None, "live_handicap": None, "live_away_odds": None,
        "update_time": None, "raw_row_text": "", "source": url,
        "_status": "missing_crow_asian",
    }
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        result["_status"] = "error"
        result["raw_row_text"] = f"goto_error: {type(e).__name__}"
        return result

    crow_names = ("Crow", "皇冠", "Crow*")
    try:
        rows = await page.query_selector_all("tr")
    except Exception:
        rows = []

    target = None
    for r in rows:
        try:
            txt = (await r.inner_text()) or ""
        except Exception:
            continue
        if any(name in txt for name in crow_names):
            # avoid matching header rows that merely mention the word
            cells = await r.query_selector_all("td")
            if len(cells) >= 4:
                target = r
                break

    if target is None:
        return result

    try:
        raw = (await target.inner_text()) or ""
        result["raw_row_text"] = re.sub(r"\s+", " ", raw).strip()[:400]
        cells = await target.query_selector_all("td")
        vals = []
        for c in cells:
            t = (await c.inner_text()) or ""
            vals.append(re.sub(r"\s+", " ", t).strip())

        # Real Titan AsianOdds_n Crow row (observed, 13 cells):
        #  ['', 'Crow*', '', '1.02','半球/一球','0.80',  init  home/hcap/away
        #                     '1.00','半球/一球','0.89',  live  home/hcap/away
        #                     '1.00','半球/一球','0.89',  (closing/now dup)
        #                     '详 统 主 客 同']
        # Strategy: find company cell, then take the data tokens that follow,
        # dropping empty cells and the trailing action cell. Each odds/handicap
        # triplet is (home_odds, handicap, away_odds).
        ci = next((i for i, v in enumerate(vals)
                   if v and any(n in v for n in crow_names)), 0)
        tail = vals[ci + 1:]
        # keep only meaningful tokens: drop empties and the action/link cell
        tokens = [v for v in tail
                  if v and not re.search(r"[详统主客同走指数]", v)]
        # tokens now look like: [init_home, init_hcap, init_away,
        #                        live_home, live_hcap, live_away, (maybe closing...)]
        def tok(i):
            return tokens[i] if i < len(tokens) and tokens[i] != "" else None

        result["initial_home_odds"] = tok(0)
        result["initial_handicap"] = tok(1)
        result["initial_away_odds"] = tok(2)
        result["live_home_odds"] = tok(3)
        result["live_handicap"] = tok(4)
        result["live_away_odds"] = tok(5)
        # update time: last cell that looks like a time
        for v in reversed(vals):
            if v and re.search(r"\d{1,2}:\d{2}", v):
                result["update_time"] = v
                break
        result["_status"] = "ok"
    except Exception as e:
        result["_status"] = "error"
        if not result["raw_row_text"]:
            result["raw_row_text"] = f"parse_error: {type(e).__name__}"
    return result


# ---- Record assembly + basic-candidate logic -------------------------------
def build_record(match, crow):
    """Assemble one match record + derived fields.

    V3 (2026-06-29) 核心逻辑：以 Crow【初盘】为入池依据，不是即时盘。
      基础候选 (is_candidate_basic=True)：
        1. scheduled
        2. 有 Crow 亚盘
        3. 【初盘】不是平手盘
        4. 能识别【初盘】让球方 (initial_fav_side)
      即时盘只用于后续复核(升盘/稳盘/退盘/水位)，不作入池条件。
      退盘不再剔除——保留初盘异常记录，由后续评分降级/PASS。
    """
    notes = []
    crow_status = crow.pop("_status", "missing_crow_asian")

    init_v, init_recv = parse_handicap(crow.get("initial_handicap"))
    live_v, live_recv = parse_handicap(crow.get("live_handicap"))

    home_move = classify_water_move(
        crow.get("initial_home_odds"), crow.get("live_home_odds"))
    away_move = classify_water_move(
        crow.get("initial_away_odds"), crow.get("live_away_odds"))

    derived = {
        "handicap_move": classify_handicap_move(init_v, live_v),
        "home_side_water_move": home_move,
        "away_side_water_move": away_move,
        "fav_side_water_move": "unknown",
        "initial_handicap_value": init_v,
        "live_handicap_value": live_v,
        "initial_fav_side": None,   # 初盘让球方 (核心)
        "live_fav_side": None,      # 即时让球方 (复核)
        "retreat_risk": False,
        "live_flat_risk": False,    # 即时退到平手
    }

    status = "ok"
    is_candidate_basic = False

    if match["status"] != "scheduled":
        status = "skipped"
        notes.append(f"非未开场 status={match['status']}")
    elif crow_status == "missing_crow_asian":
        status = "missing_crow_asian"
        notes.append("无 Crow/皇冠 亚盘")
    elif crow_status == "error":
        status = "error"
        notes.append("Crow 行解析出错")
    elif init_v is None:
        status = "ok"
        notes.append("Crow 初盘方向无法识别，跳过")
    elif init_v == 0.0:
        status = "ok"
        notes.append("Crow 初盘为平手盘，剔除（本模型只看初盘让球）")
    else:
        # 初盘非平手 → 识别初盘让球方
        status = "ok"
        init_fav = "away" if init_recv else "home"
        derived["initial_fav_side"] = init_fav
        if init_fav == "home":
            derived["fav_side_water_move"] = home_move
        elif init_fav == "away":
            derived["fav_side_water_move"] = away_move
        notes.append(f"Crow 初盘让球方 = {'客队' if init_fav=='away' else '主队'}")

        # 即时让球方 (复核用)
        if live_v is not None and live_v > 0:
            derived["live_fav_side"] = "away" if live_recv else "home"
        elif live_v == 0.0:
            derived["live_flat_risk"] = True
            notes.append("⚠️ 即时盘退到平手（风险极高）")

        if derived["handicap_move"] == "退盘":
            derived["retreat_risk"] = True
            notes.append("⚠️ 初盘→即时退盘（保留初盘异常，后续降级）")

        is_candidate_basic = True
        notes.append("基础候选成立（初盘让球已识别）")

    return {
        "match": {
            "match_id": match["match_id"],
            "league": match["league"],
            "kickoff_time": match["kickoff_time"],
            "home": match["home"],
            "away": match["away"],
            "status": match["status"],
            "source": SOURCE_LIST,
        },
        "crow_asian": crow,
        "derived": derived,
        "status": status,
        "is_candidate_basic": is_candidate_basic,
        "notes": notes,
    }


def build_summary(records):
    s = {
        "total_matches_found": len(records),
        "scheduled_matches": sum(1 for r in records if r["match"]["status"] == "scheduled"),
        "with_crow_asian": sum(1 for r in records if r["status"] == "ok"),
        "missing_crow_asian": sum(1 for r in records if r["status"] == "missing_crow_asian"),
        "basic_candidates": sum(1 for r in records if r["is_candidate_basic"]),
        "skipped": sum(1 for r in records if r["status"] == "skipped"),
        "errors": sum(1 for r in records if r["status"] == "error"),
    }
    return s


async def run(args):
    from playwright.async_api import async_playwright

    tz_now = now_tz(args.timezone)
    today_str = tz_now.strftime("%Y-%m-%d")

    records = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not args.headful)
        ctx = await browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"),
            locale="zh-CN",
        )
        page = await ctx.new_page()
        try:
            await page.goto(SOURCE_LIST, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(4000)  # let dynamic rows render
        except Exception as e:
            print(json.dumps({
                "error": f"list_page_failed: {type(e).__name__}: {e}",
                "hint": "Titan007 live index DOM may have changed; tune scrape_match_list selectors.",
            }, ensure_ascii=False), file=sys.stderr)
            await browser.close()
            return 2

        matches = await scrape_match_list(page, today_str)
        # Only future (scheduled) matches proceed to detail fetch
        scheduled = [m for m in matches if m["status"] == "scheduled"]
        fetch_set = scheduled[: args.limit] if args.limit else scheduled
        fetch_ids = {m["match_id"] for m in fetch_set}

        detail_page = await ctx.new_page()
        for m in matches:
            if m["match_id"] in fetch_ids:
                continue
            # Non-scheduled OR (scheduled but excluded by --limit debug cap):
            # emit a skipped record with empty Crow data; never fabricate odds.
            empty = {
                "match_id": m["match_id"], "company": "Crow",
                "initial_home_odds": None, "initial_handicap": None,
                "initial_away_odds": None, "live_home_odds": None,
                "live_handicap": None, "live_away_odds": None,
                "update_time": None, "raw_row_text": "", "_status": "skipped",
                "source": DETAIL_TMPL.format(match_id=m["match_id"]),
            }
            rec = build_record(m, empty)
            if m["status"] == "scheduled":
                rec["status"] = "skipped"
                rec["notes"].append("debug --limit 跳过，未抓取 Crow 详情")
            records.append(rec)

        for m in fetch_set:
            crow = await scrape_crow_row(detail_page, m["match_id"])
            records.append(build_record(m, crow))
            await asyncio.sleep(random.uniform(args.min_delay, args.max_delay))

        await browser.close()

    out = {
        "schema_version": "crow_weak_favorite_scan.v1",
        "generated_at": tz_now.isoformat(),
        "date": today_str,
        "source": SOURCE_LIST,
        "bookmaker": "Crow",
        "market": "Asian Handicap",
        "matches": records,
        "summary": build_summary(records),
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # stdout: compact summary only (token-safe), never full HTML
    print(json.dumps({
        "ok": True, "out": args.out, "date": today_str,
        "summary": out["summary"],
    }, ensure_ascii=False))
    return 0


def main():
    ap = argparse.ArgumentParser(description="Titan007 Crow Asian-handicap today scanner")
    ap.add_argument("--out", default="data/crow_today.json")
    ap.add_argument("--timezone", default="Asia/Singapore")
    ap.add_argument("--limit", type=int, default=0, help="limit scheduled matches (debug)")
    ap.add_argument("--headful", action="store_true", help="show browser (debug)")
    ap.add_argument("--min-delay", type=float, default=0.8)
    ap.add_argument("--max-delay", type=float, default=1.2)
    args = ap.parse_args()
    try:
        rc = asyncio.run(run(args))
    except KeyboardInterrupt:
        rc = 130
    sys.exit(rc)


if __name__ == "__main__":
    main()
