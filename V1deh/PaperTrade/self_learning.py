#!/usr/bin/env python3
"""
self_learning.py — Analyze prediction validation history and generate calibration notes
that get injected into the AI synthesis prompt so the model learns from its own failures.

Public API:
  analyze_and_update(days=30) -> dict   # compute stats, write learnings.json, return summary
  get_learning_context() -> str         # formatted block for synthesis prompt injection
"""

import json
import os
import logging
import re
from typing import Optional


def _data_dir() -> str:
    """Return persistent data directory. Uses /data on HF Spaces, else project root."""
    hf_data = "/data"
    if os.path.isdir(hf_data) and os.access(hf_data, os.W_OK):
        return hf_data
    return os.path.dirname(os.path.abspath(__file__))


_MIN_SAMPLES = 10  # require at least this many validated rows before injecting learnings
_MAX_STORED_RECORDS = 5000  # slim records kept in learnings.json (preserves history post-prune)

# The LLM-driven calibration analysis ("Improve AI") is expensive and its conclusions barely
# move day-to-day, so it is throttled: the LLM notes refresh at most once every N days. The
# cheap arithmetic target-reach notes + hit/miss buckets STILL refresh on every validation, so
# learnings.json (the file fed into the AI synthesis prompt) stays current. The manual
# "🧠 Improve AI" button forces an immediate LLM refresh (force_llm=True). Set the interval to
# 0 to run the LLM every time (old behavior).
_LEARN_LLM_INTERVAL_DAYS = int(os.getenv("SELF_LEARN_LLM_INTERVAL_DAYS", "7"))


def _days_since(date_str: Optional[str]) -> Optional[int]:
    """Whole days between an IST 'YYYY-MM-DD' stamp and today (IST). None if unparseable."""
    if not date_str:
        return None
    try:
        from datetime import datetime
        d = datetime.strptime(str(date_str)[:10], "%Y-%m-%d").date()
        today = datetime.strptime(_today_ist(), "%Y-%m-%d").date()
        return (today - d).days
    except Exception:
        return None


def _slim_record(r: dict) -> dict:
    """Slimmed validated record kept in learnings.json for the history tab (survives DB
    pruning). Includes snapshot_source so learnings can be split into AI vs ML."""
    return {
        "id": r.get("id"),
        "ticker": r.get("ticker"),
        "timeframe": r.get("timeframe"),
        "direction": r.get("direction"),
        "confidence": r.get("confidence"),
        "target_price_lo": r.get("target_price_lo"),
        "target_price_hi": r.get("target_price_hi"),
        "predicted_return_lo": r.get("predicted_return_lo"),
        "predicted_return_hi": r.get("predicted_return_hi"),
        "current_price": r.get("current_price"),
        "actual_price_at_validation": r.get("actual_price_at_validation"),
        "actual_return_at_validation": r.get("actual_return_at_validation"),
        "window_high": r.get("window_high"),
        "window_low": r.get("window_low"),
        "validation_result": r.get("validation_result"),
        "snapshot_source": r.get("snapshot_source"),
        "created_at": r.get("created_at"),
        "validated_at": r.get("validated_at"),
        "validation_target_date": r.get("validation_target_date"),
    }


