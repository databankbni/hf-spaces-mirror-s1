#!/usr/bin/env python3
"""
Convert PersonalAssistantBench's recorded on-device trajectories (trajectory.jsonl per task)
into the platform rollout schema, scored with THIS env's rubric so the golden
runs and live RL runs share one verdict pipeline.

Usage:
    python scripts/convert_golden.py [path/to/PersonalAssistantBench/trajectories]

Writes data/golden/personalassistantbench_golden_rollouts.json:
    { environment, model, source, rollouts: [
        { rollout_id, task_id, task_description, terminal_pass, total_reward,
          episode_rewards: {facet: score}, num_turns,
          turns: [ {step, generated_text, tool_calls, step_reward} ] } ] }
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.reward import step_reward, terminal_reward  # noqa: E402
from server.tasks import get_task  # noqa: E402
from server.world import IOSWorld  # noqa: E402

DEFAULT_SRC = ROOT.parent / "PersonalAssistantBench" / "trajectories"
OUT = ROOT / "data" / "golden" / "personalassistantbench_golden_rollouts.json"


def load_events(path: Path) -> list[dict]:
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events


def convert_task(task_id: str, events: list[dict]) -> dict | None:
    task = get_task(task_id)
    if task is None:
        return None

    # Rebuild the run: tool calls, final answers, per-step rewards, and the
    # end-state (from the run's own verify_reminders re-read of the real store).
    tools_called: list[str] = []
    final_answers: list[str] = []
    turns: list[dict] = []
    verified_reminders: list[str] = []
    step_n = 0
    total = 0.0

    for e in events:
        ev = e.get("event")
        if ev == "function_call":
            name = e.get("name", "")
            step_n += 1
            tools_called.append(name)
            r, _ = step_reward(name, False, task.rubric.forbidden_tools)
            total += r
            turns.append({
                "step": step_n,
                "generated_text": "",
                "tool_calls": [{"name": name, "arguments": e.get("arguments", "{}")}],
                "step_reward": round(r, 4),
            })
        elif ev == "agent_done":
            final = e.get("final", "")
            final_answers.append(final)
            step_n += 1
            turns.append({
                "step": step_n,
                "generated_text": final,
                "tool_calls": [],
                "step_reward": 0.0,
            })
        elif ev == "verify_reminders":
            verified_reminders = e.get("titles", []) or []

    # Score with the env's terminal rubric against the verified real end-state.
    world = IOSWorld()
    world.reminders = list(verified_reminders)
    reward, details = terminal_reward(task, world, tools_called, final_answers, events)
    if turns:
        turns[-1]["step_reward"] = round(turns[-1]["step_reward"] + reward, 4)
    total += reward

    return {
        "rollout_id": f"golden_{task_id}",
        "task_id": task_id,
        "task_description": task.summary,
        "family": task.family,
        "label": "golden (Apple on-device Foundation Model ~3B, iOS 26.4 sim)",
        "terminal_pass": details["terminal_pass"],
        "total_reward": round(total, 4),
        "episode_rewards": details["episode_rewards"],
        "facet_applicable": details["facet_applicable"],
        "checks": {
            "required_checks": details.get("required_checks", {}),
            "restraint_checks": details.get("restraint_checks", {}),
            "state_checks": details.get("state_checks", {}),
            "answer_checks": details.get("answer_checks", {}),
        },
        "num_turns": len(turns),
        "turns": turns,
        "verify_reminders": details["verify_reminders"],
    }


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    rollouts = []
    for task_dir in sorted(src.iterdir()):
        jsonl = task_dir / "trajectory.jsonl"
        if not task_dir.is_dir() or not jsonl.exists():
            continue
        rollout = convert_task(task_dir.name, load_events(jsonl))
        if rollout:
            rollouts.append(rollout)
            mark = "PASS" if rollout["terminal_pass"] else "FAIL"
            print(f"  {mark:4}  {rollout['task_id']:24} reward={rollout['total_reward']}")

    out = {
        "environment": "PersonalAssistantBench",
        "model": "apple-on-device-foundation-model-3b-ios-26.4",
        "source": "PersonalAssistantBench recorded trajectories (iOS 26.4 simulator)",
        "max_turns": 16,
        "rollouts": rollouts,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    n_pass = sum(1 for r in rollouts if r["terminal_pass"])
    print(f"\nWrote {OUT} — {len(rollouts)} rollouts, {n_pass} PASS / {len(rollouts) - n_pass} FAIL")


if __name__ == "__main__":
    main()
