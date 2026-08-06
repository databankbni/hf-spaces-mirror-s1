#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_titan007_odds.py v2 — Titan007 盘口零浏览器取数器（修复版）

v2 修复项 (2026-07-02):
  ① OU 端点增加重试(3次指数退避) + 单独超时，与 AH 解耦
  ② 数据时效检查：解析最新行时间戳，距当前>6h 标记 stale
  ③ plate_history 逐行提取：盘口轨迹以 API raw 为唯一权威
  ④ 错误隔离：AH 失败不阻塞 OU，反之亦然
  ⑤ 输出新增字段：stale_warning / plate_history / data_timestamp

用法:
  python3 fetch_titan007_odds.py <match_id> [--raw] [--company 3,24]
"""

import sys, re, json, subprocess, time, argparse, os
from datetime import datetime, timedelta

BASE = "https://vip.titan007.com/changeDetail"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

COMPANY_NAME = {
    "3": "皇冠Crown", "8": "Interwetten", "12": "易胜博", "14": "威廉希尔",
    "17": "立博", "24": "Pinnacle平博", "31": "Bet365", "35": "金宝博",
}

# ── fetch with retry ──────────────────────────────────────────

def _fetch_one(url: str, referer: str, timeout: int = 25) -> str:
    """单次 fetch：curl → urllib 回退。"""
    try:
        out = subprocess.run(
            ["curl", "-s", "--compressed", "--max-time", str(timeout),
             "-H", "User-Agent: " + UA,
             "-H", "Referer: " + referer,
             "-H", "Accept-Language: zh-CN,zh;q=0.9",
             url],
            capture_output=True, timeout=timeout + 5,
        )
        raw = out.stdout
        if raw:
            return raw.decode("gb2312", "replace")
    except Exception:
        pass
    try:
        import urllib.request as u, ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = u.Request(url, headers={"User-Agent": UA, "Referer": referer})
        return u.urlopen(req, timeout=timeout, context=ctx).read().decode("gb2312", "replace")
    except Exception as e:
        return "__ERR__" + str(e)


def fetch_with_retry(url: str, referer: str, max_retries: int = 3) -> str:
    """带指数退避的 fetch。"""
    last_err = ""
    for attempt in range(max_retries):
        result = _fetch_one(url, referer)
        if not result.startswith("__ERR__"):
            return result
        last_err = result[7:]
        if attempt < max_retries - 1:
            wait = (2 ** attempt) + 0.5
            time.sleep(wait)
    return "__ERR__" + last_err


# ── parsing ───────────────────────────────────────────────────

def parse_rows(html: str):
    """从 changeDetail 表格抽出干净行（list[list[str]]，7列）。"""
    if html.startswith("__ERR__"):
        return None, html[7:]
    rows = re.findall(r"<TR[^>]*>(.*?)</TR>", html, re.S | re.I)
    clean = []
    for r in rows:
        cells = [re.sub(r"<[^>]+>", "", c).replace("&nbsp;", " ").strip()
                 for c in re.findall(r"<TD[^>]*>(.*?)</TD>", r, re.S | re.I)]
        if len(cells) >= 7:
            clean.append(cells[:7])
    body = [c for c in clean if c[0] not in ("时间", "時間")]
    return body, None


def classify(rows: list):
    """按状态列(idx6)分早/即/滚。表格倒序(最新在上)。"""
    zao = [r for r in rows if r[6] in ("早",)]
    ji  = [r for r in rows if r[6] in ("即",)]
    gun = [r for r in rows if r[6] in ("滚", "滾")]
    opening = (zao[-1] if zao else (ji[-1] if ji else (rows[-1] if rows else None)))
    closing = (ji[0] if ji else None)
    latest_inplay = (gun[0] if gun else None)
    kicked_off = bool(gun)
    return opening, closing, latest_inplay, kicked_off


def row_to_obj(row, market):
    if not row:
        return None
    if market == "AH":
        return {"主水": row[2], "盘口": row[3], "客水": row[4], "时间": row[5], "状态": row[6]}
    return {"大球水": row[2], "盘口": row[3], "小球水": row[4], "时间": row[5], "状态": row[6]}


# ── freshness check ───────────────────────────────────────────

def _parse_row_timestamp(time_str: str) -> datetime | None:
    """解析 Titan007 行时间 '6-30 17:29' → datetime。跨年保护。"""
    try:
        parts = time_str.strip().split()
        if len(parts) >= 2:
            mm, dd = parts[0].split("-", 1)
            hh, mm2 = parts[1].split(":", 1)
            now = datetime.now()
            candidate = datetime(now.year, int(mm), int(dd), int(hh), int(mm2))
            # 跨年保护
            if candidate - now > timedelta(days=30):
                candidate = datetime(now.year - 1, int(mm), int(dd), int(hh), int(mm2))
            elif now - candidate > timedelta(days=330):
                candidate = datetime(now.year + 1, int(mm), int(dd), int(hh), int(mm2))
            return candidate
    except (ValueError, IndexError):
        pass
    return None


def check_freshness(rows: list, hours: int = 6) -> str:
    """检查最新数据行的时间是否过期。"""
    if not rows:
        return "无数据行"
    # 找最新行（status=即的第一行，因为 rows 已倒序）
    ji_rows = [r for r in rows if r[6] in ("即",)]
    latest_row = ji_rows[0] if ji_rows else rows[0]
    ts = _parse_row_timestamp(latest_row[5])
    if ts is None:
        return "时间解析失败"
    delta = (datetime.now() - ts).total_seconds() / 3600
    if delta > hours:
        return f"STALE: 最新行时间={ts.strftime('%m-%d %H:%M')}，距今{delta:.0f}h > {hours}h阈值"
    return f"ok ({delta:.1f}h)"


# ── plate history extraction ─────────────────────────────────

def extract_plate_history(rows: list) -> list[str]:
    """从 raw 行逐行提取盘口轨迹（时间序，去重保序）。"""
    plates = []
    for r in reversed(rows):  # 表格倒序 → 反转成时间序
        if len(r) > 3 and r[3].strip():
            plates.append(r[3].strip())
    # 去重保序
    seen = set()
    unique = []
    for p in plates:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


# ── market builder ────────────────────────────────────────────

def build_market(match_id: str, cid: str, market: str, raw: bool = False) -> dict:
    """获取一场比赛的 AH/OU 数据。"""
    ep = "handicap" if market == "AH" else "overunder"
    referer = ("https://vip.titan007.com/AsianOdds_n.aspx?id=" + match_id
               if market == "AH" else
               "https://vip.titan007.com/OverDown_n.aspx?id=" + match_id)
    url = "%s/%s.aspx?id=%s&companyID=%s&l=0" % (BASE, ep, match_id, cid)

    html = fetch_with_retry(url, referer)
    if html.startswith("__ERR__"):
        return {"error": "fetch failed: " + html[7:][:120]}

    rows, err = parse_rows(html)
    if err is not None:
        return {"error": "parse failed: " + err[:120]}
    if not rows:
        return {"error": "no rows parsed (页面结构或被WAF拦"}

    opening, closing, inplay, kicked = classify(rows)
    obj = {
        "kicked_off": kicked,
        "初盘opening": row_to_obj(opening, market),
        "赛前终盘closing": row_to_obj(closing, market),
    }
    if kicked:
        obj["最新滚球inplay_弃用"] = row_to_obj(inplay, market)

    # 数据时效
    freshness = check_freshness(rows)
    obj["data_freshness"] = freshness
    obj["stale_warning"] = freshness.startswith("STALE") if isinstance(freshness, str) else True
    # 提取最新时间戳
    try:
        latest_ts = None
        ji_rows = [r for r in rows if r[6] in ("即",)]
        latest_row = ji_rows[0] if ji_rows else (rows[0] if rows else None)
        if latest_row:
            latest_ts = _parse_row_timestamp(latest_row[5])
        obj["data_timestamp"] = latest_ts.strftime("%Y-%m-%d %H:%M:%S") if latest_ts else None
    except Exception:
        obj["data_timestamp"] = None

    # Raw 模式：附带全部历史行 + 盘口轨迹 + 结构化输出
    if raw:
        obj["历史全行"] = rows
        obj["plate_history"] = extract_plate_history(rows)
        
        # plate_history_detail: 每个 plate 的最后赛前有效水位
        detail = []
        seen_plates = set()
        # 按时间倒序遍历（最新在前）
        for idx, r in enumerate(rows):
            if len(r) < 7:
                continue
            plate = r[3].strip()
            if not plate or plate in seen_plates:
                continue
            phase = r[6]
            # 只取赛前行（早+即），跳过滚球
            if phase in ("早", "即"):
                seen_plates.add(plate)
                detail.append({
                    "plate": plate,
                    "home_water": r[2],
                    "away_water": r[4],
                    "time": r[5],
                    "phase": phase,
                    "is_closing_for_plate": True,
                    "selected_as": "opening" if phase == "早" else "closing",
                    "row_time_rank": idx + 1,
                    "excluded_inplay_rows_count": len([x for x in rows if x[6] in ("滚", "滾")]),
                    "water_source": "changeDetail",
                    "data_quality": "ok" if phase == "即" else "stale_plate",
                })
        # 反转回时间序
        detail.reverse()
        obj["plate_history_detail"] = detail
        
        # raw_rows: 结构化行输出
        ROW_SCHEMA = ["序号", "比分", "主水/大球水", "盘口", "客水/小球水", "变化时间", "状态"]
        obj["row_schema"] = ROW_SCHEMA
        obj["raw_rows"] = [
            {ROW_SCHEMA[i]: row[i] if i < len(row) else "" for i in range(len(ROW_SCHEMA))}
            for row in rows
        ]
    
    # 赛前终盘 / 滚球污染校验
    ji_rows = [r for r in rows if r[6] in ("即",)]
    gun_rows = [r for r in rows if r[6] in ("滚", "滾")]
    obj["closing_source"] = "pre_match" if ji_rows else ("inplay_only" if gun_rows else "unknown")
    obj["inplay_pollution_risk"] = len(gun_rows) > 0
    obj["used_pre_match_closing"] = len(ji_rows) > 0
    obj["inplay_rows_excluded"] = len(gun_rows)
    obj["closing_selected_from_phase"] = "即" if ji_rows else ("滚" if gun_rows else "早")
    # 最后一条赛前行的时间
    if ji_rows:
        last_ji = ji_rows[0]
        ts = _parse_row_timestamp(last_ji[5])
        obj["last_pre_kickoff_time"] = ts.strftime("%Y-%m-%d %H:%M:%S") if ts else last_ji[5]
    else:
        obj["last_pre_kickoff_time"] = None

    return obj


# ── main ──────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Titan007 盘口零浏览器取数器 v2")
    ap.add_argument("match_id")
    ap.add_argument("--company", default="3", help="公司ID,逗号分隔(默认3=皇冠)")
    ap.add_argument("--raw", action="store_true", help="附带全部历史行+盘口轨迹")
    ap.add_argument("--compact", action="store_true", help="紧凑模式：只输出分析必需字段, raw写入缓存文件")
    args = ap.parse_args()

    result = {
        "match_id": args.match_id,
        "数据来源": "Titan007 changeDetail端点(零浏览器)·v2",
        "companies": {},
    }
    any_kicked = False
    fetch_errors = []

    for cid in [c.strip() for c in args.company.split(",") if c.strip()]:
        name = COMPANY_NAME.get(cid, "company" + cid)
        # When --compact, still fetch full raw data (for disk save) but only output compact
        fetch_raw_mode = args.raw or args.compact
        ah = build_market(args.match_id, cid, "AH", fetch_raw_mode)
        ou = build_market(args.match_id, cid, "OU", fetch_raw_mode)

        # 错误隔离：单个端点失败不丢整场比赛
        ah_ok = "error" not in ah
        ou_ok = "error" not in ou
        if not ah_ok:
            fetch_errors.append(f"{name}/AH: {ah['error']}")
        if not ou_ok:
            fetch_errors.append(f"{name}/OU: {ou['error']}")

        any_kicked = any_kicked or ah.get("kicked_off") or ou.get("kicked_off")
        result["companies"][name] = {
            "companyID": cid,
            "AH让球盘": ah,
            "OU大小球盘": ou,
            "both_ok": ah_ok and ou_ok,
        }

    result["比赛已开球"] = any_kicked
    result["盘口口径提示"] = (
        "已开球→分析只用[初盘opening]+[赛前终盘closing]，丢弃滚球inplay"
        if any_kicked else
        "未开球→[赛前终盘closing]=当前实时赛前盘，可直接用"
    )
    if fetch_errors:
        result["fetch_errors"] = fetch_errors

    # --compact mode: strip raw_rows, write cache
    if args.compact:
        cache_dir = os.path.expanduser("~/.hermes/profiles/football/workspace/raw_odds")
        os.makedirs(cache_dir, exist_ok=True)
        cache_path = os.path.join(cache_dir, f"{args.match_id}.json")
        # Write full data to cache
        with open(cache_path, "w", encoding="utf-8") as cf:
            json.dump(result, cf, ensure_ascii=False, indent=2)
        # Build compact output (matches user-requested schema)
        compact = {
            "match_id": args.match_id,
            "source": "titan007_compact",
            "data_quality": {
                "ok": len(fetch_errors) == 0,
                "missing_fields": [],
                "retry_count": 0,
                "raw_saved_path": cache_path,
            },
            "比赛已开球": any_kicked,
        }
        crown = result.get("companies", {}).get("皇冠Crown", {})
        pinnacle = result.get("companies", {}).get("Pinnacle平博", {})
        
        def make_company_compact(cdata):
            if not cdata:
                return {"ah": {}, "ou": {}}
            ah = cdata.get("AH让球盘", {})
            ou = cdata.get("OU大小球盘", {})
            ah_open = ah.get("初盘opening", {}) or {}
            ah_close = ah.get("赛前终盘closing", {}) or {}
            ou_open = ou.get("初盘opening", {}) or {}
            ou_close = ou.get("赛前终盘closing", {}) or {}
            
            # line delta
            ah_plate_map = {
                "平手": 0, "平手/半球": 0.25, "平/半": 0.25,
                "半球": 0.5, "半": 0.5, "半球/一球": 0.75, "半/一": 0.75,
                "一球": 1.0, "一球/球半": 1.25, "一/球半": 1.25,
                "球半": 1.5, "球半/两球": 1.75, "球半/两": 1.75,
                "两球": 2.0, "两": 2.0,
            }
            ah_open_p = ah_plate_map.get(ah_open.get("盘口", ""), None)
            ah_close_p = ah_plate_map.get(ah_close.get("盘口", ""), None)
            ah_delta = None
            if ah_open_p is not None and ah_close_p is not None:
                ah_delta = f"{ah_close_p - ah_open_p:+.2f}"
            
            return {
                "ah": {
                    "open_line": ah_open.get("盘口", ""),
                    "open_home_water": ah_open.get("主水", ""),
                    "open_away_water": ah_open.get("客水", ""),
                    "current_line": ah_close.get("盘口", ""),
                    "current_home_water": ah_close.get("主水", ""),
                    "current_away_water": ah_close.get("客水", ""),
                    "line_delta": ah_delta,
                    "plate_history": ah.get("plate_history", []),
                    "stale": ah.get("stale_warning", False),
                },
                "ou": {
                    "open_line": ou_open.get("盘口", ""),
                    "open_over_water": ou_open.get("大球水", ""),
                    "open_under_water": ou_open.get("小球水", ""),
                    "current_line": ou_close.get("盘口", ""),
                    "current_over_water": ou_close.get("大球水", ""),
                    "current_under_water": ou_close.get("小球水", ""),
                    "line_delta": None,
                    "plate_history": ou.get("plate_history", []),
                    "stale": ou.get("stale_warning", False),
                }
            }
        
        compact["crown"] = make_company_compact(crown)
        compact["pinnacle"] = make_company_compact(pinnacle)
        
        # Cross-book signals
        cross_book = []
        crown_ah_line = crown.get("AH让球盘", {}).get("赛前终盘closing", {}).get("盘口", "") if crown else ""
        pin_ah_line = pinnacle.get("AH让球盘", {}).get("赛前终盘closing", {}).get("盘口", "") if pinnacle else ""
        if crown_ah_line and pin_ah_line and crown_ah_line != pin_ah_line:
            cross_book.append(f"AH分歧 Crown={crown_ah_line} Pinnacle={pin_ah_line}")
        compact["cross_book_signals"] = cross_book
        
        if fetch_errors:
            compact["data_quality"]["missing_fields"] = fetch_errors
        
        print(json.dumps(compact, ensure_ascii=False, indent=2))
        return

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
