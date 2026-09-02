from __future__ import annotations

from core.sections.controls import build_section_buttons


class SectionControl:
    """Control-bot façade for all content sections.

    Callback names are additive (`news:*`, `sports:*`, `blogger:*`); legacy
    callback strings are not renamed or removed.
    """

    def __init__(self, runtime, admin_check=None):
        self.runtime = runtime
        self.admin_check = admin_check or (lambda _user_id: True)

    def callbacks(self):
        out = {}
        for section in ("news", "sports", "blogger"):
            for button in build_section_buttons(section):
                out[button.callback] = self.handle
        return out

    def handle(self, callback: str, user_id=None):
        if callback.count(":") != 1:
            return {"ok": False, "reason": "invalid_callback"}
        section, action = callback.split(":", 1)
        if section not in ("news", "sports", "blogger"):
            return {"ok": False, "reason": "unknown_section"}

        if action == "settings" or action == "status":
            return {"ok": True, "section": section, "state": self.runtime.get_section_state(section)}
        if action == "sources":
            return {"ok": True, "section": section, "sources": self.runtime.get_section_state(section)["sources"]}
        if action == "blocked":
            return {"ok": True, "section": section, "blocked_words": self.runtime.get_section_state(section)["blocked_words"]}
        if action == "duplicates":
            return {"ok": True, "section": section, "enabled": self.runtime.get_section_state(section)["duplicate_protection"]}
        if action == "ai":
            return {"ok": True, "section": section, "enabled": self.runtime.get_section_state(section)["ai_enabled"]}
        if action == "queue":
            return {"ok": True, "section": section, "queue": self.runtime.queue.store.get_stats()}
        if action == "metrics":
            return {"ok": True, "section": section, "metrics": self.runtime.metrics_snapshot(), "detailed": self.runtime.metrics.detailed_snapshot()}
        if action == "health":
            return {"ok": True, "section": section, "health": self.runtime.health_snapshot()}
        if action == "dead":
            return {"ok": True, "section": section, "jobs": self.runtime.queue_snapshot(status="dead")}
        if action == "enable":
            return self.runtime.set_section_state(section, enabled=True).__dict__
        if action == "disable":
            return self.runtime.set_section_state(section, enabled=False).__dict__
        if action == "repair":
            if not self.admin_check(user_id):
                return {"ok": False, "reason": "admin_required"}
            return {"ok": True, **self.runtime.set_auto_repair(True)}
        return {"ok": False, "reason": "unknown_action"}


class ControlPlaneControl:
    CALLBACKS=("control:overview","control:alerts","control:providers","control:audit")
    def __init__(self,runtime,admin_check=None): self.runtime=runtime; self.admin_check=admin_check or (lambda _uid:True)
    def handle(self,callback,user_id=None):
        if callback=="control:overview": return {"ok":True,**self.runtime.operational_snapshot()}
        if callback=="control:alerts": return {"ok":True,"alerts":self.runtime.control_plane.evaluate()}
        if callback=="control:providers": return {"ok":True,"providers":self.runtime.pool.snapshot()}
        if callback=="control:audit":
            if not self.admin_check(user_id): return {"ok":False,"reason":"admin_required"}
            return {"ok":True,"audit":self.runtime.recent_audit(50)}
        return {"ok":False,"reason":"unknown_action"}
