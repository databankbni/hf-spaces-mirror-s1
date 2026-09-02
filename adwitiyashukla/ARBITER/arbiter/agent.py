from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from . import actions as action_mod
from . import perception, prompts
from .llm.base import LLMError, LLMProvider, QuotaExhausted
from .models import (INCONCLUSIVE, NOT_REPRODUCED, REPRODUCED, Action, BugSpec,
                     Signal, StepRecord, Usage)
from .oracle import CrashOracle, DomOracle, VisualOracle

MAX_PARSE_RETRIES = 2
REPEAT_LIMIT = 3


class Actor:
    def __init__(self, provider: LLMProvider, driver, spec: BugSpec,
                 crash: CrashOracle, evidence_dir: str):
        self.provider = provider
        self.driver = driver
        self.spec = spec
        self.crash = crash
        self.visual = VisualOracle()
        self.dom = DomOracle()
        self.evidence_dir = evidence_dir
        self.usage = Usage()
        self.steps: List[StepRecord] = []
        self.signals: List[Signal] = []
        os.makedirs(evidence_dir, exist_ok=True)

    def _save(self, name: str, blob: bytes) -> str:
        path = os.path.join(self.evidence_dir, name)
        with open(path, "wb") as fh:
            fh.write(blob)
        return path

    def run(self) -> Tuple[str, str, List[StepRecord], List[Signal]]:
        history: List[str] = []
        pending: List[Signal] = []
        recent: List[str] = []
        verdict, reason = INCONCLUSIVE, "the run ended without a verdict"

        snap, raw_png = self.driver.snapshot()
        self._save("step00_screen.png", raw_png)

        for step in range(self.spec.max_steps):
            elements = snap.get("elements", [])
            annotated = perception.annotate(raw_png, elements)
            if step == 0:
                self._save("step00_annotated.png", annotated)

            warning = ""
            if len(recent) >= REPEAT_LIMIT and len(set(recent[-REPEAT_LIMIT:])) == 1:
                warning = ("you have repeated {0!r} {1} times with no progress. If the report does "
                           "not call for repetition, try a different element or a different path."
                           ).format(recent[-1], REPEAT_LIMIT)

            user = prompts.actor_user(
                report=self.spec.prompt_view(), step=step, max_steps=self.spec.max_steps,
                history=history, signals=[s.line() for s in pending],
                element_map=perception.element_map(snap),
                color_bands=perception.region_colors(raw_png), repeat_warning=warning)

            action = self._decide(user, annotated)
            if action is None:
                verdict, reason = INCONCLUSIVE, "the actor produced no valid action"
                break

            if action.name == "finish":
                verdict = action.args["verdict"]
                reason = str(action.args["reason"])
                self.steps.append(StepRecord(step, self.driver.url, action, "run ended",
                                             len(elements), [], []))
                history.append("{0} -> {1}".format(action, verdict))
                break

            result, frames, stamps = self.driver.act_with_burst(action)
            recent.append(str(action))
            history.append("{0} -> {1}".format(action, result))

            step_signals: List[Signal] = []
            step_signals += self.visual.inspect(step, frames, stamps)
            step_signals += self.crash.drain(step)

            snap, raw_png = self.driver.snapshot()
            new_elements = snap.get("elements", [])
            step_signals += self.dom.inspect(step, elements, new_elements, snap.get("viewport"))

            shot_path = self._save("step{0:02d}_screen.png".format(step + 1), raw_png)
            self.steps.append(StepRecord(step, self.driver.url, action, result,
                                         len(new_elements), [shot_path], step_signals))
            self.signals += step_signals
            pending = step_signals
        else:
            verdict = INCONCLUSIVE
            reason = "the actor used all {0} steps without reaching a verdict".format(self.spec.max_steps)

        return verdict, reason, self.steps, self.signals

    def _decide(self, user: str, image: bytes) -> Optional[Action]:
        message = user
        for attempt in range(MAX_PARSE_RETRIES + 1):
            try:
                reply = self.provider.complete(prompts.actor_system(), message, [image])
            except QuotaExhausted:
                raise
            except LLMError as exc:
                print("    [actor] provider error: {0}".format(exc))
                return None
            self.usage.add(reply.usage)
            try:
                parsed = action_mod.parse(reply.text)
                return parsed[0]
            except (action_mod.ActionError, ValueError) as exc:
                if attempt == MAX_PARSE_RETRIES:
                    print("    [actor] gave up parsing after {0} tries: {1}".format(attempt + 1, exc))
                    return None
                message = (user + "\n\nYour previous reply could not be used: {0}\n"
                           "Reply with exactly one JSON action in a fenced block.".format(exc))
        return None
