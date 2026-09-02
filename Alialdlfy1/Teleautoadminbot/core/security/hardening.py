from __future__ import annotations
import hashlib, os, re, time
from dataclasses import dataclass
from typing import Iterable

@dataclass(frozen=True)
class SecurityFinding:
    code: str
    severity: str
    detail: str

class SecurityHardener:
    """Runtime security guardrails; additive and backwards compatible."""
    def __init__(self, secret_registry=None):
        self.registry = secret_registry
        self._values: set[str] = set()
        self._rotation_epoch = 0
        self._last_rotation = 0.0

    def refresh(self) -> int:
        if not self.registry:
            return 0
        count = 0
        for name in self.registry.discover():
            value = os.environ.get(name, "")
            if value:
                self._values.add(value)
                count += 1
        return count

    def register_secret_value(self, value: str | None):
        if value and len(value) >= 4:
            self._values.add(value)

    def redact(self, text: object) -> str:
        out = str(text)
        for value in sorted(self._values, key=len, reverse=True):
            if value:
                out = out.replace(value, "<REDACTED>")
        # Also catch common secret assignments not discovered from environment.
        return re.sub(r'(?i)(api[_-]?key|token|secret|password|credential)\s*[:=]\s*[^\s,;]+', r'\1=<REDACTED>', out)

    def fingerprint(self, value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()[:16]

    def validate_environment(self, required: Iterable[str] = ()) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        for name in required:
            if not os.getenv(name):
                findings.append(SecurityFinding("missing_secret", "critical", name))
        if os.getenv("P29_SECRET_MASTER_KEY") and len(os.getenv("P29_SECRET_MASTER_KEY", "")) < 32:
            findings.append(SecurityFinding("weak_master_key", "critical", "P29_SECRET_MASTER_KEY"))
        return findings

    def rotate_epoch(self) -> int:
        self._rotation_epoch += 1
        self._last_rotation = time.time()
        return self._rotation_epoch

    @property
    def rotation_epoch(self) -> int:
        return self._rotation_epoch
