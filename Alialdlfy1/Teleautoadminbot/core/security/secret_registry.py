from __future__ import annotations
import os, re, time
from dataclasses import dataclass

@dataclass
class SecretState:
    name: str
    healthy: bool = True
    failures: int = 0
    last_error: str = ""
    cooldown_until: float = 0.0

class SecretRegistry:
    """Discovers compatible secret names without renaming existing environment variables."""
    def __init__(self, prefix: str|None=None):
        self.prefix=prefix
        self.states: dict[str,SecretState]={}

    def discover(self) -> list[str]:
        names=[]
        for k,v in os.environ.items():
            if not v: continue
            if self.prefix and not k.startswith(self.prefix): continue
            # Broad, additive discovery: API_KEY / TOKEN / SECRET / CREDENTIAL patterns.
            if re.search(r"(API[_-]?KEY|TOKEN|SECRET|CREDENTIAL|ACCESS[_-]?KEY)", k, re.I):
                names.append(k)
                self.states.setdefault(k,SecretState(k))
        return sorted(names)

    def available(self) -> list[str]:
        now=time.time()
        return [n for n in self.discover() if self.states[n].healthy and self.states[n].cooldown_until <= now]

    def mark_failure(self,name,error,cooldown=60):
        s=self.states.setdefault(name,SecretState(name))
        s.failures+=1; s.healthy=False; s.last_error=str(error)[:500]
        s.cooldown_until=time.time()+cooldown

    def mark_success(self,name):
        s=self.states.setdefault(name,SecretState(name))
        s.healthy=True; s.failures=0; s.last_error=""; s.cooldown_until=0

    def get(self,name):
        return os.environ.get(name)
