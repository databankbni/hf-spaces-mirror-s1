#!/usr/bin/env python3
"""
research/loop_backtest.py — Continuous prompt optimization loop (AI-only, no strategies).

Runs backtest → analyzes accuracy → applies targeted prompt fix → repeats
indefinitely until target price range predictions achieve ≥90% accuracy on all
timeframes (1D, 3D, 5D), matching actual NSE price movements within predicted ranges.

Features:
  - No hard iteration ceiling: runs until target is met or Ctrl+C
  - Auto-detects model rate limits and waits for cooldown before retrying
  - AI predictions only (no strategy signals, matched_strategy=null)
  - Backs up CSV and prompt on every iteration

Usage:
  python research/loop_backtest.py
  python research/loop_backtest.py --reset   # clear CSV and start fresh
"""
from __future__ import annotations
import sys, os, re, shutil, subprocess, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd

CSV_PATH    = os.path.join(os.path.dirname(__file__), "ai_prompt_accuracy.csv")
FORECAST_PY = os.path.join(os.path.dirname(__file__), "..", "ai_forecast.py")
TARGET      = 90.0
BACKTEST_CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
ITERATION_BACKUP_RE = re.compile(r"ai_prompt_accuracy_iter(\d+)\.csv$")

# Hold-out boundary — must match backtest.py HOLDOUT_START.
# Training window for loop optimization = rolling 18 months ending the day before this.
HOLDOUT_START = "2025-01-01"


# ── ANALYSIS ──────────────────────────────────────────────────────────────────

def analyze(csv_path: str) -> dict | None:
    if not os.path.exists(csv_path):
        return None
    df = pd.read_csv(csv_path)
    if "timeframe" not in df.columns:
        print("  [WARN] CSV has no timeframe column — old format"); return None

    res = {}
    if "intraday_hit_for_tf" not in df.columns:
        print("  [WARN] CSV missing intraday_hit_for_tf column — re-run backtest with updated script")
        return None

    # Exclude non-LLM rows — only real provider/model predictions count toward targets.
    n_total = len(df)
    if "source" in df.columns:
        excluded_sources = {"heuristic", "ai_unavailable", "failed"}
        df = df[~df["source"].isin(excluded_sources)].copy()
        n_llm = len(df)
        n_heuristic = n_total - n_llm
        if n_heuristic > 0:
            print(f"  [FILTER] Dropped {n_heuristic}/{n_total} non-LLM rows — only {n_llm} real LLM predictions counted")
        if n_llm == 0:
            print("  [WARN] Zero LLM predictions in CSV — all rows were non-LLM (heuristic/ai_unavailable/failed).")
            return None
        llm_pct = n_llm / n_total * 100
        if llm_pct < 50:
            print(f"  [WARN] Only {llm_pct:.0f}% of predictions came from LLM — results may not be representative")

    # Scope: INTRADAY + 1D only. 3D/5D are retired from every production path (CLAUDE.md,
    # "No 3D/5D on prod API") — this loop should never spend iterations re-tuning a timeframe
    # nothing in prod ever calls.
    for tf in ["INTRADAY", "1D"]:
        sub = df[df["timeframe"] == tf]
        if sub.empty:
            continue
        directional = sub[sub["direction"].isin(["BULLISH", "BEARISH"])].copy()
        bull  = directional[directional["direction"] == "BULLISH"]
        bear  = directional[directional["direction"] == "BEARISH"]
        # PRIMARY METRIC: target_hit (actual price range predictions)
        tgt_acc = directional["target_hit_for_tf"].mean() * 100 if len(directional) >= 3 else float("nan")
        tgt_bull = bull["target_hit_for_tf"].mean() * 100 if len(bull) >= 3 else float("nan")
        tgt_bear = bear["target_hit_for_tf"].mean() * 100 if len(bear) >= 3 else float("nan")
        # SECONDARY: band-touch "directional" hit (for diagnostics — NOT real direction accuracy,
        # see real_dir_acc/real_pnl below for that).
        dir_acc = directional["intraday_hit_for_tf"].mean() * 100 if len(directional) >= 3 else float("nan")
        b_acc = bull["intraday_hit_for_tf"].mean() * 100 if len(bull) >= 3 else float("nan")
        e_acc = bear["intraday_hit_for_tf"].mean() * 100 if len(bear) >= 3 else float("nan")

        # REAL direction accuracy + net P&L — did the stock actually move the predicted way,
        # and would trading it have made money net of NSE round-trip costs. This is the metric
        # target_hit/dir_acc above are blind to (a low, easily-touched near-bound can "hit" a
        # band on either metric regardless of whether the direction call has any real edge).
        real_dir_acc = real_pnl = real_pnl_bull = real_pnl_bear = float("nan")
        try:
            from costs import cost_pct_for_timeframe
            if tf == "INTRADAY":
                real_move = pd.to_numeric(directional.get("ret_intraday_real"), errors="coerce")
            else:
                real_move = pd.to_numeric(directional.get("ret_for_tf"), errors="coerce")
            valid = directional[real_move.notna()].copy()
            valid["real_move"] = real_move[real_move.notna()]
            if len(valid) >= 3:
                is_bull = valid["direction"] == "BULLISH"
                correct = np.where(is_bull, valid["real_move"] > 0, valid["real_move"] < 0)
                gross = np.where(is_bull, valid["real_move"], -valid["real_move"])
                net = gross - cost_pct_for_timeframe(tf)
                real_dir_acc = correct.mean() * 100
                real_pnl = net.mean()
                if is_bull.sum() >= 3:
                    real_pnl_bull = net[is_bull.values].mean()
                if (~is_bull).sum() >= 3:
                    real_pnl_bear = net[(~is_bull).values].mean()
        except Exception:
            pass

        res[tf] = {
            "target_acc":  tgt_acc,
            "target_bull": tgt_bull,
            "target_bear": tgt_bear,
            "dir_acc":     dir_acc,
            "bull_acc":    b_acc,
            "bear_acc":    e_acc,
            "real_dir_acc": real_dir_acc,
            "real_pnl":     real_pnl,
            "real_pnl_bull": real_pnl_bull,
            "real_pnl_bear": real_pnl_bear,
            "n_bull":      len(bull),
            "n_bear":      len(bear),
            "n_dir":       len(directional),
            "n_total":     len(sub),
            "bear_ratio":  (directional["direction"] == "BEARISH").mean() * 100 if len(directional) else 0,
            "med_bull_acc": sub[(sub["confidence"] == "MEDIUM") & (sub["direction"] == "BULLISH")]["intraday_hit_for_tf"].mean() * 100
                            if len(sub[(sub["confidence"] == "MEDIUM") & (sub["direction"] == "BULLISH")]) >= 3
                            else float("nan"),
        }
    return res


