from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Optional

DEFAULTS = {
    "provider": "gemini",
    "actor_model": "gemini-3.5-flash-lite",
    "judge_provider": "",
    "judge_model": "gemini-3.5-flash",
    "trials": 3,
}


def load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def key_for(provider: str) -> str:
    env = {"gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
           "openai": ("OPENAI_API_KEY",),
           "anthropic": ("ANTHROPIC_API_KEY",),
           "mock": ()}.get(provider, ())
    for name in env:
        v = os.environ.get(name, "").strip()
        if v:
            return v
    return ""


@dataclass
class RunConfig:
    provider: str = DEFAULTS["provider"]
    actor_model: str = DEFAULTS["actor_model"]
    judge_provider: str = DEFAULTS["judge_provider"]
    judge_model: str = DEFAULTS["judge_model"]
    trials: int = DEFAULTS["trials"]
    rpm: float = 12.0
    headless: bool = True
    record: bool = False
    video: bool = False
    bugs_dir: str = "benchmark/bugs"
    apps_dir: str = "benchmark/apps"
    out_dir: str = "results"
    evidence_dir: str = "evidence"
    trace_dir: str = "traces"
    only: Optional[str] = None
    seed_note: str = ""

    @property
    def effective_judge_provider(self) -> str:
        return self.judge_provider or self.provider

    def describe(self) -> Dict[str, object]:
        return {
            "actor": "{0}:{1}".format(self.provider, self.actor_model),
            "judge": "{0}:{1}".format(self.effective_judge_provider, self.judge_model),
            "trials_per_bug": self.trials,
            "rpm": self.rpm,
            "headless": self.headless,
        }
