#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
multi_company_analyzer.py — 多公司盘口即时分析器 v1

输入: fetch_titan007_odds.py v2 的 JSON 输出（stdin）
输出: ADI(AH-OU背离)、SFI(聪明钱领先)、多公司水位比较、信号收敛加分

用法:
  python3 fetch_titan007_odds.py 2998777 --company 3,24 | python3 multi_company_analyzer.py

设计目标:
  - 不依赖 changedetection.io / HF Space / 时序DB
  - 基于即时快照数据产出 v3.0 框架所需的多公司信号
  - 输出可直接对接 #19 信号收敛框架
  - convergence_bonus: 0-3分 → 叠加到 #19 信号收敛计数

核心指标:
  - ADI: 基于绝对值方向修正(abs(hcp)), 四象限分类(aligned_bullish/divergence_trap_up/open_game/aligned_bearish/dual_deadlock)
  - SFI: ΔPinnacle_implied_prob - ΔCrown_implied_prob (>0.08 = 真资金领先)
  - 多公司共识: AH direction consensus + OU direction consensus
  - Pinnacle背离: 两家方向相反时自动标记

⚠️ 关键 Pitfall: ADI公式使用 abs(hcp) 比较而非原始数值。
  受让盘(hcp>0)与让球盘(hcp<0)的数值方向相反，
  但绝对值增大=让球方变强。直接用 ah_movement < -0.05 
  判"加深"会把受让→更深受让误判为"退盘"。
