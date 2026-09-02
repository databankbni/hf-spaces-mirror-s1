from __future__ import annotations

import json
import os
import time
from typing import Dict, List

from .benchmark import load_suite
from .config import RunConfig, key_for
from .judge import Judge
from .llm.base import build_provider
from .models import NOT_REPRODUCED, REPRODUCED
from .persist import load_trials


def run_audit(cfg: RunConfig) -> Dict[str, object]:
    specs = [s for s in load_suite(cfg.bugs_dir, cfg.only) if not s.control]
    if len(specs) < 2:
        raise ValueError("the audit needs at least two seeded bugs to shuffle between")

    provider = build_provider(cfg.effective_judge_provider, cfg.judge_model,
                              key_for(cfg.effective_judge_provider))
    judge = Judge(provider)
    rows: List[Dict[str, object]] = []
    started = time.time()

    print("judge audit: each run's evidence reviewed against a report it does not match")
    for i, evidence_spec in enumerate(specs):
        mismatched = specs[(i + 1) % len(specs)]
        trials = load_trials(cfg.evidence_dir, evidence_spec.id)
        if not trials:
            print("  {0}: no evidence on disk, skipping".format(evidence_spec.id))
            continue
        t = trials[0]
        provider.start_scope("audit/{0}".format(evidence_spec.id))
        verdict = judge.review(mismatched.prompt_view(), t.steps, t.signals,
                               t.final_state, t.evidence_dir)
        correct = verdict.verdict != REPRODUCED
        rows.append({
            "evidence_from": evidence_spec.id,
            "judged_against": mismatched.id,
            "verdict": verdict.verdict,
            "confidence": verdict.confidence,
            "refused": correct,
            "reasoning": verdict.reasoning,
        })
        print("  {0:<18} evidence vs {1:<18} report -> {2:<16} {3}".format(
            evidence_spec.id, mismatched.id, verdict.verdict,
            "correctly refused" if correct else "RUBBER STAMPED"))

    refused = sum(1 for r in rows if r["refused"])
    summary = {
        "pairs": len(rows),
        "refused": refused,
        "rubber_stamped": len(rows) - refused,
        "refusal_rate": round(refused / len(rows), 3) if rows else 0.0,
        "duration_s": round(time.time() - started, 1),
        "judge_model": cfg.judge_model,
        "rows": rows,
    }
    print("\n{0}/{1} mismatched pairs correctly refused".format(refused, len(rows)))
    if summary["rubber_stamped"]:
        print("{0} pair(s) were confirmed against evidence that cannot support them. "
              "That is a real weakness and belongs in the writeup.".format(summary["rubber_stamped"]))
    os.makedirs(cfg.out_dir, exist_ok=True)
    path = os.path.join(cfg.out_dir, "judge_audit.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    print("saved {0}".format(path))
    return summary
