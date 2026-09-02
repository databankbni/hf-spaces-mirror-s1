from __future__ import annotations

import os
import time
from typing import List

from . import cost as cost_mod
from .benchmark import load_suite
from .config import RunConfig, key_for
from .judge import Judge
from .llm.base import QuotaExhausted, build_provider
from .models import BugResult, TrialResult, UNRESOLVED, dumps
from .persist import load_trials
from .trial import SuiteResult, combine

MISSING_STATE = ("(the final page state was not recorded during the original run; "
                 "judge from the actions, signals and screenshots)")


def rejudge(cfg: RunConfig, only_unresolved: bool = True) -> SuiteResult:
    specs = load_suite(cfg.bugs_dir, cfg.only)
    started = time.time()
    out = SuiteResult(config=dict(cfg.describe(), mode="rejudge"),
                      started_at=time.strftime("%Y-%m-%d %H:%M:%S"))
    provider = build_provider(cfg.effective_judge_provider, cfg.judge_model,
                              key_for(cfg.effective_judge_provider))
    if cfg.effective_judge_provider == "mock":
        provider.trace_dir = cfg.trace_dir
    elif cfg.record:
        from .llm.mock import RecordingProvider
        provider = RecordingProvider(provider, cfg.trace_dir)
    judge = Judge(provider)

    print("re-judging evidence in {0} with {1}".format(cfg.evidence_dir, cfg.judge_model))
    for spec in specs:
        trials = load_trials(cfg.evidence_dir, spec.id)
        if not trials:
            print("  {0}: no saved evidence, skipping".format(spec.id))
            continue
        print("  {0}".format(spec.id))
        updated: List[TrialResult] = []
        for t in trials:
            if only_unresolved and t.outcome != UNRESOLVED:
                print("    trial {0}: already {1}, left alone".format(
                    t.trial_index + 1, t.outcome.lower()))
                updated.append(t)
                continue
            provider.start_scope("{0}/t{1}/judge".format(spec.id, t.trial_index))
            try:
                verdict = judge.review(spec.prompt_view(), t.steps, t.signals,
                                       t.final_state or MISSING_STATE, t.evidence_dir)
            except QuotaExhausted as exc:
                print("\n  {0}".format(exc))
                print("  Leaving the remaining trials untouched.")
                updated.extend(trials[len(updated):])
                out.results.append(BugResult(spec=spec, trials=updated))
                return _finish(out, started)
            before = t.outcome
            t.judge_verdict = verdict.verdict
            t.judge_confidence = verdict.confidence
            t.judge_reason = verdict.reasoning
            t.judge_evidence = verdict.evidence
            t.judge_usage = verdict.usage
            t.outcome = combine(t.actor_verdict, verdict.verdict)
            t.error = verdict.error
            print("    trial {0}: {1} -> {2} (judge said {3})".format(
                t.trial_index + 1, before.lower(), t.outcome.lower(), verdict.verdict))
            path = os.path.join(t.evidence_dir, "trial.json")
            if os.path.isdir(t.evidence_dir):
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(dumps(t))
            updated.append(t)
        out.results.append(BugResult(spec=spec, trials=updated))

    return _finish(out, started)


def _finish(out: SuiteResult, started: float) -> SuiteResult:
    out.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
    out.duration_s = round(time.time() - started, 1)
    return out
