from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import time

@dataclass(frozen=True)
class RepairPolicy:
    enabled: bool = True
    auto_apply_low_risk: bool = False
    require_admin_for_medium: bool = True
    require_admin_for_high: bool = True
    max_attempts_per_incident: int = 2
    cooldown_seconds: int = 300
    allowed_roots: tuple[str,...] = ("core/", "modules/", "services/")
    protected_fragments: tuple[str,...] = (
        ".env", "secret", "credential", "token", "key",
        "sessions/", "data/", ".git/"
    )

class RepairGuard:
    def __init__(self, policy: RepairPolicy|None=None):
        self.policy=policy or RepairPolicy()
        self._incidents={}

    def classify(self, changed_files):
        files=[x.replace("\\","/").lower() for x in changed_files]
        if any(any(p in f for p in self.policy.protected_fragments) for f in files):
            return "blocked"
        if any(not any(f.startswith(r) for r in self.policy.allowed_roots) for f in files):
            return "high"
        if any(f.endswith((".py",".json",".yaml",".yml")) for f in files):
            return "medium"
        return "high"

    def authorize(self, incident_id, changed_files, admin_approved=False):
        risk=self.classify(changed_files)
        now=time.time()
        state=self._incidents.get(incident_id, {"attempts":0,"last":0})
        if risk=="blocked": return False, risk, "protected files are never auto-repairable"
        if state["attempts"] >= self.policy.max_attempts_per_incident:
            return False, risk, "repair attempt limit reached"
        if now-state["last"] < self.policy.cooldown_seconds:
            return False, risk, "repair cooldown active"
        if risk=="medium" and self.policy.require_admin_for_medium and not admin_approved:
            return False, risk, "admin approval required"
        if risk=="high" and self.policy.require_admin_for_high and not admin_approved:
            return False, risk, "admin approval required"
        state["attempts"]+=1; state["last"]=now; self._incidents[incident_id]=state
        return True, risk, "authorized"