def _analyze_bucket_set(new_validated: list, existing: dict, days: int, use_llm: bool = True,
                        llm_allowed: bool = True) -> dict:
    """Compute calibration stats (buckets, confidence, notes, records) for ONE prediction
    source (AI or ML).

    Aggregates are rebuilt from a DEDUPLICATED union of (a) the current DB validated rows
    and (b) previously-stored slim records that are no longer in the DB (pruned history).
    Dedup is by snapshot id, so a row present in BOTH the DB and the stored history is counted
    exactly once — the analysis is idempotent and safe to re-run without pruning in between
    (the old approach seeded historical totals AND re-counted un-pruned DB rows, double-counting).
    """
    existing = existing or {}
    existing_records: list = existing.get("records", [])

    # Union of records: current DB rows first, then stored records whose id isn't in the DB set.
    new_ids: set = {r.get("id") for r in new_validated if r.get("id") is not None}
    combined_src: list = list(new_validated)
    for er in existing_records:
        if er.get("id") not in new_ids:
            combined_src.append(er)

    merged_buckets: dict = {}
    merged_conf: dict = {}
    total = 0
    total_hits = 0
    all_records: list = []
    for r in combined_src:
        result = r.get("validation_result")
        if result not in ("HIT", "MISS"):
            continue
        direction = (r.get("direction") or "").upper()
        if direction in ("N/A", "NO TRADE", "NEUTRAL", ""):
            continue
        timeframe = (r.get("timeframe") or "1D").upper()
        confidence = (r.get("confidence") or "LOW").upper()
        hit = result == "HIT"

        key = f"{direction}_{timeframe}"
        b = merged_buckets.setdefault(
            key, {"hits": 0, "total": 0, "direction": direction, "timeframe": timeframe}
        )
        b["hits"] += int(hit)
        b["total"] += 1

        c = merged_conf.setdefault(confidence, {"hits": 0, "total": 0})
        c["hits"] += int(hit)
        c["total"] += 1

        total += 1
        total_hits += int(hit)
        all_records.append(_slim_record(r))

    all_records.sort(key=lambda x: x.get("validated_at") or "", reverse=True)
    all_records = all_records[:_MAX_STORED_RECORDS]

    new_in_this_run = sum(
        1 for r in new_validated
        if r.get("id") is not None and r.get("id") not in {er.get("id") for er in existing_records}
    )

    if total < _MIN_SAMPLES:
        return {
            "status": "insufficient_data",
            "total_validated": total,
            "new_in_this_run": new_in_this_run,
            "min_required": _MIN_SAMPLES,
            "calibration_notes": [],
            "notes_base": (existing or {}).get("notes_base", []),
            "notes_updated_at": (existing or {}).get("notes_updated_at"),
            "buckets": {},
            "confidence_stats": {},
            "records": all_records,
        }

    bucket_stats = {}
    for key, b in sorted(merged_buckets.items(), key=lambda x: x[1]["total"], reverse=True):
        if b["total"] < 5:
            continue
        hit_rate = b["hits"] / b["total"]
        bucket_stats[key] = {
            "hits": b["hits"],
            "total": b["total"],
            "hit_rate": round(hit_rate, 3),
            "miss_rate": round(1 - hit_rate, 3),
        }

    overall_accuracy = round(total_hits / total, 3) if total else 0

    prev_notes_base = (existing or {}).get("notes_base")
    prev_notes_at = (existing or {}).get("notes_updated_at")
    notes_updated_at = _today_ist()
    if use_llm:
        if llm_allowed or not prev_notes_base:
            try:
                notes_base = _llm_calibration_notes(bucket_stats, merged_conf, all_records, overall_accuracy)
            except Exception as _le:
                logging.warning("LLM calibration failed (%s) — using arithmetic fallback", _le)
                notes_base = _arithmetic_calibration_notes(bucket_stats, merged_conf)
        else:
            # Throttled: reuse the last LLM notes (their conclusions barely move day-to-day).
            # The cheap target-reach notes below still refresh, so learnings.json stays actionable.
            notes_base = list(prev_notes_base)
            notes_updated_at = prev_notes_at or notes_updated_at
    else:
        # ML is a trained model (no prompt to inject into), so its notes stay descriptive /
        # arithmetic — same WARN/CAUTION/OK hit-miss blocks, no LLM cost.
        notes_base = _arithmetic_calibration_notes(bucket_stats, merged_conf)

    # Prepend target-reach diagnostics (predicted high/low/mid vs the stock's ACTUAL high/low)
    # so the panel explains WHY a target was missed — e.g. a high target price never touched.
    # These are arithmetic + cheap, so they ALWAYS refresh (even on LLM-throttled runs), keeping
    # the "pull the target in" guidance current in the JSON fed to the AI.
    target_notes = _target_reach_notes(all_records)
    calibration_notes = target_notes + notes_base

    return {
        "total_validated": total,
        "new_in_this_run": new_in_this_run,
        "overall_accuracy": overall_accuracy,
        "buckets": bucket_stats,
        "calibration_notes": calibration_notes,
        "notes_base": notes_base,
        "notes_updated_at": notes_updated_at,
        "confidence_stats": {
            k: {"hits": v["hits"], "total": v["total"], "hit_rate": round(v["hits"] / v["total"], 3)}
            for k, v in merged_conf.items() if v["total"] >= 5
        },
        "records": all_records,
    }


