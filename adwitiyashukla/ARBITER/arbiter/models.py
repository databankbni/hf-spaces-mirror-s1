from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

REPRODUCED = "REPRODUCED"
NOT_REPRODUCED = "NOT_REPRODUCED"
INCONCLUSIVE = "INCONCLUSIVE"

CONFIRMED = "CONFIRMED"
REJECTED = "REJECTED"
DISPUTED = "DISPUTED"
AGREED_NOT_REPRODUCED = "AGREED_NOT_REPRODUCED"
UNRESOLVED = "UNRESOLVED"


@dataclass
class BugSpec:
    id: str
    title: str
    app: str
    category: str
    ground_truth: str
    control: bool
    report: str
    pattern: str = ""
    max_steps: int = 15
    viewport: Dict[str, int] = field(default_factory=lambda: {"width": 1000, "height": 800})

    def prompt_view(self) -> str:
        return "TITLE: {0}\n\n{1}".format(self.title, self.report.strip())


@dataclass
class Action:
    name: str
    args: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        if not self.args:
            return self.name
        pretty = ", ".join("{0}={1!r}".format(k, v) for k, v in self.args.items())
        return "{0}({1})".format(self.name, pretty)


@dataclass
class Signal:
    source: str
    kind: str
    detail: str
    step: int
    severity: str = "info"
    evidence: Dict[str, Any] = field(default_factory=dict)

    def line(self) -> str:
        return "[step {0}] {1}.{2} ({3}): {4}".format(
            self.step, self.source, self.kind, self.severity, self.detail
        )


@dataclass
class StepRecord:
    index: int
    url: str
    action: Optional[Action]
    result: str
    element_count: int
    frames: List[str] = field(default_factory=list)
    signals: List[Signal] = field(default_factory=list)


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    model: str = ""

    def add(self, other: "Usage") -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.calls += other.calls
        self.model = self.model or other.model


@dataclass
class TrialResult:
    bug_id: str
    trial_index: int
    actor_verdict: str
    actor_reason: str
    judge_verdict: str
    judge_confidence: float
    judge_reason: str
    judge_evidence: List[str]
    outcome: str
    steps: List[StepRecord]
    signals: List[Signal]
    actor_usage: Usage
    judge_usage: Usage
    duration_s: float
    evidence_dir: str
    final_state: str = ""
    error: str = ""

    @property
    def reproduced(self) -> bool:
        return self.outcome == CONFIRMED


@dataclass
class BugResult:
    spec: BugSpec
    trials: List[TrialResult]

    @property
    def confirmed(self) -> int:
        return sum(1 for t in self.trials if t.reproduced)

    @property
    def actor_claimed(self) -> int:
        return sum(1 for t in self.trials if t.actor_verdict == REPRODUCED)

    @property
    def rejected(self) -> int:
        return sum(1 for t in self.trials if t.outcome == REJECTED)

    @property
    def disputed(self) -> int:
        return sum(1 for t in self.trials if t.outcome == DISPUTED)

    @property
    def reproduction_rate(self) -> float:
        return (self.confirmed / len(self.trials)) if self.trials else 0.0

    @property
    def stability(self) -> str:
        r = self.reproduction_rate
        if r == 0.0:
            return "never"
        if r >= 0.9:
            return "deterministic"
        if r >= 0.3:
            return "flaky"
        return "rare"

    @property
    def verdict(self) -> str:
        return REPRODUCED if self.reproduction_rate > 0.5 else NOT_REPRODUCED

    @property
    def correct(self) -> bool:
        return self.verdict == self.spec.ground_truth

    @property
    def false_positive(self) -> bool:
        return self.spec.control and self.verdict == REPRODUCED


def to_jsonable(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return {k: to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    return obj


def dumps(obj: Any) -> str:
    return json.dumps(to_jsonable(obj), indent=2, default=str)