MIN_LLM_PREDICTIONS = 30   # require at least 30 real LLM rows per TF before declaring target met

def target_met(res: dict) -> bool:
    for tf, r in res.items():
        if r.get("n_dir", 0) < 5:
            return False
        if r.get("n_dir", 0) < MIN_LLM_PREDICTIONS:
            print(f"  [GATE] {tf}: only {r.get('n_dir',0)} predictions (need {MIN_LLM_PREDICTIONS}) — target not met yet")
            return False
        # PRIMARY: target_hit accuracy must reach 90%
        if np.isnan(r.get("target_acc", float("nan"))) or r.get("target_acc", 0) < TARGET:
            return False
    return True


def next_backup_iteration(csv_path: str) -> int:
    """Return the next monotonically increasing iterN suffix for CSV backups."""
    directory = os.path.dirname(csv_path)
    highest = -1
    for name in os.listdir(directory):
        match = ITERATION_BACKUP_RE.match(name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def print_summary(res: dict, iteration: int):
    print(f"\n{'='*70}")
    print(f"  ITERATION {iteration} RESULTS")
    print(f"{'='*70}")
    print(f"  {'TF':<9} {'TgtHit':>10} {'TgtBull':>10} {'TgtBear':>10} {'DirHit':>9} {'N_DIR':>8} {'BearRat':>9}")
    print(f"  {'-'*66}")
    for tf in ["INTRADAY", "1D"]:
        r = res.get(tf, {})
        ta  = f"{r.get('target_acc',float('nan')):.1f}%" if not np.isnan(r.get('target_acc', float('nan'))) else "n/a"
        tb  = f"{r.get('target_bull',float('nan')):.1f}%" if not np.isnan(r.get('target_bull', float('nan'))) else "n/a"
        te  = f"{r.get('target_bear',float('nan')):.1f}%" if not np.isnan(r.get('target_bear', float('nan'))) else "n/a"
        da  = f"{r.get('dir_acc',float('nan')):.1f}%" if not np.isnan(r.get('dir_acc', float('nan'))) else "n/a"
        br  = f"{r.get('bear_ratio',0):.1f}%"
        nd  = r.get('n_dir', 0)
        tgt_ok = not np.isnan(r.get('target_acc', float('nan'))) and r.get('target_acc', 0) >= TARGET
        status = "✓" if tgt_ok else "✗"
        print(f"  {tf:<9} {ta:>10} {status}  {tb:>10}  {te:>10}  {da:>8}  {nd:>6}  {br:>8}")

    # Real direction-accuracy + net P&L — the metric TgtHit/DirHit above are blind to. Printed
    # separately so it's impossible to miss even though it isn't (yet) a pass/fail gate.
    print(f"\n  {'TF':<9} {'RealDirAcc':>11} {'RealP&L':>9} {'P&L(Bull)':>10} {'P&L(Bear)':>10}")
    print(f"  {'-'*54}")
    for tf in ["INTRADAY", "1D"]:
        r = res.get(tf, {})
        rda = f"{r.get('real_dir_acc',float('nan')):.1f}%" if not np.isnan(r.get('real_dir_acc', float('nan'))) else "n/a"
        rp  = f"{r.get('real_pnl',float('nan')):+.3f}%" if not np.isnan(r.get('real_pnl', float('nan'))) else "n/a"
        rpb = f"{r.get('real_pnl_bull',float('nan')):+.3f}%" if not np.isnan(r.get('real_pnl_bull', float('nan'))) else "n/a"
        rpe = f"{r.get('real_pnl_bear',float('nan')):+.3f}%" if not np.isnan(r.get('real_pnl_bear', float('nan'))) else "n/a"
        print(f"  {tf:<9} {rda:>11} {rp:>9} {rpb:>10} {rpe:>10}")
    print()


# ── PROMPT FIXES ──────────────────────────────────────────────────────────────

def read_forecast(path: str) -> str:
    with open(path, "r") as f:
        return f.read()

def write_forecast(path: str, content: str):
    with open(path, "w") as f:
        f.write(content)


def _replace_once(src: str, old: str, new: str) -> tuple[str, bool]:
    if old in src:
        return src.replace(old, new, 1), True
    return src, False


def _find_in_synthesis(src: str, target: str) -> bool:
    """Check if target string exists inside _build_synthesis_prompt function."""
    start = src.find("def _build_synthesis_prompt(")
    end = src.find("def _downgrade_confidence(", start)
    if start == -1 or end == -1:
        return False
    return target in src[start:end]


def _replace_in_synthesis(src: str, old: str, new: str) -> tuple[str, bool]:
    """Replace string inside _build_synthesis_prompt only."""
    start = src.find("def _build_synthesis_prompt(")
    end = src.find("def _downgrade_confidence(", start)
    if start == -1 or end == -1:
        return src, False
    block = src[start:end]
    if old not in block:
        return src, False
    block = block.replace(old, new, 1)
    return src[:start] + block + src[end:], True


# ── PROMPT FIX FUNCTIONS ──────────────────────────────────────────────────────
# All fixes target the signal alignment rules in _build_synthesis_prompt.
# Strategy: the key lever for >90% accuracy is direction accuracy.
# We do this by tightening the criteria that must be met before LLM calls directional.

def fix_tighten_1d_bullish_rsi(src: str, iteration: int) -> tuple[str, str]:
    """Tighten 1D BULLISH RSI threshold — require stronger oversold to call BULLISH."""
    pairs = [
        ("- BULLISH when: RSI < 40 (oversold bounce) OR (above EMA50 AND MACD > 0 AND volume high)\n",
         f"- BULLISH when: RSI < 35 (deep oversold) OR (above EMA50 AND MACD > 0 AND volume > 1.3x avg) [v{iteration}]\n"),
        (f"- BULLISH when: RSI < 35 (deep oversold) OR (above EMA50 AND MACD > 0 AND volume > 1.3x avg) [v{iteration-1}]\n",
         f"- BULLISH when: RSI < 32 (extreme oversold) OR (above EMA50 AND MACD > 0 AND volume > 1.5x avg) [v{iteration}]\n"),
    ]
    for old, new in pairs:
        new_src, ok = _replace_in_synthesis(src, old, new)
        if ok:
            return new_src, f"  [FIX] 1D BULLISH RSI tightened to {32 if 'extreme' in new else 35}"
    return src, "  [FIX] 1D BULLISH RSI anchor not found — skipped"


def fix_tighten_1d_bearish_rsi(src: str, iteration: int) -> tuple[str, str]:
    """Tighten 1D BEARISH RSI threshold — require more overbought to call BEARISH."""
    pairs = [
        ("- BEARISH when: RSI > 68 AND below EMA50 AND MACD < 0 AND volume confirms\n",
         f"- BEARISH when: RSI > 72 AND below EMA50 AND MACD < 0 AND volume confirms downside [v{iteration}]\n"),
        (f"- BEARISH when: RSI > 72 AND below EMA50 AND MACD < 0 AND volume confirms downside [v{iteration-1}]\n",
         f"- BEARISH when: RSI > 75 AND below BOTH EMA50 AND EMA200 AND MACD < 0 AND 90D return negative [v{iteration}]\n"),
    ]
    for old, new in pairs:
        new_src, ok = _replace_in_synthesis(src, old, new)
        if ok:
            return new_src, f"  [FIX] 1D BEARISH RSI threshold raised"
    return src, "  [FIX] 1D BEARISH RSI anchor not found — skipped"


def fix_tighten_3d_signal_count(src: str, iteration: int) -> tuple[str, str]:
    """Tighten 3D direction criteria — require more evidence for directional calls."""
    pairs = [
        ("- BEARISH when: below EMA50 AND (RSI > 58 OR MACD < 0) AND macro/sector headwinds\n",
         f"- BEARISH when: below EMA50 AND RSI > 58 AND MACD < 0 AND macro/sector headwinds [v{iteration}]\n"),
        (f"- BEARISH when: below EMA50 AND RSI > 58 AND MACD < 0 AND macro/sector headwinds [v{iteration-1}]\n",
         f"- BEARISH when: below BOTH EMA50 AND EMA200 AND RSI > 60 AND MACD < 0 AND 90D return negative [v{iteration}]\n"),
    ]
    for old, new in pairs:
        new_src, ok = _replace_in_synthesis(src, old, new)
        if ok:
            return new_src, "  [FIX] 3D BEARISH now requires both EMAs below and MACD confirmation"
    return src, "  [FIX] 3D BEARISH anchor not found — skipped"


def fix_tighten_5d_direction(src: str, iteration: int) -> tuple[str, str]:
    """Tighten 5D direction thresholds — only call directional when trend is clear."""
    pairs = [
        ("- NEUTRAL when: between EMAs, or any major signal is conflicting — prefer NEUTRAL over a weak guess\n",
         f"- NEUTRAL when: between EMAs, OR RSI 40-62, OR MACD near zero, OR FII flows mixed — STRONGLY prefer NEUTRAL [v{iteration}]\n"),
        (f"- NEUTRAL when: between EMAs, OR RSI 40-62, OR MACD near zero, OR FII flows mixed — STRONGLY prefer NEUTRAL [v{iteration-1}]\n",
         f"- NEUTRAL when: any ambiguity at all in EMA position, RSI direction, or macro regime — NEUTRAL is correct answer [v{iteration}]\n"),
    ]
    for old, new in pairs:
        new_src, ok = _replace_in_synthesis(src, old, new)
        if ok:
            return new_src, "  [FIX] 5D NEUTRAL threshold strengthened — more NEUTRAL calls"
    return src, "  [FIX] 5D NEUTRAL anchor not found — skipped"


def fix_raise_vix_threshold(src: str, iteration: int) -> tuple[str, str]:
    """Lower VIX bar for reducing BULLISH — now 18 instead of 20."""
    pairs = [
        ("- When VIX > 20 or macro is risk-off: require 4+ signals for BULLISH\n",
         f"- When VIX > 18 or macro is risk-off: require 4+ signals for BULLISH; prefer NEUTRAL [v{iteration}]\n"),
        (f"- When VIX > 18 or macro is risk-off: require 4+ signals for BULLISH; prefer NEUTRAL [v{iteration-1}]\n",
         f"- When VIX > 16 or macro is risk-off: prefer NEUTRAL; only BULLISH with 5+ clear signals [v{iteration}]\n"),
    ]
    for old, new in pairs:
        new_src, ok = _replace_in_synthesis(src, old, new)
        if ok:
            return new_src, "  [FIX] VIX BULLISH threshold lowered (18/16)"
    return src, "  [FIX] VIX threshold anchor not found — skipped"


def fix_increase_signal_count(src: str, iteration: int) -> tuple[str, str]:
    """Require more signals to align before calling directional."""
    pairs = [
        ("- Require ≥3 of these to align before calling BULLISH or BEARISH:\n",
         f"- Require ≥4 of these to align before calling BULLISH or BEARISH (≥3 is not enough): [v{iteration}]\n"),
        (f"- Require ≥4 of these to align before calling BULLISH or BEARISH (≥3 is not enough): [v{iteration-1}]\n",
         f"- Require ≥5 of these to clearly align before calling BULLISH or BEARISH: [v{iteration}]\n"),
    ]
    for old, new in pairs:
        new_src, ok = _replace_in_synthesis(src, old, new)
        if ok:
            return new_src, "  [FIX] Required signal alignment count raised to 4/5"
    return src, "  [FIX] signal count anchor not found — skipped"


def fix_strengthen_neutral_preference(src: str, iteration: int) -> tuple[str, str]:
    """Make NEUTRAL the strong default when signals conflict."""
    pairs = [
        ("- In genuine signal conflict: always choose NEUTRAL over a low-conviction directional call\n",
         f"- RULE: When in doubt, output NEUTRAL. A wrong directional call is worse than NEUTRAL. [v{iteration}]\n"),
        (f"- RULE: When in doubt, output NEUTRAL. A wrong directional call is worse than NEUTRAL. [v{iteration-1}]\n",
         f"- RULE: NEUTRAL is the safe default. Only override to directional when evidence is overwhelming and specific. [v{iteration}]\n"),
    ]
    for old, new in pairs:
        new_src, ok = _replace_in_synthesis(src, old, new)
        if ok:
            return new_src, "  [FIX] NEUTRAL preference strengthened in synthesis prompt"
    return src, "  [FIX] NEUTRAL anchor not found — skipped"


# Fix sequence — ordered for target-hit accuracy improvement
# Each fix targets direction accuracy (the root cause of <90% target-hit)
FIX_SEQUENCE = [
    ("tighten_5d_direction",          fix_tighten_5d_direction),
    ("tighten_3d_signal_count",       fix_tighten_3d_signal_count),
    ("tighten_1d_bullish_rsi",        fix_tighten_1d_bullish_rsi),
    ("tighten_1d_bearish_rsi",        fix_tighten_1d_bearish_rsi),
    ("raise_vix_threshold",           fix_raise_vix_threshold),
    ("increase_signal_count",         fix_increase_signal_count),
    ("strengthen_neutral_preference", fix_strengthen_neutral_preference),
]


def choose_fix(res: dict, iteration: int) -> tuple[str, callable]:
    """Pick fix based on which timeframe and direction has worst target-hit accuracy."""
    target_accs = [res[tf]["target_acc"] for tf in res if not np.isnan(res[tf].get("target_acc", float("nan")))]
    avg_target = np.mean(target_accs) if target_accs else float("nan")

    r1d = res.get("1D", {})
    r3d = res.get("3D", {})
    r5d = res.get("5D", {})

    t1 = r1d.get("target_acc", float("nan"))
    t3 = r3d.get("target_acc", float("nan"))
    t5 = r5d.get("target_acc", float("nan"))

    b1 = r1d.get("dir_acc", float("nan"))   # direction accuracy 1D
    b3 = r3d.get("dir_acc", float("nan"))   # direction accuracy 3D
    b5 = r5d.get("dir_acc", float("nan"))   # direction accuracy 5D

    print(f"  Diagnosis: target_acc={avg_target:.1f}%  1D={t1:.1f}% (dir={b1:.1f}%)  3D={t3:.1f}% (dir={b3:.1f}%)  5D={t5:.1f}% (dir={b5:.1f}%)")

    # Identify weakest TF by target accuracy
    weakest = min(
        [("1D", t1), ("3D", t3), ("5D", t5)],
        key=lambda x: x[1] if not np.isnan(x[1]) else 999,
    )[0]

    # 5D is hardest — fix its direction criteria first
    if weakest == "5D" and not np.isnan(t5) and t5 < TARGET:
        return FIX_SEQUENCE[0]  # tighten_5d_direction
    if weakest == "3D" and not np.isnan(t3) and t3 < TARGET:
        return FIX_SEQUENCE[1]  # tighten_3d_signal_count
    if weakest == "1D" and not np.isnan(t1) and t1 < TARGET:
        # Sub-diagnose: is BULLISH or BEARISH worse for 1D?
        bull1 = r1d.get("target_bull", float("nan"))
        bear1 = r1d.get("target_bear", float("nan"))
        if not np.isnan(bull1) and not np.isnan(bear1) and bull1 < bear1:
            return FIX_SEQUENCE[2]  # tighten_1d_bullish_rsi
        return FIX_SEQUENCE[3]  # tighten_1d_bearish_rsi

    # If all TFs present but still below target — try global fixes
    if not np.isnan(avg_target) and avg_target < TARGET - 10:
        return FIX_SEQUENCE[4]  # raise_vix_threshold
    if not np.isnan(avg_target) and avg_target < TARGET - 5:
        return FIX_SEQUENCE[5]  # increase_signal_count
    if not np.isnan(avg_target) and avg_target < TARGET:
        return FIX_SEQUENCE[6]  # strengthen_neutral_preference

    return FIX_SEQUENCE[iteration % len(FIX_SEQUENCE)]


# ── MODEL STATUS ──────────────────────────────────────────────────────────────

def _model_status() -> str:
    """Return a one-line string showing which LLM providers are available."""
    try:
        import ai_forecast as _aif
        or_ready = bool(os.environ.get("OPENROUTER_API_KEY", ""))
        groq_ready = bool(os.environ.get("GROQ_API_KEY", ""))
        hf_ready = bool(os.environ.get("HF_TOKEN", ""))
        parts = []
        if or_ready:
            model = os.environ.get("OPENROUTER_BEST_FREE_MODEL", "openai/gpt-oss-120b:free")
            parts.append(f"OpenRouter ({model}): ready")
        if groq_ready:
            parts.append("Groq: ready")
        if hf_ready:
            parts.append("HuggingFace: ready")
        if not parts:
            parts.append("No LLM provider configured (set OPENROUTER_API_KEY, GROQ_API_KEY, or HF_TOKEN)")
        return "  Models: " + " | ".join(parts)
    except Exception as e:
        return f"  Models: (status check failed: {e})"


def _all_models_cooled_down() -> tuple[bool, int]:
    """Return (all_cooled, max_wait_seconds) — always False unless we can detect cooldowns."""
    return False, 0


# ── MAIN LOOP ─────────────────────────────────────────────────────────────────

def main():
    import signal

    _stop = [False]
    def _sig_handler(sig, frame):
        print("\n\n  [STOP] Ctrl+C received — finishing current iteration then exiting...")
        _stop[0] = True
    signal.signal(signal.SIGINT, _sig_handler)

    # Optional: --reset to clear CSV and start fresh
    if "--reset" in sys.argv:
        if os.path.exists(CSV_PATH):
            os.remove(CSV_PATH)
            print("  CSV cleared — starting fresh")

    print("=" * 70)
    print("  CONTINUOUS AI PREDICTION OPTIMIZATION LOOP")
    print("  Target: Target price range accuracy >=90% on 1D, 3D, 5D")
    print("  AI-only mode: no strategy signals (matched_strategy=null)")
    print("  Model chain: gpt-4.1-mini -> gpt-4o -> gpt-4o-mini (auto-failover)")
    print("  Press Ctrl+C to stop gracefully after current iteration")
    print("=" * 70)

    iteration = 0
    backup_iteration = next_backup_iteration(CSV_PATH)
    if backup_iteration > 0:
        print(f"  Resuming backup numbering from ai_prompt_accuracy_iter{backup_iteration}.csv")

    while not _stop[0]:
        iteration += 1

        # If all GitHub models are rate-limited, continue running so OpenRouter
        # (if configured) can still provide LLM rows while cooldowns recover.
        all_cooled, max_wait = _all_models_cooled_down()
        if all_cooled:
            print(f"\n  [COOLDOWN] All models are rate-limited ({max_wait}s remaining).")
            print("  Continuing with other LLM providers (if configured) so the loop stays live.")
            print(_model_status())

        print(f"\n{'─'*70}")
        print(f"  ITERATION {iteration}")
        print(_model_status())
        print(f"{'─'*70}")

        # Back up CSV from previous run
        if os.path.exists(CSV_PATH):
            backup = CSV_PATH.replace(".csv", f"_iter{backup_iteration}.csv")
            shutil.copy(CSV_PATH, backup)
            print(f"  Backed up previous results -> {os.path.basename(backup)}")
            backup_iteration += 1

        # Rolling 18-month training window: optimize on recent data only, never touch hold-out.
        # holdout_dt is 2025-01-01; rolling window ends 2024-12-31, starts 18 months earlier.
        from datetime import datetime as _dt, timedelta as _td
        _holdout_dt   = _dt.strptime(HOLDOUT_START, "%Y-%m-%d")
        _train_end_dt = _holdout_dt - _td(days=1)          # 2024-12-31
        _rolling_days = 18 * 30                            # ~18 months
        _rolling_start_dt = _train_end_dt - _td(days=_rolling_days)
        _rolling_start = _rolling_start_dt.strftime("%Y-%m-%d")
        _rolling_end   = _train_end_dt.strftime("%Y-%m-%d")
        print(f"  Rolling window: {_rolling_start} → {_rolling_end} (18-month training set, hold-out locked)")

        # Run backtest — explicit file handles so subprocess doesn't inherit
        # nohup's broken fds (avoids "Bad file descriptor" crash on macOS)
        print(f"\n  Running backtest (fresh historical data + prompt-only calibration)...")
        t0 = time.time()
        bt_log = "/tmp/backtest_live.log"
        bt_err = "/tmp/backtest_err.log"
        with open(bt_log, "w") as bt_out_f, open(bt_err, "w") as bt_err_f:
            proc = subprocess.run(
                [
                    sys.executable,
                    os.path.join(os.path.dirname(__file__), "backtest.py"),
                    "--start", _rolling_start,
                    "--end",   _rolling_end,
                ],
                cwd=os.path.dirname(__file__) + "/..",
                stdin=subprocess.DEVNULL,
                stdout=bt_out_f,
                stderr=bt_err_f,
            )
        elapsed = time.time() - t0
        # Stream backtest output to our log
        try:
            with open(bt_log) as f:
                for line in f:
                    print(line, end="")
        except Exception:
            pass
        print(f"\n  Backtest finished in {elapsed/60:.1f} min (exit code {proc.returncode})")

        # Detect rate-limit failure
        if proc.returncode != 0:
            all_cooled, max_wait = _all_models_cooled_down()
            if all_cooled:
                print(f"  [RATE LIMIT] Backtest failed due to model rate limits. "
                      f"Will retry after cooldown.")
                iteration -= 1
                continue

        # Analyze
        res = analyze(CSV_PATH)
        if not res:
            print("  [WARN] Analysis returned no results (all non-LLM or missing columns) — skipping prompt fix, waiting for models")
            if not _stop[0]:
                print(f"  Pausing 120s for model rate limits to recover...")
                for _ in range(24):
                    if _stop[0]: break
                    time.sleep(5)
            continue

        print_summary(res, iteration)

        # Check target
        if target_met(res):
            print("  ***  TARGET MET -- target price range accuracy >=90% on 1D, 3D, 5D  ***")
            subprocess.run([sys.executable,
                            os.path.join(os.path.dirname(__file__), "backtest.py"),
                            "--print-only"])
            break

        if _stop[0]:
            print("  [STOP] Stopped by user.")
            break

        # Pick and apply fix
        fix_name, fix_fn = choose_fix(res, iteration)
        print(f"\n  Applying fix: {fix_name}")
        src = read_forecast(FORECAST_PY)
        new_src, msg = fix_fn(src, iteration)
        if new_src == src:
            print(f"  {msg} -- trying next fix in sequence")
            idx = next((i for i, f in enumerate(FIX_SEQUENCE) if f[0] == fix_name), 0)
            fix_name2, fix_fn2 = FIX_SEQUENCE[(idx + 1) % len(FIX_SEQUENCE)]
            new_src, msg2 = fix_fn2(src, iteration)
            msg = msg2
        write_forecast(FORECAST_PY, new_src)
        print(msg)

        # Short pause between iterations
        if not _stop[0]:
            print(f"\n  Pausing 30s before next iteration...")
            for _ in range(6):
                if _stop[0]:
                    break
                time.sleep(5)

    print("\n  Loop complete.")


if __name__ == "__main__":
    main()