"""

import sys, json, math
from typing import Optional

# ── 盘口中文→数值 ──────────────────────────────────────────
# 约定: 正值=主队受让(underdog), 负值=主队让球(favorite)

HANDP_TO_NUM = {
    "平手": 0.0, "受让平手": 0.0,
    "平手/半球": -0.25, "受让平手/半球": 0.25,
    "半球": -0.5, "受让半球": 0.5,
    "半球/一球": -0.75, "受让半球/一球": 0.75,
    "一球": -1.0, "受让一球": 1.0,
    "一球/球半": -1.25, "受让一球/球半": 1.25,
    "球半": -1.5, "受让球半": 1.5,
    "球半/两球": -1.75, "受让球半/两球": 1.75,
    "两球": -2.0, "受让两球": 2.0,
    "两球/两球半": -2.25, "受让两球/两球半": 2.25,
    "两球半": -2.5, "受让两球半": 2.5,
    "两球半/三球": -2.75, "受让两球半/三球": 2.75,
    "三球": -3.0, "受让三球": 3.0,
}

def parse_handicap(hcp_str: str) -> Optional[float]:
    if not hcp_str or not hcp_str.strip():
        return None
    s = hcp_str.strip()
    if s in HANDP_TO_NUM:
        return HANDP_TO_NUM[s]
    try:
        return float(s)
    except ValueError:
        pass
    return None

def parse_ou_line(ou_str: str) -> Optional[float]:
    if not ou_str or not ou_str.strip():
        return None
    s = ou_str.strip()
    if "/" in s:
        parts = s.split("/")
        try:
            return (float(parts[0]) + float(parts[1])) / 2
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None

def parse_water(w: str) -> Optional[float]:
    if w is None or w == "-" or w == "":
        return None
    try:
        return float(str(w))
    except (ValueError, TypeError):
        return None

def implied_prob(home_water: float, away_water: float) -> tuple[float, float]:
    """港赔水位 → 去水隐含概率。1 + water = 十进制赔率近似。"""
    if home_water <= 0 or away_water <= 0:
        return 0.5, 0.5
    raw_h = 1.0 / (1.0 + home_water)
    raw_a = 1.0 / (1.0 + away_water)
    total = raw_h + raw_a
    if total == 0:
        return 0.5, 0.5
    return raw_h / total, raw_a / total

# ── 单公司 ADI + 方向 ───────────────────────────────────────

def analyze_company(name: str, data: dict) -> dict:
    ah = data.get("AH让球盘", {})
    ou = data.get("OU大小球盘", {})

    ah_open = ah.get("初盘opening") or {}
    ah_close = ah.get("赛前终盘closing") or {}
    ah_plate_hist = ah.get("plate_history", [])

    ah_open_line = parse_handicap(ah_open.get("盘口", ""))
    ah_close_line = parse_handicap(ah_close.get("盘口", ""))
    ah_close_hw = parse_water(ah_close.get("主水"))
    ah_close_aw = parse_water(ah_close.get("客水"))
    ah_open_hw = parse_water(ah_open.get("主水"))
    ah_open_aw = parse_water(ah_open.get("客水"))

    ou_open = ou.get("初盘opening") or {}
    ou_close = ou.get("赛前终盘closing") or {}
    ou_open_line = parse_ou_line(ou_open.get("盘口", ""))
    ou_close_line = parse_ou_line(ou_close.get("盘口", ""))
    ou_close_ovw = parse_water(ou_close.get("大球水"))
    ou_close_unw = parse_water(ou_close.get("小球水"))
    ou_open_ovw = parse_water(ou_open.get("大球水"))
    ou_open_unw = parse_water(ou_open.get("小球水"))

    # AH 方向
    ah_direction = "neutral"
    ah_strength = 0.0
    if ah_close_line is not None:
        if ah_close_line < -0.1:
            ah_direction = "home_favor"
            ah_strength = abs(ah_close_line)
        elif ah_close_line > 0.1:
            ah_direction = "away_favor"
            ah_strength = abs(ah_close_line)
        else:
            if ah_close_hw is not None and ah_close_aw is not None:
                if ah_close_hw < ah_close_aw - 0.03:
                    ah_direction = "home_favor"
                elif ah_close_aw < ah_close_hw - 0.03:
                    ah_direction = "away_favor"

    # AH 盘口移动
    ah_movement = 0.0
    if ah_open_line is not None and ah_close_line is not None:
        ah_movement = ah_close_line - ah_open_line
    elif ah_open_line is None and ah_close_line is not None and len(ah_plate_hist) >= 2:
        first = parse_handicap(ah_plate_hist[0])
        last = parse_handicap(ah_plate_hist[-1])
        if first is not None and last is not None:
            ah_movement = first - last

    # OU 方向
    ou_direction = "neutral"
    if ou_close_line is not None:
        ou_movement = 0.0
        if ou_open_line is not None:
            ou_movement = ou_close_line - ou_open_line
        if ou_close_ovw is not None and ou_close_unw is not None:
            if ou_close_ovw < ou_close_unw - 0.03:
                ou_direction = "over"
            elif ou_close_unw < ou_close_ovw - 0.03:
                ou_direction = "under"
            elif ou_movement > 0.05:
                ou_direction = "over"
            elif ou_movement < -0.05:
                ou_direction = "under"

    ou_movement_val = 0.0
    if ou_open_line is not None and ou_close_line is not None:
        ou_movement_val = ou_close_line - ou_open_line

    # ═══ ADI: 基于绝对值方向修正 ═══
    # 受让盘(hcp>0)与让球盘(hcp<0)的数值方向相反，
    # 但 abs(hcp)↑=让球方更强 · abs(hcp)↓=让球方变弱
    adi_result = {"type": "normal", "score": 5, "narrative": ""}

    ah_fav_stronger = False
    ah_fav_weaker = False
    if ah_open_line is not None and ah_close_line is not None:
        abs_open = abs(ah_open_line)
        abs_close = abs(ah_close_line)
        ah_fav_stronger = abs_close > abs_open + 0.04
        ah_fav_weaker = abs_close < abs_open - 0.04

    ou_rising = ou_movement_val > 0.05
    ou_falling = ou_movement_val < -0.05

    if ah_fav_stronger and ou_rising:
        adi_result = {"type": "aligned_bullish", "score": 8,
                      "narrative": "让球方加深+OU升盘: 强势方进攻预期增强，方向共振"}
    elif ah_fav_stronger and ou_falling:
        adi_result = {"type": "divergence_trap_up", "score": 3,
                      "narrative": "让球方加深+OU降盘: 强队热但进球不支持，⚠️诱上信号"}
    elif ah_fav_weaker and ou_rising:
        adi_result = {"type": "open_game", "score": 5,
                      "narrative": "让球方退盘+OU升盘: 比赛开放、强弱优势降，进球预期升"}
    elif ah_fav_weaker and ou_falling:
        adi_result = {"type": "aligned_bearish", "score": 8,
                      "narrative": "让球方退盘+OU降盘: 弱势保守，风险回撤，方向共振"}
    elif ah_movement == 0.0 and ou_movement_val == 0.0:
        adi_result = {"type": "dual_deadlock", "score": 4,
                      "narrative": "双盘死守: 市场无方向，确定性低"}
    else:
        adi_result = {"type": "mixed", "score": 5,
                      "narrative": "盘口变化混合，无明显背离"}

    imp_home = imp_away = None
    if ah_close_hw and ah_close_aw:
        imp_home, imp_away = implied_prob(ah_close_hw, ah_close_aw)

    return {
        "ah_line_open": ah_open_line,
        "ah_line_close": ah_close_line,
        "ah_movement": round(ah_movement, 2),
        "ah_direction": ah_direction,
        "ah_strength": round(ah_strength, 2),
        "ah_close_water": {"home": ah_close_hw, "away": ah_close_aw},
        "ah_close_imp_prob": {"home": round(imp_home, 4) if imp_home else None,
                              "away": round(imp_away, 4) if imp_away else None},
        "ou_line_open": ou_open_line,
        "ou_line_close": ou_close_line,
        "ou_movement": round(ou_movement_val, 2),
        "ou_direction": ou_direction,
        "ou_close_water": {"over": ou_close_ovw, "under": ou_close_unw},
        "adi": adi_result,
        "plate_history": ah_plate_hist,
        "data_freshness": ah.get("data_freshness", "N/A"),
    }

# ── 多公司交叉分析 ──────────────────────────────────────────

CROWN_IDS = {'3', 'Crown', 'Crow', '皇冠', '皇冠Crown'}
PINNACLE_IDS = {'24', 'Pinnacle', '平博', 'Pinnacle平博'}

def _find_company(companies: dict, ids: set) -> str | None:
    """按公司名/ID显式识别，不依赖输入顺序。"""
    for name in companies:
        if name in ids or any(cid in name for cid in ids):
            return name
    return None

def cross_analyze(companies: dict) -> dict:
    names = list(companies.keys())
    if len(names) < 2:
        return {"error": "需要至少2家公司", "signals_for_pipeline": {}}

    # 显式识别 Crown 和 Pinnacle，不依赖输入顺序
    crown_name = _find_company(companies, CROWN_IDS)
    pinnacle_name = _find_company(companies, PINNACLE_IDS)
    other_names = [n for n in names if n not in (crown_name, pinnacle_name)]

    if crown_name is None:
        return {"error": "未找到皇冠/皇冠Crown数据", "signals_for_pipeline": {"warnings": ["皇冠数据缺失"]}}
    if pinnacle_name is None:
        # 有皇冠但无平博：仍可产出部分分析
        c1_name, c2_name = crown_name, other_names[0] if other_names else None
        if c2_name is None:
            return {"error": "仅单家公司（皇冠），无法交叉分析", "signals_for_pipeline": {}}
    else:
        c1_name, c2_name = crown_name, pinnacle_name
    c1 = companies[c1_name]
    c2 = companies[c2_name]

    # SFI
    c1_h = c1.get("ah_close_imp_prob", {}).get("home")
    c2_h = c2.get("ah_close_imp_prob", {}).get("home")
    sfi = None
    if c1_h is not None and c2_h is not None:
        sfi_raw = c2_h - c1_h
        sfi = round(sfi_raw, 4)

    # AH 盘口差异
    c1_ah = c1.get("ah_line_close")
    c2_ah = c2.get("ah_line_close")
    ah_plate_diff = None
    if c1_ah is not None and c2_ah is not None:
        ah_plate_diff = round(c2_ah - c1_ah, 2)

    # 水位差异
    water_compare = {}
    if c1_ah == c2_ah and c1_ah is not None:
        c1_hw = c1.get("ah_close_water", {}).get("home", 0) or 0
        c2_hw = c2.get("ah_close_water", {}).get("home", 0) or 0
        c1_aw = c1.get("ah_close_water", {}).get("away", 0) or 0
        c2_aw = c2.get("ah_close_water", {}).get("away", 0) or 0
        water_compare = {
            "same_plate": True,
            "home_water_diff": round(c2_hw - c1_hw, 3),
            "away_water_diff": round(c2_aw - c1_aw, 3),
            "note": f"{c1_name}主水{c1_hw} vs {c2_name}主水{c2_hw}"
        }
    elif c1_ah is not None and c2_ah is not None:
        water_compare = {
            "same_plate": False,
            "plate_diff": ah_plate_diff,
            "note": f"{c1_name}={c1_ah} vs {c2_name}={c2_ah}"
        }

    # 共识
    c1_ah_dir = c1.get("ah_direction", "neutral")
    c2_ah_dir = c2.get("ah_direction", "neutral")
    c1_ou_dir = c1.get("ou_direction", "neutral")
    c2_ou_dir = c2.get("ou_direction", "neutral")

    ah_consensus = "agree" if c1_ah_dir == c2_ah_dir and c1_ah_dir != "neutral" else \
                   ("partial" if (c1_ah_dir != "neutral") != (c2_ah_dir != "neutral") else
                    "disagree" if c1_ah_dir != c2_ah_dir and c1_ah_dir != "neutral" and c2_ah_dir != "neutral" else
                    "neutral")
    ou_consensus = "agree" if c1_ou_dir == c2_ou_dir and c1_ou_dir != "neutral" else \
                   ("partial" if (c1_ou_dir != "neutral") != (c2_ou_dir != "neutral") else
                    "disagree" if c1_ou_dir != c2_ou_dir and c1_ou_dir != "neutral" and c2_ou_dir != "neutral" else
                    "neutral")

    pinnacle_divergence = None
    if ah_consensus == "disagree":
        pinnacle_divergence = {
            "type": "pinnacle_divergence",
            "severity": "warning",
            "note": f"Pinnacle({c2_ah_dir}) vs Crown({c1_ah_dir}) — 聪明钱方向与主流背离"
        }

    # 信号收敛加分
    convergence_bonus = 0
    signals = []
    warnings = []

    if ah_consensus == "agree":
        convergence_bonus += 1
        signals.append("multi_company_ah_consensus")
    if ou_consensus == "agree":
        convergence_bonus += 1
        signals.append("multi_company_ou_consensus")
    if ah_consensus == "disagree":
        warnings.append("ah_disagree: 皇冠与平博AH方向冲突")
    if ou_consensus == "disagree":
        warnings.append("ou_disagree: 皇冠与平博OU方向冲突")
    if pinnacle_divergence:
        warnings.append(pinnacle_divergence["note"])
    if sfi is not None and abs(sfi) > 0.03:
        sfi_dir = "Pinnacle偏主队" if sfi > 0 else "Pinnacle偏客队"
        if abs(sfi) > 0.08:
            signals.append(f"sfi_strong: {sfi_dir}({abs(sfi):.1%})")
            convergence_bonus += 1
        else:
            warnings.append(f"sfi_weak: {sfi_dir}({abs(sfi):.1%})")

    # ADI 冲突
    adi_alignment = _check_adi_alignment(companies)
    if adi_alignment == "conflict_trap":
        warnings.append("adi_conflict: 至少一家公司检测到ADI诱上/诱大球信号，与共识方向冲突")

    return {
        "sfi": sfi,
        "ah_plate_diff": ah_plate_diff,
        "water_compare": water_compare,
        "ah_consensus": ah_consensus,
        "ou_consensus": ou_consensus,
        "pinnacle_divergence": pinnacle_divergence,
        "signals_for_pipeline": {
            "convergence_bonus": convergence_bonus,
            "signal_sources": signals,
            "warnings": warnings,
            "adi_alignment": adi_alignment,
        }
    }

def _check_adi_alignment(companies: dict) -> str:
    adi_types = set()
    for name, data in companies.items():
        adi = data.get("adi", {}).get("type", "")
        if adi:
            adi_types.add(adi)
    if len(adi_types) <= 1:
        return "aligned"
    if "divergence_trap_up" in adi_types:
        return "conflict_trap"
    return "mixed"

# ── main ──────────────────────────────────────────────────────

def main():
    raw = sys.stdin.read()
    if not raw.strip():
        print(json.dumps({"error": "无输入，请管道 fetch_titan007_odds.py 的输出"}, ensure_ascii=False))
        sys.exit(1)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"JSON解析失败: {e}"}, ensure_ascii=False))
        sys.exit(1)

    match_id = data.get("match_id", "unknown")
    kicked = data.get("比赛已开球", False)
    companies_raw = data.get("companies", {})

    analyzed = {}
    for name, cdata in companies_raw.items():
        if not cdata.get("both_ok", False):
            continue
        analyzed[name] = analyze_company(name, cdata)

    if not analyzed:
        print(json.dumps({"error": "无有效公司数据"}, ensure_ascii=False))
        sys.exit(1)

    cross = cross_analyze(analyzed) if len(analyzed) >= 2 else {}
    optimal = _suggest_optimal(analyzed, cross)

    result = {
        "match_id": match_id,
        "kicked_off": kicked,
        "analyzer_version": "v1",
        "companies": analyzed,
        "cross_company": cross,
        "optimal_suggestion": optimal,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

def _suggest_optimal(companies: dict, cross: dict) -> dict:
    from collections import Counter
    ah_dirs = [c["ah_direction"] for c in companies.values() if c["ah_direction"] != "neutral"]
    ou_dirs = [c["ou_direction"] for c in companies.values() if c["ou_direction"] != "neutral"]
    ah_vote = Counter(ah_dirs).most_common(1)
    ou_vote = Counter(ou_dirs).most_common(1)
    consensus_ah = ah_vote[0][0] if ah_vote else "neutral"
    consensus_ou = ou_vote[0][0] if ou_vote else "neutral"

    adi_types = [c["adi"]["type"] for c in companies.values()]
    has_divergence = any("divergence" in t for t in adi_types)
    has_aligned = any("aligned" in t for t in adi_types)

    suggestion = {
        "ah_consensus_direction": consensus_ah,
        "ou_consensus_direction": consensus_ou,
        "adi_status": "divergence_warning" if has_divergence else ("aligned" if has_aligned else "neutral"),
    }
    sig = cross.get("signals_for_pipeline", {})
    bonus = sig.get("convergence_bonus", 0)
    if bonus >= 2:
        suggestion["signal_strength"] = "strong"
    elif bonus >= 1:
        suggestion["signal_strength"] = "moderate"
    else:
        suggestion["signal_strength"] = "weak"
    suggestion["convergence_bonus"] = bonus
    suggestion["warnings"] = sig.get("warnings", [])
    return suggestion

if __name__ == "__main__":
    main()
