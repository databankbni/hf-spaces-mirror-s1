#!/usr/bin/env python3
"""
皇冠水位 K 线 + 诱盘识别引擎

庄家逻辑（每条都必须从"庄家想让你做什么"反推）：
  庄家目标 = 平衡账面 + 吃水。他们不会告诉你方向，但水位调法暴露了意图。

核心六形态：
  T1. 锁盘诱多 — 盘口死守 + A侧水跌(资金追A) + B侧水涨 → 庄家乐意收A侧钱 → A会输 → 价值在B
  T2. 锁盘诱空 — 盘口死守 + A侧水涨(给更好价) + B侧水跌 → 庄家想让你买A → A会输 → 价值在B(矛盾!)
      纠: T2实际上是"A价值信号"。庄家给A更好价但不升盘 = 庄家不怕A赢 → A有价值。拉赫蒂/葛吉拉/南非模式。
  T3. 升盘诱多 — 盘口升 + 水跌(砍水) → 盘深了但价更差 → 庄家赶你去对面 → 跟升盘方向
  T4. 降盘诱空 — 盘口降 + 水升(给好价) → 盘浅了但价更好 → 庄家诱你买降盘方 → 逆向
  T5. 放量突破 — 单根K线振幅>0.12 → 庄家测试某个水位但守不住 → 突破方向是真实方向
  T6. 尾盘急转 — 最后2根K线反向大幅逆转 → 临场信息更新 → 跟尾盘方向

用法:
  python3 scripts/plot_water_kline.py <match_id> [--market AH] [--bucket 30]
"""

import json, sys, os, subprocess
from datetime import datetime
from collections import defaultdict
from typing import Optional

# ═══════════════════════════════════════════
# 数据获取
# ═══════════════════════════════════════════
def fetch_raw(match_id: str) -> dict:
    import os, sys, subprocess
    script_dir = os.path.dirname(os.path.abspath(__file__))
    fetcher = os.path.join(script_dir, "fetch_titan007_odds.py")
    python_bin = os.environ.get("HERMES_PYTHON", sys.executable)
    result = subprocess.run(
        [python_bin, fetcher, match_id, "--raw"],
        capture_output=True, text=True, timeout=60
    )
    return json.loads(result.stdout)


# ═══════════════════════════════════════════
# K 线聚合
# ═══════════════════════════════════════════
def parse_row(r: list) -> Optional[dict]:
    """解析一行 raw 数据。返回 None 如果是滚球或无效。"""
    try:
        wh = float(r[2]) if r[2] else None
        plate = r[3].strip()
        wa = float(r[4]) if r[4] else None
        time_str = r[5].strip()
        status = r[6].strip() if len(r) > 6 else ""
    except (ValueError, IndexError):
        return None
    if wh is None or wa is None:
        return None
    if "滚" in status:
        return None
    try:
        parts = time_str.split()
        if len(parts) >= 2:
            dt = datetime.strptime("2026-" + parts[0] + " " + parts[1], "%Y-%m-%d %H:%M")
        else:
            return None
    except ValueError:
        return None
    return {"dt": dt, "home_water": wh, "plate": plate, "away_water": wa}


