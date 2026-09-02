from __future__ import annotations
from .engine import AutoRepairEngine
from .policy import RepairGuard

class GuardedRepair:
    def __init__(self, engine: AutoRepairEngine, guard: RepairGuard, health_check=None):
        self.engine=engine
        self.guard=guard
        self.health_check=health_check

    def test_and_apply(self, incident_id, patch, tests=None, admin_approved=False):
        rec,res=self.engine.propose_and_test(patch, tests=tests)
        if not res.passed:
            return rec
        allowed,risk,reason=self.guard.authorize(incident_id, rec.changed_files, admin_approved)
        if not allowed:
            rec.status="approval_required" if "approval" in reason else "blocked"
            rec.reason=reason
            return rec
        rec=self.engine.apply_approved(rec,res.sandbox_dir)
        if self.health_check:
            try:
                healthy=self.health_check()
            except Exception:
                healthy=False
            if not healthy:
                self.engine.rollback(rec)
        return rec
