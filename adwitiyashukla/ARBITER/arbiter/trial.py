from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import cost as cost_mod
from . import perception
from .agent import Actor
from .benchmark import load_suite
from .config import RunConfig, key_for
from .judge import Judge
from .llm.base import QuotaExhausted, build_provider
from .llm.mock import RecordingProvider
from .models import (AGREED_NOT_REPRODUCED, CONFIRMED, DISPUTED, INCONCLUSIVE,
                     NOT_REPRODUCED, REJECTED, REPRODUCED, UNRESOLVED, BugResult,
                     BugSpec, TrialResult, Usage, dumps)
from .oracle import CrashOracle
from .server import BenchmarkServer


def combine(actor_verdict: str, judge_verdict: str) -> str:
    if judge_verdict == INCONCLUSIVE:
        return UNRESOLVED
    if actor_verdict == REPRODUCED and judge_verdict == REPRODUCED:
        return CONFIRMED
    if actor_verdict == REPRODUCED and judge_verdict == NOT_REPRODUCED:
        return REJECTED
    if actor_verdict != REPRODUCED and judge_verdict == REPRODUCED:
        return DISPUTED
    return AGREED_NOT_REPRODUCED


@dataclass
class SuiteResult:
    config: Dict[str, object]
    results: List[BugResult] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    duration_s: float = 0.0


def _providers(cfg: RunConfig, scope: str) -> Tuple[object, object]:
    actor = build_provider(cfg.provider, cfg.actor_model, key_for(cfg.provider))
    judge = build_provider(cfg.effective_judge_provider, cfg.judge_model,
                           key_for(cfg.effective_judge_provider))
    if cfg.provider == "mock":
        actor.trace_dir = cfg.trace_dir
        judge.trace_dir = cfg.trace_dir
    if cfg.record and cfg.provider != "mock":
        actor = RecordingProvider(actor, cfg.trace_dir)
        judge = RecordingProvider(judge, cfg.trace_dir)
    actor.start_scope(scope + "/actor")
    judge.start_scope(scope + "/judge")
    return actor, judge


def build_driver(crash: CrashOracle, spec: BugSpec, cfg: RunConfig, evidence_dir: str):
    from .driver.web import WebDriver
    return WebDriver(crash, spec.viewport, headless=cfg.headless,
                     video_dir=os.path.join(evidence_dir, "video") if cfg.video else "")


DRIVER_FACTORY = build_driver


def run_trial(spec: BugSpec, cfg: RunConfig, server: BenchmarkServer, index: int) -> TrialResult:
    scope = "{0}/t{1}".format(spec.id, index)
    evidence_dir = os.path.join(cfg.evidence_dir, spec.id, "t{0}".format(index))
    os.makedirs(evidence_dir, exist_ok=True)
    actor_provider, judge_provider = _providers(cfg, scope)

    crash = CrashOracle()
    driver = DRIVER_FACTORY(crash, spec, cfg, evidence_dir)
    started = time.time()
    error = ""
    actor_verdict, actor_reason = INCONCLUSIVE, ""
    steps, signals = [], []
    final_state = ""
    actor_usage = Usage()

    try:
        driver.start()
        driver.goto(server.url_for(spec.app))
        actor = Actor(actor_provider, driver, spec, crash, evidence_dir)
        actor_verdict, actor_reason, steps, signals = actor.run()
        actor_usage = actor.usage
        try:
            snap, _ = driver.snapshot()
            final_state = perception.element_map(snap)
        except Exception:
            final_state = "(final page state could not be captured)"
    except Exception as exc:
        error = "{0}: {1}".format(type(exc).__name__, str(exc)[:300])
    finally:
        driver.stop()

    judge_result = Judge(judge_provider).review(
        spec.prompt_view(), steps, signals, final_state, evidence_dir)

    outcome = combine(actor_verdict, judge_result.verdict)
    trial = TrialResult(
        bug_id=spec.id, trial_index=index,
        actor_verdict=actor_verdict, actor_reason=actor_reason,
        judge_verdict=judge_result.verdict, judge_confidence=judge_result.confidence,
        judge_reason=judge_result.reasoning, judge_evidence=judge_result.evidence,
        outcome=outcome, steps=steps, signals=signals,
        actor_usage=actor_usage, judge_usage=judge_result.usage,
        duration_s=round(time.time() - started, 2), evidence_dir=evidence_dir,
        final_state=final_state, error=error or judge_result.error)

    with open(os.path.join(evidence_dir, "trial.json"), "w", encoding="utf-8") as fh:
        fh.write(dumps(trial))
    return trial