def build_ohlc(rows: list, bucket_minutes: int = 30) -> list:
    """将原始行聚合成 OHLC K 线。"""
    parsed = [p for p in (parse_row(r) for r in rows) if p]
    if not parsed:
        return []
    parsed.sort(key=lambda x: x["dt"])
    t0 = parsed[0]["dt"]

    buckets = defaultdict(list)
    for p in parsed:
        delta = (p["dt"] - t0).total_seconds() / 60
        bk = int(delta // bucket_minutes)
        buckets[bk].append(p)

    ohlc = []
    for bk in sorted(buckets.keys()):
        items = buckets[bk]
        hw = [it["home_water"] for it in items]
        aw = [it["away_water"] for it in items]
        ohlc.append({
            "time": items[0]["dt"].strftime("%m-%d %H:%M"),
            "plate": items[0]["plate"],
            "home": {"o": hw[0], "h": max(hw), "l": min(hw), "c": hw[-1]},
            "away": {"o": aw[0], "h": max(aw), "l": min(aw), "c": aw[-1]},
        })
    return ohlc


# ═══════════════════════════════════════════
# 诱盘识别引擎 (v2 — 水/盘比率驱动)
# ═══════════════════════════════════════════

def plate_depth(plate: str, side: str) -> float:
    """将皇冠盘口文本转为让球深度(正=home受让,负=home让球)。"""
    plate = plate.strip()
    is_recv = ("受让" in plate) or ("受" in plate)
    cleaned = plate.replace("受让", "").replace("受", "").replace("让", "").strip()

    m = {
        "平手": 0, "平手/半球": 0.25, "平/半": 0.25,
        "半球": 0.5, "半": 0.5,
        "半球/一球": 0.75, "半/一": 0.75,
        "一球": 1.0, "一": 1.0,
        "一球/球半": 1.25, "一/球半": 1.25,
        "球半": 1.5,
        "球半/两球": 1.75, "球半/两": 1.75,
        "两球": 2.0, "两": 2.0,
        "两球/两球半": 2.25, "两/两半": 2.25,
        "两球半": 2.5, "两半": 2.5,
        "两球半/三球": 2.75, "两半/三": 2.75,
        "三球": 3.0, "三": 3.0,
        "三球/三球半": 3.25, "三球半": 3.5,
        "四球": 4.0,
    }
    v = m.get(cleaned, None)
    if v is None:
        # Fallback: try partial match
        for k, v2 in m.items():
            if k in cleaned:
                return -v2 if is_recv else v2
        return 0.0
    return v if is_recv else -v  # positive = home receives, negative = home gives


def body(candle: dict) -> float:
    return candle["c"] - candle["o"]

def detect_traps(ohlc: list, plate_history: list = None) -> dict:
    """从 K 线序列中识别庄家诱盘信号 (v2 水/盘比率)。"""
    if len(ohlc) < 4:
        return {"trap_signals": [], "direction_lean": "neutral", "trap_confidence": 0,
                "summary": "K线数据不足(需≥4根)"}

    signals = []
    n = len(ohlc)
    ph = plate_history or []

    # 盘口变化深度 (正=home受让加深=away让球加深)
    plate_delta = 0.0
    if len(ph) >= 2:
        plate_delta = plate_depth(ph[-1], "home") - plate_depth(ph[0], "home")

    # ═══ T2: 升水价值信号 (核心) ═══
    # 庄给更好价 = value. 看水涨 vs 盘变的关系。
    for side, label in [("home", "主队(受让)"), ("away", "客队(让球)")]:
        water_rise = ohlc[-1][side]["c"] - ohlc[0][side]["o"]
        opp_water_drop = ohlc[0]["away" if side == "home" else "home"]["o"] - \
                         ohlc[-1]["away" if side == "home" else "home"]["c"]

        # 盘对该侧的影响: home受让加深=正, home让球加深=负
        plate_effect = plate_delta if side == "home" else -plate_delta
        # plate_effect > 0: 盘向该侧倾斜(受让加深=更被看好)
        # plate_effect < 0: 盘向对手倾斜(让球加深=更不被看好)

        # T2a: 盘死守+水涨 ≥0.08 → 经典升水不升盘 (最强)
        # 🔧 v4 修复(2026-07-01): 显式检查盘口历史无任何变化, 防止OU多档移动被误判为死守
        plate_static = abs(plate_delta) < 0.01 and len(set(ph)) <= 1
        if plate_static and water_rise >= 0.06:
            strength = min(9, 4 + int(water_rise * 30))
            signals.append({
                "type": "T2a_锁盘升水",
                "side": side,
                "desc": f"盘口死守+{label}水涨+{water_rise:.2f}(对手水跌{opp_water_drop:.2f}) → 经典升水不升盘",
                "action": f"推{label}",
                "strength": strength,
            })

        # T2b: 盘向对手微调(≤0.25)但水仍逆势涨 → 庄在给价 (强)
        if 0 < abs(plate_delta) <= 0.25 and plate_effect < 0 and water_rise >= 0.06:
            strength = min(8, 5 + int(water_rise * 25))
            signals.append({
                "type": "T2b_逆盘升水",
                "side": side,
                "desc": f"盘口微调向对手({abs(plate_delta):.2f})但{label}水逆势涨+{water_rise:.2f} → 庄抗盘给价",
                "action": f"推{label}",
                "strength": strength,
            })

        # T2c: 盘向该侧倾斜+水也涨 → 双重确认但价仍好
        if plate_effect > 0 and water_rise >= 0.04:
            signals.append({
                "type": "T2c_顺盘升水",
                "side": side,
                "desc": f"盘口向{label}倾斜({plate_effect:+.2f})+水仍涨{water_rise:+.2f} → 双重确认",
                "action": f"推{label}",
                "strength": 5,
            })

    # ═══ T1: 降水过热 = 陷阱 ═══
    for side, label in [("home", "主队"), ("away", "客队")]:
        water_drop = ohlc[0][side]["o"] - ohlc[-1][side]["c"]
        if water_drop >= 0.06:
            signals.append({
                "type": "T1_降水过热",
                "side": side,
                "desc": f"{label}水跌-{water_drop:.2f}(钱追{label}) → {label}过热=陷阱",
                "action": f"fade{label}",
                "strength": min(8, int(water_drop * 40)),
            })

    # ═══ T3: 升盘 + 对手侧水跌 = 真实支持 ═══
    # 盘口向某方加深 + 该方对手水跌 → 市场真实看多该方
    if plate_delta != 0:
        favored_side = "away" if plate_delta > 0 else "home"  # home受让加深=away被看多
        opp_side = "home" if favored_side == "away" else "away"
        opp_water_drop = ohlc[0][opp_side]["o"] - ohlc[-1][opp_side]["c"]
        if opp_water_drop >= 0.03:
            signals.append({
                "type": "T3_升盘实撑",
                "side": favored_side,
                "desc": f"盘口加深+对手水跌{opp_water_drop:.2f} → 真实支持{favored_side}",
                "action": f"推{'客队' if favored_side == 'away' else '主队'}",
                "strength": min(7, 4 + int(opp_water_drop * 30)),
            })

    # ═══ T4: 降盘 + 水涨 = 诱空(假弱) ═══
    if abs(plate_delta) >= 0.25 and plate_delta != 0:
        weakened_side = "home" if plate_delta < 0 else "away"
        ws = ohlc[-1][weakened_side]["c"] - ohlc[0][weakened_side]["o"]
        if ws >= 0.05:
            signals.append({
                "type": "T4_降盘诱空",
                "side": weakened_side,
                "desc": f"盘口降{abs(plate_delta):.2f}但水涨+{ws:.2f} → 假弱=诱空",
                "action": f"推{'主队' if weakened_side == 'home' else '客队'}",
                "strength": 6,
            })

    # ═══ T5: 放量突破 ═══
    for side, label in [("home", "主队"), ("away", "客队")]:
        for i in range(1, n):
            amp = ohlc[i][side]["h"] - ohlc[i][side]["l"]
            if amp > 0.10:
                d = "涨" if body(ohlc[i][side]) > 0 else "跌"
                signals.append({
                    "type": "T5_放量", "side": side,
                    "desc": f"{label}水 {ohlc[i]['time']} 单K振幅{amp:.2f}→探后{d}",
                    "action": f"跟{d}", "strength": 3,
                })

    # ═══ T6: 尾盘急转 ═══
    if n >= 3:
        for side, label in [("home", "主队"), ("away", "客队")]:
            pb = body(ohlc[-2][side]); lb = body(ohlc[-1][side])
            if pb < -0.03 and lb > 0.05:
                signals.append({
                    "type": "T6_尾盘急转", "side": side,
                    "desc": f"{label}水尾盘急转涨{lb:+.2f} → 临场利多", "action": f"推{label}", "strength": 6})
            elif pb > 0.03 and lb < -0.05:
                signals.append({
                    "type": "T6_尾盘急转", "side": side,
                    "desc": f"{label}水尾盘急转跌{lb:+.2f} → 临场利空", "action": f"fade{label}", "strength": 6})

    # ═══ 综合方向 ═══
    home_score = 0; away_score = 0
    for s in signals:
        a = s.get("action", "")
        d = s.get("desc", "")
        if "推主队" in a or "推主队" in d: home_score += s["strength"]
        if "推客队" in a or "推客队" in d: away_score += s["strength"]
        if "fade主队" in a: away_score += s["strength"]
        if "fade客队" in a: home_score += s["strength"]

    if home_score > away_score + 2:
        lean, conf = "home_side", min(9, home_score // 2)
    elif away_score > home_score + 2:
        lean, conf = "away_side", min(9, away_score // 2)
    else:
        lean, conf = "neutral", max(0, min(5, (home_score + away_score) // 3))

    parts = [f"[{s['type']}] {s['desc']} → {s['action']}" for s in sorted(signals, key=lambda x: -x["strength"])[:5]]
    summary = "\n".join(parts) if parts else "无明显诱盘信号，K线平稳"

    return {
        "trap_signals": signals, "direction_lean": lean, "trap_confidence": conf,
        "home_score": home_score, "away_score": away_score, "summary": summary,
        "plate_delta": plate_delta,
    }


# ═══════════════════════════════════════════
# 形态识别引擎 — 区分真热/真空 vs 诱多/诱空
# ═══════════════════════════════════════════

def classify_trend(ohlc: list, side: str) -> dict:
    """简化版趋势分类: 真趋势=整体移动大+尾盘确认, 假脉冲=单刺+反转。"""
    if len(ohlc) < 4:
        return {"type": "unknown", "strength": 0, "desc": "数据不足"}

    vals = [bar[side]["c"] for bar in ohlc]
    n = len(vals)
    overall_change = vals[-1] - vals[0]
    direction = "up" if overall_change > 0.03 else ("down" if overall_change < -0.03 else "flat")

    # 1. 整体移动幅度
    abs_change = abs(overall_change)

    # 2. 尾盘方向: 最后 20% K线的净变化
    tail_n = max(3, n // 5)
    tail_change = vals[-1] - vals[-tail_n]
    tail_confirms = (tail_change > 0) == (overall_change > 0) if abs(overall_change) > 0.01 else False

    # 3. 最大单根振幅 vs 整体变化 (脉冲比)
    amps = [bar[side]["h"] - bar[side]["l"] for bar in ohlc]
    max_amp = max(amps) if amps else 0
    # 如果最大振幅占总变化比例很高 → 脉冲性
    pulse_pct = max_amp / abs_change if abs_change > 0.005 else 99

    # 4. 分类
    if abs_change >= 0.06 and tail_confirms and pulse_pct < 1.5:
        trend_type = "真趋势"
        strength = min(9, 5 + int(abs_change * 30))
    elif abs_change >= 0.04 and tail_confirms and pulse_pct < 2.5:
        trend_type = "偏真"
        strength = min(7, 4 + int(abs_change * 25))
    elif pulse_pct >= 3.0 and abs_change < 0.03:
        trend_type = "假脉冲"
        strength = 2
    elif abs_change < 0.02:
        trend_type = "无趋势"
        strength = 1
    else:
        trend_type = "偏真" if tail_confirms else "震荡"
        strength = 4 if tail_confirms else 2

    desc = (f"{'↑' if overall_change>0 else '↓'}{abs_change:.2f}"
            f" 尾盘{'确认' if tail_confirms else '背离'}"
            f" 脉冲{'集中' if pulse_pct>2 else '分散'}({pulse_pct:.1f}x)")

    return {
        "type": trend_type, "strength": strength, "desc": desc,
        "direction": direction, "overall_change": overall_change,
        "tail_confirms": tail_confirms, "pulse_pct": pulse_pct,
    }


def detect_candlestick_patterns(ohlc: list, side: str) -> list:
    """检测经典K线形态: 三兵/三鸦/锤子/十字星/吞没/晨星/暮星。"""
    patterns = []
    if len(ohlc) < 3:
        return patterns

    n = len(ohlc)
    bars = [bar[side] for bar in ohlc]
    bodies = [b["c"] - b["o"] for b in bars]
    upper_shadows = [b["h"] - max(b["o"], b["c"]) for b in bars]
    lower_shadows = [min(b["o"], b["c"]) - b["l"] for b in bars]
    ranges = [b["h"] - b["l"] for b in bars]

    # --- 最后3根K线检测 ---
    last3 = list(range(max(0, n-3), n))

    # 三连阳 (红三兵) — 持续推升 = 真价值
    if len(last3) == 3:
        if all(bodies[i] > 0.01 for i in last3):
            total_rise = bars[last3[-1]]["c"] - bars[last3[0]]["o"]
            if total_rise >= 0.03:
                patterns.append({"type": "红三兵", "desc": f"三连阳推升+{total_rise:.2f}",
                                "meaning": "真价值_持续给价", "strength": 7})

    # 三连阴 (黑三鸦) — 持续压降 = 真陷阱
    if len(last3) == 3:
        if all(bodies[i] < -0.01 for i in last3):
            total_fall = bars[last3[0]]["o"] - bars[last3[-1]]["c"]
            if total_fall >= 0.03:
                patterns.append({"type": "黑三鸦", "desc": f"三连阴压降-{total_fall:.2f}",
                                "meaning": "真陷阱_持续砍水", "strength": 7})

    # 锤子线 — 下影线 >> 实体 → 支撑确认
    for i in last3:
        rng = ranges[i]
        if rng > 0.01 and lower_shadows[i] > 2 * abs(bodies[i]) and lower_shadows[i] > 0.5 * rng:
            patterns.append({"type": "锤子线",
                            "desc": f"K{i}下影线{lower_shadows[i]:.2f}>>实体 → 支撑",
                            "meaning": "诱空_假跌破", "strength": 5})

    # 上吊线 — 上影线 >> 实体 → 压力
    for i in last3:
        rng = ranges[i]
        if rng > 0.01 and upper_shadows[i] > 2 * abs(bodies[i]) and upper_shadows[i] > 0.5 * rng:
            patterns.append({"type": "上吊线",
                            "desc": f"K{i}上影线{upper_shadows[i]:.2f}>>实体 → 压力",
                            "meaning": "诱多_假突破", "strength": 5})

    # 晨星 — 阴→小实体→阳 → 反转向上
    if len(last3) >= 3:
        i0, i1, i2 = last3[0], last3[1], last3[2]
        if bodies[i0] < -0.01 and abs(bodies[i1]) < 0.008 and bodies[i2] > 0.02:
            patterns.append({"type": "晨星反转",
                            "desc": "阴→十字→阳 → 底部反转向上",
                            "meaning": "空转多_诱空结束", "strength": 8})

    # 暮星 — 阳→小实体→阴 → 反转向下
    if len(last3) >= 3:
        i0, i1, i2 = last3[0], last3[1], last3[2]
        if bodies[i0] > 0.01 and abs(bodies[i1]) < 0.008 and bodies[i2] < -0.02:
            patterns.append({"type": "暮星反转",
                            "desc": "阳→十字→阴 → 顶部反转向下",
                            "meaning": "多转空_诱多结束", "strength": 8})

    return patterns


def analyze_flow(ohlc: list, market: str = "AH") -> dict:
    """整合趋势+形态 → 输出庄家意图评估。
    market='AH' → home=主队(受让), away=客队(让球)
    market='OU' → home=大球, away=小球
    """
    labels = {"home": "主队(受让)", "away": "客队(让球)"} if market == "AH" else {"home": "大球", "away": "小球"}
    ah_patterns = {}
    for side, lbl in [("home", labels["home"]), ("away", labels["away"])]:
        trend = classify_trend(ohlc, side)
        patterns = detect_candlestick_patterns(ohlc, side)
        # 综合: 真趋势+确认形态 = 高置信度
        is_real = trend["type"] in ("真趋势", "偏真")
        confirming = any(p["strength"] >= 5 for p in patterns)

        signal_quality = "🟢强" if is_real and confirming else \
                        "🟡中" if is_real or confirming else \
                        "🔴弱"

        ah_patterns[side] = {
            "label": lbl,
            "trend": trend,
            "patterns": [p["type"] for p in patterns],
            "signal_quality": signal_quality,
            "summary": f"{trend['desc']} | 形态: {', '.join(p['type'] for p in patterns) or '无'} | {signal_quality}"
        }

    # 综合意图 — 基于趋势类型+尾盘确认
    home_t = ah_patterns.get("home", {}).get("trend", {})
    away_t = ah_patterns.get("away", {}).get("trend", {})
    home_dir = home_t.get("direction", "flat")
    away_dir = away_t.get("direction", "flat")
    home_tail = home_t.get("tail_confirms", False)
    away_tail = away_t.get("tail_confirms", False)
    home_type = home_t.get("type", "")
    away_type = away_t.get("type", "")

    # 真趋势 + 尾盘确认 = 强信号
    home_strong = home_type in ("真趋势", "偏真") and home_tail
    away_strong = away_type in ("真趋势", "偏真") and away_tail

    hl, al = labels["home"], labels["away"]
    if home_dir == "up" and home_strong and away_dir != "up":
        intent = f"🟢 {hl}水真涨(尾盘确认) → 诱空{hl} → {hl}有价值"
    elif away_dir == "up" and away_strong and home_dir != "up":
        intent = f"🟢 {al}水真涨(尾盘确认) → 诱空{al} → {al}有价值"
    elif home_dir == "up" and not home_tail:
        intent = f"🔴 {hl}水位上涨但尾盘背离 → 信号弱化 → 谨慎"
    elif away_dir == "up" and not away_tail:
        intent = f"🔴 {al}水位上涨但尾盘背离 → 信号弱化 → 谨慎"
    elif home_strong and away_strong:
        intent = f"⚠️ 双方均有真趋势 → 盘口方向决定(结合plate_delta)"
    else:
        intent = f"⚪ 无明确持续趋势 → 观望"

    return {"patterns": ah_patterns, "intent": intent}
# ═══════════════════════════════════════════
def ascii_kline(ohlc: list, title: str, side: str, side_label: str) -> str:
    if not ohlc:
        return "(无数据)"
    key = side
    vals = []
    for bar in ohlc:
        vals.extend([bar[key]["o"], bar[key]["h"], bar[key]["l"], bar[key]["c"]])
    vmin, vmax = min(vals), max(vals)
    if vmax == vmin:
        vmax += 0.02

    h, w = 16, min(len(ohlc), 60)
    step = max(1, len(ohlc) // w)
    grid = [[" " for _ in range(w)] for _ in range(h)]

    def y(v):
        return int((1 - (v - vmin) / (vmax - vmin)) * (h - 1))

    for idx in range(0, len(ohlc), step):
        col = idx // step
        if col >= w:
            break
        bar = ohlc[idx]
        o, hi, lo, c = bar[key]["o"], bar[key]["h"], bar[key]["l"], bar[key]["c"]
        yo, yhi, ylo, yc = y(o), y(hi), y(lo), y(c)
        for row in range(min(yhi, ylo), max(yhi, ylo) + 1):
            if 0 <= row < h:
                grid[row][col] = "│"
        sym = "█" if c >= o else "░"
        for row in range(min(yo, yc), max(yo, yc) + 1):
            if 0 <= row < h:
                grid[row][col] = sym

    lines = [f"{title} [{side_label}水, {vmin:.2f}~{vmax:.2f}]"]
    for row in range(h):
        label = f"{vmax - row*(vmax-vmin)/(h-1):.2f}" if row % 4 == 0 else "     "
        lines.append(f"{label} │{''.join(grid[row])}")
    lines.append(f"{'─'*5}└{'─'*w}")
    return "\n".join(lines)


# ═══════════════════════════════════════════
# 主程序
# ═══════════════════════════════════════════
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("match_id")
    ap.add_argument("--market", default="AH", choices=["AH", "OU", "both"])
    ap.add_argument("--bucket", type=int, default=0, help="K线周期(分钟), 0=auto")
    ap.add_argument("--ascii", action="store_true", help="[DEPRECATED: use --debug-ascii] 仅输出 ASCII 人工图")
    ap.add_argument("--debug-ascii", action="store_true", help="仅输出 ASCII 人工图（调试用）")
    ap.add_argument("--json", action="store_true", help="输出完整 JSON（含 OHLC 明细）")
    ap.add_argument("--no-compact", action="store_true", help="禁用紧凑模式（= --json 模式）")
    args = ap.parse_args()
    
    # --ascii 兼容 --debug-ascii
    if args.ascii and not args.debug_ascii:
        args.debug_ascii = True
    
    if args.debug_ascii and args.json:
        print("ERROR: --debug-ascii 和 --json 不能同时使用", file=sys.stderr)
        sys.exit(1)
    if args.debug_ascii and args.no_compact:
        print("ERROR: --debug-ascii 和 --no-compact 不能同时使用", file=sys.stderr)
        sys.exit(1)
    
    # Default mode: compact. Only full JSON if --json or --no-compact.
    use_compact = not args.json and not args.no_compact and not args.debug_ascii

    data = fetch_raw(args.match_id)
    crown = data["companies"]["皇冠Crown"]

    outputs = []
    for market_key, market_name in [("AH让球盘", "AH"), ("OU大小球盘", "OU")]:
        if args.market not in ("both", market_name):
            continue

        rows = crown[market_key]["历史全行"]
        
        # auto bucket 选择
        if args.bucket > 0:
            bucket = args.bucket
        else:
            row_count = len(rows)
            if row_count >= 300:
                bucket = 60
            elif row_count >= 150:
                bucket = 30
            elif row_count >= 60:
                bucket = 15
            else:
                bucket = 5
            # 如果已开球，缩小 bucket
            if crown[market_key].get("kicked_off", False):
                bucket = max(5, bucket // 2)
        
        ohlc = build_ohlc(rows, bucket)

        # 盘口轨迹：v2 fetch 脚本的 plate_history 为权威来源
        market_data = crown.get(market_key, {})
        if "plate_history" in market_data:
            unique_plates = market_data["plate_history"]
            plate_source = "fetch_script_v2"
        else:
            plates = []
            for r in rows:
                p = parse_row(r)
                if p:
                    plates.append(p["plate"])
            unique_plates = list(dict.fromkeys(plates))
            plate_source = "kline_derived"

        # 诱盘分析
        traps = detect_traps(ohlc, unique_plates)
        flow = analyze_flow(ohlc, market=market_name)

        # --- ASCII / debug-ascii 输出 ---
        if args.debug_ascii:
            print(f"\n{'═'*55}")
            print(f"  {market_name} 水位 K 线 — 诱盘识别")
            print(f"{'═'*55}")

            if market_name == "AH":
                print(ascii_kline(ohlc, f"AH 主队(受让方)", "home", "主(受让)"))
                print()
                print(ascii_kline(ohlc, f"AH 客队(让球方)", "away", "客(让球)"))
            else:
                print(ascii_kline(ohlc, f"OU 大球", "home", "大球"))
                print(ascii_kline(ohlc, f"OU 小球", "away", "小球"))

            if flow:
                print(f"\n  📐 形态分析:")
                for side in ["home", "away"]:
                    p = flow["patterns"][side]
                    print(f"  {p['label']}: {p['summary']}")
                print(f"  🎯 庄家意图: {flow['intent']}")

            print(f"\n{'─'*55}")
            print(f"  盘口变化: {' → '.join(unique_plates) if unique_plates else '(无变化)'}")
            print(f"  K线数: {len(ohlc)}, 周期: {args.bucket}min")
            print(f"\n  📍 庄家意图评估:")
            print(f"  {traps['summary']}")
            print(f"  方向倾向: {traps['direction_lean']}, 置信度: {traps['trap_confidence']}/10")
            print(f"{'─'*55}\n")

        # 水位反转检测
        water_reversal = False
        value_window_closed = False
        if len(ohlc) >= 4:
            for side in ["home", "away"]:
                vals = [bar[side]["c"] for bar in ohlc]
                # 最后两根 K 线反向
                if len(vals) >= 3:
                    mid = len(vals) // 2
                    first_half = vals[mid] - vals[0]
                    second_half = vals[-1] - vals[mid]
                    if abs(first_half) > 0.03 and second_half * first_half < -0.02:
                        water_reversal = True
                        break
        
        # JSON 输出对象
        kline_source = f"fetch_api_{bucket}min_{len(rows)}rows"
        out = {
            "kline_source": kline_source,
            "market": market_name,
            "buckets": len(ohlc),
            "bucket_min": bucket,
            "plate_history": unique_plates,
            "closing_plate": unique_plates[-1] if unique_plates else None,
            "closing_home_water": ohlc[-1]["home"]["c"] if ohlc else None,
            "closing_away_water": ohlc[-1]["away"]["c"] if ohlc else None,
            "water_reversal_detected": water_reversal,
            "value_window_closed": value_window_closed,
            "kline_confidence": traps["trap_confidence"],
            "kline_direction": traps["direction_lean"],
            "patterns": list(set(
                (p["type"] if isinstance(p, dict) else str(p))
                for side in ["home", "away"]
                for p in (flow.get("patterns", {}).get(side, {}).get("patterns", []) if isinstance(flow.get("patterns", {}).get(side, {}), dict) else [])
            )) if flow else [],
            "bucket_used": bucket,
            "trap_analysis": {
                "signals": traps["trap_signals"],
                "direction_lean": traps["direction_lean"],
                "confidence": traps["trap_confidence"],
                "home_score": traps.get("home_score", 0),
                "away_score": traps.get("away_score", 0),
                "summary": traps["summary"],
            }
        }
        outputs.append(out)

    # JSON 输出
    if use_compact:
        # Compact mode: only direction/confidence/summary
        compact = {
            "kline_source": "real",
            "match_id": args.match_id,
        }
        for out in outputs:
            market_key = out["market"]
            compact[market_key] = {
                "kline_direction": out.get("kline_direction", "neutral"),
                "kline_confidence": out.get("kline_confidence", 0),
                "water_reversal_detected": out.get("water_reversal_detected", False),
                "value_window_closed": out.get("value_window_closed", False),
                "patterns": out.get("patterns", []),
            }
        print(json.dumps(compact, ensure_ascii=False, indent=2))
    elif args.json or args.no_compact:
        if args.market == "both":
            print(json.dumps({
                "match_id": args.match_id,
                "markets": outputs,
            }, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(outputs[0], ensure_ascii=False, indent=2))
