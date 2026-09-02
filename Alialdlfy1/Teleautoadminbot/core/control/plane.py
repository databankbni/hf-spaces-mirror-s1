from __future__ import annotations
import time
from dataclasses import dataclass, asdict

@dataclass
class Alert:
    key: str
    severity: str
    message: str
    first_seen: float
    last_seen: float
    count: int = 1
    active: bool = True

class ControlPlane:
    """Read-only operational control surface with safe, actionable alerts."""
    def __init__(self, runtime, dead_threshold=1, queue_threshold=50):
        self.runtime = runtime
        self.dead_threshold = int(dead_threshold)
        self.queue_threshold = int(queue_threshold)
        self._alerts: dict[str, Alert] = {}

    def _upsert(self, key, severity, message):
        now=time.time(); old=self._alerts.get(key)
        if old:
            old.last_seen=now; old.count+=1; old.active=True; old.message=message
        else:
            self._alerts[key]=Alert(key,severity,message,now,now)

    def evaluate(self):
        stats=self.runtime.queue.store.get_stats()
        if stats.get("dead",0)>=self.dead_threshold: self._upsert("queue.dead","critical",f"Dead-letter jobs: {stats['dead']}")
        else: self._resolve("queue.dead")
        if stats.get("queued",0)>=self.queue_threshold: self._upsert("queue.backlog","warning",f"Queue backlog: {stats['queued']}")
        else: self._resolve("queue.backlog")
        for name,item in self.runtime.health_snapshot().items():
            key=f"health:{name}"
            if item.get("status")=="unhealthy": self._upsert(key,"critical",f"Unhealthy service: {name}")
            else: self._resolve(key)
        return self.active_alerts()

    def _resolve(self,key):
        if key in self._alerts: self._alerts[key].active=False
    def active_alerts(self): return [asdict(a) for a in self._alerts.values() if a.active]
    def snapshot(self):
        return {"queue":self.runtime.queue.store.get_stats(),"health":self.runtime.health_snapshot(),"metrics":self.runtime.metrics_snapshot(),"providers":self.runtime.pool.snapshot(),"alerts":self.evaluate(),"sections":{s:self.runtime.get_section_state(s) for s in self.runtime._sections},"security":self.security_snapshot()}
    def security_snapshot(self):
        findings = self.runtime.security.validate_environment() if hasattr(self.runtime, "security") else []
        return {"rotation_epoch": getattr(getattr(self.runtime, "security", None), "rotation_epoch", 0), "findings":[getattr(x, "__dict__", str(x)) for x in findings]}

    def acknowledge(self,key,admin_approved=False):
        if not admin_approved:return {"ok":False,"reason":"admin_required"}
        alert=self._alerts.get(key)
        if not alert:return {"ok":False,"reason":"not_found"}
        alert.active=False
        return {"ok":True,"key":key}
