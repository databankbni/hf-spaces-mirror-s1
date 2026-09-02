from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import prompts
from .actions import extract_json_block
from .llm.base import LLMError, LLMProvider, QuotaExhausted
from .models import INCONCLUSIVE, NOT_REPRODUCED, REPRODUCED, Signal, StepRecord, Usage

MAX_IMAGES = 4
SEVERITY_RANK = {"hard": 3, "notable": 2, "info": 1}


@dataclass
class JudgeVerdict:
    verdict: str = INCONCLUSIVE
    confidence: float = 0.0
    symptom_observed: str = ""
    evidence: List[str] = field(default_factory=list)
    reasoning: str = ""
    usage: Usage = field(default_factory=Usage)
    error: str = ""


def select_evidence_images(steps: Sequence[StepRecord], evidence_dir: str
                           ) -> Tuple[List[str], List[str]]:
    paths: List[str] = []
    notes: List[str] = []

    first = os.path.join(evidence_dir, "step00_screen.png")
    if os.path.exists(first):
        paths.append(first)
        notes.append("the page as it looked before any action")

    ranked = sorted(
        [s for s in steps if s.signals and s.action and s.action.name != "finish"],
        key=lambda s: -max([SEVERITY_RANK.get(sig.severity, 0) for sig in s.signals] or [0]))
    for s in ranked:
        if len(paths) >= MAX_IMAGES - 1:
            break
        for p in s.frames:
            if p not in paths and os.path.exists(p):
                paths.append(p)
                kinds = ", ".join(sorted({sig.kind for sig in s.signals}))
                notes.append("the page right after action {0} ({1}), where instrumentation "
                             "recorded: {2}".format(s.index + 1, s.action, kinds))
                break

    last_with_frame = [s for s in steps if s.frames and os.path.exists(s.frames[0])]
    if last_with_frame:
        final = last_with_frame[-1].frames[0]
        if final not in paths:
            paths.append(final)
            notes.append("the final state of the page when the run ended")
    return paths[:MAX_IMAGES], notes[:MAX_IMAGES]


def build_payload(report: str, steps: Sequence[StepRecord], signals: Sequence[Signal],
                  final_state: str, evidence_dir: str) -> Tuple[str, str, List[bytes], List[str]]:
    action_lines = ["{0} -> {1}".format(s.action, s.result)
                    for s in steps if s.action and s.action.name != "finish"]
    signal_lines = [s.line() for s in signals]
    paths, notes = select_evidence_images(steps, evidence_dir)
    images: List[bytes] = []
    for p in paths:
        with open(p, "rb") as fh:
            images.append(fh.read())
    user = prompts.judge_user(report, action_lines, signal_lines, final_state, notes)
    return prompts.JUDGE_SYSTEM, user, images, notes


class Judge:
    def __init__(self, provider: LLMProvider):
        self.provider = provider

    def review(self, report: str, steps: Sequence[StepRecord], signals: Sequence[Signal],
               final_state: str, evidence_dir: str) -> JudgeVerdict:
        system, user, images, _ = build_payload(report, steps, signals, final_state, evidence_dir)
        try:
            reply = self.provider.complete(system, user, images)
        except QuotaExhausted:
            raise
        except LLMError as exc:
            return JudgeVerdict(error=str(exc), reasoning="judge could not be reached")
        v = parse_verdict(reply.text)
        v.usage = reply.usage
        return v


def parse_verdict(text: str) -> JudgeVerdict:
    try:
        data: Dict[str, Any] = json.loads(extract_json_block(text))
    except Exception as exc:
        return JudgeVerdict(error="unparseable judge reply: {0}".format(exc),
                            reasoning=text.strip()[:400])
    verdict = str(data.get("verdict", "")).upper().strip()
    if verdict not in {REPRODUCED, NOT_REPRODUCED, INCONCLUSIVE}:
        verdict = INCONCLUSIVE
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    evidence = data.get("evidence") or []
    if isinstance(evidence, str):
        evidence = [evidence]
    return JudgeVerdict(
        verdict=verdict, confidence=max(0.0, min(1.0, confidence)),
        symptom_observed=str(data.get("symptom_observed", ""))[:400],
        evidence=[str(e)[:300] for e in evidence][:8],
        reasoning=str(data.get("reasoning", ""))[:800])
