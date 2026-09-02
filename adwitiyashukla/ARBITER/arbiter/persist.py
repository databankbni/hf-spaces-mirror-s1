from __future__ import annotations

import glob
import json
import os
from typing import Dict, List, Optional

from .models import Action, Signal, StepRecord, TrialResult, Usage


def _usage(d: Optional[Dict]) -> Usage:
    d = d or {}
    return Usage(prompt_tokens=int(d.get("prompt_tokens", 0)),
                 completion_tokens=int(d.get("completion_tokens", 0)),
                 calls=int(d.get("calls", 0)), model=str(d.get("model", "")))


def _signal(d: Dict) -> Signal:
    return Signal(source=d.get("source", ""), kind=d.get("kind", ""), detail=d.get("detail", ""),
                  step=int(d.get("step", 0)), severity=d.get("severity", "info"),
                  evidence=d.get("evidence") or {})


def _step(d: Dict) -> StepRecord:
    action = None
    if d.get("action"):
        action = Action(name=d["action"].get("name", ""), args=d["action"].get("args") or {})
    return StepRecord(index=int(d.get("index", 0)), url=d.get("url", ""), action=action,
                      result=d.get("result", ""), element_count=int(d.get("element_count", 0)),
                      frames=list(d.get("frames") or []),
                      signals=[_signal(s) for s in d.get("signals") or []])


step_from_dict = _step
signal_from_dict = _signal


def load_trial(path: str) -> TrialResult:
    with open(path, "r", encoding="utf-8") as fh:
        d = json.load(fh)
    return TrialResult(
        bug_id=d["bug_id"], trial_index=int(d["trial_index"]),
        actor_verdict=d["actor_verdict"], actor_reason=d.get("actor_reason", ""),
        judge_verdict=d.get("judge_verdict", ""), judge_confidence=float(d.get("judge_confidence", 0.0)),
        judge_reason=d.get("judge_reason", ""), judge_evidence=list(d.get("judge_evidence") or []),
        outcome=d.get("outcome", ""), steps=[_step(s) for s in d.get("steps") or []],
        signals=[_signal(s) for s in d.get("signals") or []],
        actor_usage=_usage(d.get("actor_usage")), judge_usage=_usage(d.get("judge_usage")),
        duration_s=float(d.get("duration_s", 0.0)), evidence_dir=d.get("evidence_dir", ""),
        final_state=d.get("final_state", ""), error=d.get("error", ""))


def load_trials(evidence_dir: str, bug_id: str) -> List[TrialResult]:
    pattern = os.path.join(evidence_dir, bug_id, "t*", "trial.json")
    out = [load_trial(p) for p in sorted(glob.glob(pattern))]
    return sorted(out, key=lambda t: t.trial_index)