def analyze_and_update(days: Optional[int] = None, force_llm: bool = False) -> dict:
    """
    Query prediction_snapshots for validated results and write learnings.json.

    `days=None` (the default) analyzes the ENTIRE validated history — every prediction
    matters, so there is no rolling window. Pass a positive int only to restrict the window.

    `force_llm=True` bypasses the LLM-refresh throttle and re-runs the (expensive) LLM
    calibration immediately — used by the manual "🧠 Improve AI" button. Automatic callers
    (post-validation + scheduler) leave it False, so the LLM notes refresh at most once every
    `_LEARN_LLM_INTERVAL_DAYS` days while the cheap target/bucket stats still update each run.

    AI and ML predictions are analyzed SEPARATELY (by snapshot_source) so each gets its own
    hit/miss buckets, confidence stats, and calibration notes — the panel shows both. The
    top-level fields mirror the AI block for backward compatibility: get_learning_context()
    injects AI-only learnings into the AI synthesis prompt (ML data no longer pollutes it).
    """
    import database as db

    # Pull the FULL history (days=None ⇒ no time window). get_prediction_snapshots caps at
    # `limit`, so request a high cap to capture every validated row.
    rows = db.get_prediction_snapshots(days=days, limit=100000)
    validated = [
        r for r in rows
        if r.get("validation_status") == "VALIDATED"
        and r.get("validation_result") in ("HIT", "MISS")
        and r.get("direction", "").upper() not in ("N/A", "NO TRADE", "NEUTRAL", "")
    ]
    ai_new = [r for r in validated if (r.get("snapshot_source") or "").lower() != "ml"]
    ml_new = [r for r in validated if (r.get("snapshot_source") or "").lower() == "ml"]

    existing = _read() or {}
    # New format stores per-source blocks under "ai"/"ml". Old (flat) format is treated as the
    # AI seed — records carry snapshot_source, so subsequent runs self-correct the split.
    ai_existing = existing.get("ai") if "ai" in existing else existing
    ml_existing = existing.get("ml", {})

    # Throttle gate: allow the LLM to run when forced, when the interval is disabled (0), when
    # no prior LLM notes exist, or when enough days have elapsed since the last LLM refresh.
    prev_llm_at = (ai_existing or {}).get("notes_updated_at")
    _elapsed = _days_since(prev_llm_at)
    llm_allowed = bool(
        force_llm
        or _LEARN_LLM_INTERVAL_DAYS <= 0
        or prev_llm_at is None
        or _elapsed is None
        or _elapsed >= _LEARN_LLM_INTERVAL_DAYS
    )

    ai_block = _analyze_bucket_set(ai_new, ai_existing or {}, days, use_llm=True, llm_allowed=llm_allowed)
    ml_block = _analyze_bucket_set(ml_new, ml_existing or {}, days, use_llm=False)

    # Combined records (both sources) for the validation history tab — dedup by id + cap.
    seen: set = set()
    combined: list = []
    for rec in (ai_block.get("records", []) + ml_block.get("records", [])):
        rid = rec.get("id")
        if rid is not None and rid in seen:
            continue
        seen.add(rid)
        combined.append(rec)
    combined.sort(key=lambda x: x.get("validated_at") or "", reverse=True)
    combined = combined[:_MAX_STORED_RECORDS]

    result = {
        "updated_at": _today_ist(),
        "days": days,
        **ai_block,           # top-level == AI block (backward compat)
        "records": combined,  # ...but history tab needs both sources
        "ai": ai_block,
        "ml": ml_block,
    }
    _write(result)
    logging.info(
        "Self-learning updated: AI N=%d (%.0f%%, +%d), ML N=%d (%.0f%%, +%d) [LLM %s]",
        ai_block.get("total_validated", 0), ai_block.get("overall_accuracy", 0) * 100, len(ai_new),
        ml_block.get("total_validated", 0), ml_block.get("overall_accuracy", 0) * 100, len(ml_new),
        "refreshed" if llm_allowed else f"reused (next in {_LEARN_LLM_INTERVAL_DAYS - (_elapsed or 0)}d)",
    )
    return result


