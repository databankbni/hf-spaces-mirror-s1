#!/usr/bin/env python3
"""
Run backtest A/B comparison for two predictor labels and print side-by-side accuracy.

This script executes research/backtest.py twice on the exact same test set and cache,
while overriding source metadata via environment variables:
- AI_FORECAST_SOURCE_PROVIDER
- AI_FORECAST_SOURCE_MODEL
- AI_FORECAST_SOURCE_PREFIX

Example:
  python research/compare_predictors.py \
    --a-provider openrouter --a-model openai/gpt-oss-120b:free \
    --b-provider groq --b-model llama-3.3-70b-versatile \
    --use-cache
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
BACKTEST = RESEARCH / "backtest.py"


def _safe_label(provider: str, model: str) -> str:
    return f"{provider}_{model}".replace("/", "_").replace(":", "_").replace(" ", "_")


def _run_backtest(
    provider: str,
    model: str,
    use_cache: bool,
    refresh_cache: bool,
    cache_dir: str,
    out_csv: Path,
    limit_work_items: int,
) -> None:
    env = os.environ.copy()
    env["AI_FORECAST_SOURCE_PROVIDER"] = provider
    env["AI_FORECAST_SOURCE_MODEL"] = model
    env["AI_FORECAST_SOURCE_PREFIX"] = "ai_forecast"

    cmd = [
        sys.executable,
        str(BACKTEST),
        "--csv-out",
        str(out_csv),
        "--cache-dir",
        cache_dir,
    ]
    if limit_work_items and limit_work_items > 0:
        cmd.extend(["--limit-work-items", str(limit_work_items)])
    if use_cache:
        cmd.append("--use-cache")
    if refresh_cache:
        cmd.append("--refresh-cache")

    print(f"\n=== Running backtest for {provider}:{model} ===")
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"Backtest failed for {provider}:{model} (exit {proc.returncode})")


def _metrics(csv_path: Path) -> dict:
    df = pd.read_csv(csv_path)
    if df.empty:
        return {"rows": 0, "overall_target_hit": 0.0, "tf": {}}

    out = {
        "rows": int(len(df)),
        "overall_target_hit": float(df["target_hit_for_tf"].mean() * 100.0),
        "tf": {},
    }
    for tf in ["1D", "3D", "5D"]:
        sub = df[df["timeframe"] == tf]
        out["tf"][tf] = {
            "n": int(len(sub)),
            "target_hit": float(sub["target_hit_for_tf"].mean() * 100.0) if len(sub) else 0.0,
            "direction_hit": float(sub["intraday_hit_for_tf"].mean() * 100.0) if len(sub) else 0.0,
        }
    return out


def _print_compare(a_label: str, a: dict, b_label: str, b: dict) -> None:
    print("\n=== Predictor Comparison ===")
    print(f"A: {a_label}")
    print(f"B: {b_label}")
    print("")
    print(f"Overall target-hit: {a_label}={a['overall_target_hit']:.2f}%  |  {b_label}={b['overall_target_hit']:.2f}%")
    print(f"Rows: {a_label}={a['rows']}  |  {b_label}={b['rows']}")
    print("")
    print("Timeframe target-hit / direction-hit")
    for tf in ["1D", "3D", "5D"]:
        atf = a["tf"][tf]
        btf = b["tf"][tf]
        print(
            f"  {tf}: "
            f"{a_label}={atf['target_hit']:.2f}%/{atf['direction_hit']:.2f}% (n={atf['n']})  |  "
            f"{b_label}={btf['target_hit']:.2f}%/{btf['direction_hit']:.2f}% (n={btf['n']})"
        )

    winner = a_label if a["overall_target_hit"] > b["overall_target_hit"] else b_label
    if abs(a["overall_target_hit"] - b["overall_target_hit"]) < 1e-9:
        winner = "TIE"
    print("")
    print(f"Winner (overall target-hit): {winner}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--a-provider", default="openrouter")
    p.add_argument("--a-model", default="openai/gpt-oss-120b:free")
    p.add_argument("--b-provider", default="groq")
    p.add_argument("--b-model", default="llama-3.3-70b-versatile")
    p.add_argument("--use-cache", action="store_true")
    p.add_argument("--refresh-cache", action="store_true")
    p.add_argument("--cache-dir", default=str(RESEARCH / "cache"))
    p.add_argument("--limit-work-items", type=int, default=0, help="Run only first N work items per model")
    args = p.parse_args()

    a_label = f"{args.a_provider}:{args.a_model}"
    b_label = f"{args.b_provider}:{args.b_model}"

    out_a = RESEARCH / f"ai_prompt_accuracy_{_safe_label(args.a_provider, args.a_model)}.csv"
    out_b = RESEARCH / f"ai_prompt_accuracy_{_safe_label(args.b_provider, args.b_model)}.csv"

    _run_backtest(
        args.a_provider,
        args.a_model,
        args.use_cache,
        args.refresh_cache,
        args.cache_dir,
        out_a,
        args.limit_work_items,
    )
    _run_backtest(
        args.b_provider,
        args.b_model,
        args.use_cache,
        args.refresh_cache,
        args.cache_dir,
        out_b,
        args.limit_work_items,
    )

    a = _metrics(out_a)
    b = _metrics(out_b)
    _print_compare(a_label, a, b_label, b)