def run_bug(spec: BugSpec, cfg: RunConfig, server: BenchmarkServer) -> BugResult:
    trials = []
    for i in range(cfg.trials):
        t = run_trial(spec, cfg, server, i)
        mark = {CONFIRMED: "confirmed", REJECTED: "rejected by judge",
                DISPUTED: "judge overruled actor", AGREED_NOT_REPRODUCED: "not reproduced",
                UNRESOLVED: "inconclusive"}[t.outcome]
        print("    trial {0}: actor={1:<15} judge={2:<15} -> {3} ({4:.0f}s)".format(
            i + 1, t.actor_verdict, t.judge_verdict, mark, t.duration_s))
        trials.append(t)
    return BugResult(spec=spec, trials=trials)


def run_suite(cfg: RunConfig) -> SuiteResult:
    specs = load_suite(cfg.bugs_dir, cfg.only)
    started = time.time()
    out = SuiteResult(config=cfg.describe(),
                      started_at=time.strftime("%Y-%m-%d %H:%M:%S"))
    print("ARBITER: {0} bug report(s), {1} trial(s) each".format(len(specs), cfg.trials))
    print("  actor {0}   judge {1}".format(out.config["actor"], out.config["judge"]))
    print("  pacing at {0:.0f} requests per minute".format(cfg.rpm))
    with BenchmarkServer(cfg.apps_dir) as server:
        print("  benchmark served from {0}\n".format(server.url_for("")))
        for spec in specs:
            tag = "control" if spec.control else spec.category
            print("  {0}  [{1}]".format(spec.id, tag))
            try:
                out.results.append(run_bug(spec, cfg, server))
            except KeyboardInterrupt:
                print("\n  interrupted. Reporting on the {0} report(s) already "
                      "completed.".format(len(out.results)))
                break
            except QuotaExhausted as exc:
                print("\n  {0}\n  Reporting on the {1} report(s) already completed.".format(
                    exc, len(out.results)))
                break
            except Exception as exc:
                print("    {0} failed: {1}: {2}".format(spec.id, type(exc).__name__,
                                                        str(exc)[:200]))
                if not out.results:
                    raise
    out.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
    out.duration_s = round(time.time() - started, 1)
    return out


def metrics(suite: SuiteResult) -> Dict[str, object]:
    seeded = [r for r in suite.results if not r.spec.control]
    controls = [r for r in suite.results if r.spec.control]
    trials = [t for r in suite.results for t in r.trials]
    usages = [u for t in trials for u in (t.actor_usage, t.judge_usage)]

    reproduced = [r for r in seeded if r.verdict == REPRODUCED]
    false_positives = [r for r in controls if r.false_positive]
    claimed = sum(1 for t in trials if t.actor_verdict == REPRODUCED)
    confirmed = sum(1 for t in trials if t.outcome == CONFIRMED)

    return {
        "bugs_total": len(suite.results),
        "seeded_bugs": len(seeded),
        "controls": len(controls),
        "reproduced": len(reproduced),
        "reproduction_rate": round(len(reproduced) / len(seeded), 3) if seeded else 0.0,
        "false_positives": len(false_positives),
        "false_positive_rate": round(len(false_positives) / len(controls), 3) if controls else 0.0,
        "accuracy": round(sum(1 for r in suite.results if r.correct) / len(suite.results), 3)
                    if suite.results else 0.0,
        "trials_total": len(trials),
        "actor_claimed": claimed,
        "judge_confirmed": confirmed,
        "judge_rejected": sum(1 for t in trials if t.outcome == REJECTED),
        "judge_disputed": sum(1 for t in trials if t.outcome == DISPUTED),
        "unresolved": sum(1 for t in trials if t.outcome == UNRESOLVED),
        "overclaim_rate": round(sum(1 for t in trials if t.outcome == REJECTED) / claimed, 3)
                          if claimed else 0.0,
        "unconfirmed_rate": round((claimed - confirmed) / claimed, 3) if claimed else 0.0,
        "deterministic": sum(1 for r in suite.results if r.stability == "deterministic"),
        "flaky": sum(1 for r in suite.results if r.stability in ("flaky", "rare")),
        "cost": cost_mod.summarise(usages),
        "duration_s": suite.duration_s,
    }