_TF_TOKENS = ("INTRADAY", "1D", "3D", "5D")


def _note_matches_tf(note: str, tf_label: str) -> bool:
    """True if `note` has no TF token (a TF-agnostic note, e.g. confidence calibration) or
    its TF token equals `tf_label` — prevents a 3D calibration note from being applied to an
    INTRADAY (or any other mismatched timeframe) synthesis call."""
    upper = note.upper()
    found = [t for t in _TF_TOKENS if re.search(rf"\b{t}\b", upper)]
    return (not found) or (tf_label in found)


def get_learning_context(tf_label: Optional[str] = None) -> str:
    """
    Return a formatted block for injection into the synthesis prompt.
    When `tf_label` is given, notes are filtered to that timeframe (plus TF-agnostic notes,
    e.g. confidence-level calibration) so a 3D lesson is never applied to an INTRADAY call —
    and the header N/accuracy are recomputed from that timeframe's own buckets when available.
    Returns empty string if learnings.json is missing, stale, or has too little data.
    """
    data = _read()
    if not data:
        return ""

    total = data.get("total_validated", 0)
    if total < _MIN_SAMPLES:
        return ""

    notes = data.get("calibration_notes", [])
    if not notes:
        return ""

    accuracy = data.get("overall_accuracy", 0)

    if tf_label:
        tf_u = tf_label.upper()
        notes = [n for n in notes if _note_matches_tf(n, tf_u)]
        if not notes:
            return ""
        buckets = data.get("buckets", {}) or {}
        tf_buckets = {k: v for k, v in buckets.items() if k.endswith(f"_{tf_u}")}
        tf_total = sum(v["total"] for v in tf_buckets.values())
        tf_hits = sum(v["hits"] for v in tf_buckets.values())
        if tf_total > 0:
            total = tf_total
            accuracy = tf_hits / tf_total

    days = data.get("days")
    updated = data.get("updated_at", "")
    window = f"last {days} days" if days else "all history"

    lines = [
        f"LEARNING FROM RECENT PREDICTIONS ({window}, N={total}, accuracy={accuracy:.0%}, updated {updated}):"
    ]
    for note in notes:
        lines.append(f"- {note}")

    return "\n".join(lines)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _learnings_path() -> str:
    return os.path.join(_data_dir(), "learnings.json")


def _arithmetic_calibration_notes(bucket_stats: dict, merged_conf: dict) -> list:
    """Fallback: threshold-based calibration notes (no LLM required)."""
    notes = []
    for key, s in bucket_stats.items():
        parts = key.split("_", 1)
        direction = parts[0]
        timeframe = parts[1] if len(parts) > 1 else "1D"
        n = s["total"]
        miss_rate = s["miss_rate"]
        hit_rate = s["hit_rate"]
        if miss_rate > 0.25:
            notes.append(
                f"WARN {direction} {timeframe}: {miss_rate:.0%} miss rate (N={n}) — "
                f"only call {direction} {timeframe} when a strong trigger fires"
            )
        elif miss_rate > 0.15:
            notes.append(
                f"CAUTION {direction} {timeframe}: {miss_rate:.0%} miss rate (N={n}) — "
                f"require at least 2 confirming signals before calling {direction}"
            )
        elif hit_rate >= 0.90:
            notes.append(
                f"OK {direction} {timeframe}: {hit_rate:.0%} hit rate (N={n}) — "
                f"triggers are well-calibrated, trust them"
            )
    for conf in ("HIGH", "MEDIUM", "LOW"):
        cc = merged_conf.get(conf, {})
        if cc.get("total", 0) < 5:
            continue
        hr = cc["hits"] / cc["total"]
        if conf == "HIGH" and hr < 0.85:
            notes.append(
                f"WARN HIGH confidence calls are only {hr:.0%} accurate (N={cc['total']}) — "
                f"be stricter before assigning HIGH confidence"
            )
    return notes


def _target_reach_notes(records: list) -> list:
    """Compare the predicted target band (high/low/mid) against the stock's ACTUAL price
    window (window_high/window_low) to explain WHY a prediction missed — e.g. a high target
    the price never reached. Groups by direction+timeframe and reports the reach rate plus
    the average shortfall, so the panel says exactly how far off the target was. Works for
    both AI and ML records (both carry window_high/low + target band)."""
    from collections import defaultdict

    groups: dict = defaultdict(list)
    for r in records:
        direction = (r.get("direction") or "").upper()
        tf = (r.get("timeframe") or "1D").upper()
        if direction not in ("BULLISH", "BEARISH", "SLIGHTLY BULLISH", "SLIGHTLY BEARISH"):
            continue
        entry = r.get("current_price") or 0
        wh = r.get("window_high")
        wl = r.get("window_low")
        t_lo = r.get("target_price_lo")
        t_hi = r.get("target_price_hi")
        if not entry or wh is None or wl is None or t_lo is None or t_hi is None:
            continue
        groups[(direction, tf)].append((entry, wh, wl, t_lo, t_hi))

    notes = []
    for (direction, tf), rows in sorted(groups.items(), key=lambda x: -len(x[1])):
        n = len(rows)
        if n < 5:
            continue
        bullish = "BULLISH" in direction
        reached = 0
        shortfalls = []          # how far short of the target the price stopped (% of entry)
        pred_target_pcts = []    # predicted best-case target as % move
        actual_extreme_pcts = [] # actual best-case reached as % move
        mid_reached = 0          # did price at least touch the midpoint?
        for entry, wh, wl, t_lo, t_hi in rows:
            mid = (t_lo + t_hi) / 2.0
            if bullish:
                pred_target_pcts.append((t_hi - entry) / entry * 100)
                actual_extreme_pcts.append((wh - entry) / entry * 100)
                if wh >= t_hi:
                    reached += 1
                else:
                    shortfalls.append((t_hi - wh) / entry * 100)
                if wh >= mid:
                    mid_reached += 1
            else:
                pred_target_pcts.append((t_lo - entry) / entry * 100)
                actual_extreme_pcts.append((wl - entry) / entry * 100)
                if wl <= t_lo:
                    reached += 1
                else:
                    shortfalls.append((wl - t_lo) / entry * 100)
                if wl <= mid:
                    mid_reached += 1

        reach_rate = reached / n
        mid_rate = mid_reached / n
        avg_pred = sum(pred_target_pcts) / n
        avg_actual = sum(actual_extreme_pcts) / n
        edge = "high" if bullish else "low"
        if reach_rate < 0.5 and shortfalls:
            avg_short = sum(shortfalls) / len(shortfalls)
            notes.append(
                f"MISS {direction} {tf}: {edge} target hit only {reach_rate:.0%} (N={n}) — "
                f"predicted {edge} avg {avg_pred:+.1f}% but price only reached {avg_actual:+.1f}% "
                f"(~{avg_short:.1f}% too far); midpoint touched {mid_rate:.0%} — pull the {edge} target in"
            )
        elif reach_rate >= 0.85:
            notes.append(
                f"OK {direction} {tf}: {edge} target hit {reach_rate:.0%} (N={n}) — "
                f"band well-placed (pred {avg_pred:+.1f}% vs reached {avg_actual:+.1f}%)"
            )
        elif mid_rate < 0.6:
            notes.append(
                f"CAUTION {direction} {tf}: midpoint hit only {mid_rate:.0%} (N={n}) — "
                f"predicted {edge} avg {avg_pred:+.1f}% vs actual {avg_actual:+.1f}%; narrow the band"
            )
    return notes


def _llm_calibration_notes(
    bucket_stats: dict,
    merged_conf: dict,
    records: list,
    overall_accuracy: float,
) -> list:
    """LLM-driven calibration: reasons over hit/miss patterns and near-misses."""
    from llm_client import make_chat_call

    # Build per-bucket hit-rate summary
    bucket_lines = []
    for key, s in bucket_stats.items():
        bucket_lines.append(
            f"  {key}: {s['hit_rate']:.0%} hit rate ({s['hits']}/{s['total']})"
        )

    # Recent 30 records for near-miss analysis
    recent = []
    for r in records[:30]:
        recent.append({
            "ticker": r.get("ticker"),
            "tf": r.get("timeframe"),
            "dir": r.get("direction"),
            "conf": r.get("confidence"),
            "result": r.get("validation_result"),
            "pred_lo": r.get("predicted_return_lo"),
            "pred_hi": r.get("predicted_return_hi"),
            "actual": r.get("actual_return_at_validation"),
            "win_hi": r.get("window_high"),
            "win_lo": r.get("window_low"),
        })

    conf_lines = []
    for conf in ("HIGH", "MEDIUM", "LOW"):
        cc = merged_conf.get(conf, {})
        if cc.get("total", 0) >= 5:
            hr = cc["hits"] / cc["total"]
            conf_lines.append(f"  {conf}: {hr:.0%} ({cc['hits']}/{cc['total']})")

    prompt = f"""You are a trading system calibration analyst. The system targets ≥85% hit rate.
Overall accuracy: {overall_accuracy:.0%}

Direction+timeframe hit rates (target ≥85%):
{chr(10).join(bucket_lines) if bucket_lines else "  (no buckets with N≥5 yet)"}

Confidence hit rates:
{chr(10).join(conf_lines) if conf_lines else "  (insufficient data)"}

Recent predictions (last 30):
{json.dumps(recent, indent=None)}

Tasks:
1. Flag any direction+timeframe bucket below 85% hit rate with WARN (below 75%) or CAUTION (75-84%).
2. Identify near-misses: records where the actual return was within 20% of the predicted range boundary.
3. Cross-tab: if HIGH-confidence calls underperform MEDIUM, flag it.
4. If the 10 most recent records trend worse than overall, add a RECENT_DRIFT warning.
5. For buckets at ≥90% hit rate, add an OK note to reinforce the pattern.

Respond ONLY with a JSON array of strings. Each string starts with WARN, CAUTION, OK, or RECENT_DRIFT.
Example: ["WARN BULLISH 1D: 30% miss rate (N=20) — tighten trigger requirements", "OK BEARISH 3D: 92% hit rate (N=15) — well calibrated"]
No markdown, no explanation, just the JSON array."""

    content, _, _ = make_chat_call(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=400,
        temperature=0.2,
        fast_fail_on_rate_limit=True,
        max_retries=2,
    )

    raw = content.strip()
    # Strip markdown fences if present
    import re
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    notes = json.loads(raw)
    if not isinstance(notes, list):
        raise ValueError(f"Expected list, got {type(notes)}")
    return [str(n) for n in notes if isinstance(n, str) and n.strip()]


def _write(data: dict) -> None:
    try:
        with open(_learnings_path(), "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logging.warning("Could not write learnings.json: %s", e)


def _read() -> Optional[dict]:
    try:
        with open(_learnings_path()) as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        logging.warning("Could not read learnings.json: %s", e)
        return None


def _today_ist() -> str:
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone.utc).astimezone(
        timezone(timedelta(hours=5, minutes=30))
    ).strftime("%Y-%m-%d")


if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else None
    result = analyze_and_update(days=days)
    print(json.dumps(result, indent=2))
    print("\n--- Prompt context ---")
    print(get_learning_context() or "(no context yet)")
