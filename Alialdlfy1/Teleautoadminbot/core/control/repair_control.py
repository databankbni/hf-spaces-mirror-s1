from __future__ import annotations
from core.control.router import ControlRouter
from core.control.repair_buttons import REPAIR_BUTTONS

class RepairControl:
    """Control-bot integration façade. Host Telegram layer only needs to dispatch callback strings."""
    def __init__(self, repair_engine, guard, state: dict|None=None):
        self.engine=repair_engine
        self.guard=guard
        self.state=state if state is not None else {"enabled": True, "pending": [], "last": None}
        self.router=ControlRouter()
        self._register()

    def _register(self):
        self.router.register("repair:status", lambda: {
            "enabled": self.state["enabled"],
            "pending": len(self.state["pending"]),
            "last": self.state["last"],
        })
        self.router.register("repair:pending", lambda: list(self.state["pending"]))
        self.router.register("repair:disable", self.disable)
        self.router.register("repair:enable", self.enable)
        self.router.register("repair:rollback", self.rollback)

    def disable(self):
        self.state["enabled"]=False
        return {"ok":True,"enabled":False}

    def enable(self):
        self.state["enabled"]=True
        return {"ok":True,"enabled":True}

    def queue_for_approval(self, record):
        self.state["pending"].append(record)
        self.state["last"]=record
        return record

    def approve(self, repair_record_id: str, apply_fn):
        if not self.state["enabled"]:
            return {"ok":False,"reason":"auto-repair disabled"}
        match=next((x for x in self.state["pending"] if getattr(x,"repair_id",None)==repair_record_id),None)
        if not match:
            return {"ok":False,"reason":"repair not found"}
        result=apply_fn(match)
        self.state["pending"]=[x for x in self.state["pending"] if x is not match]
        self.state["last"]=result
        return {"ok":True,"result":result}

    def rollback(self):
        last=self.state.get("last")
        if not last:
            return {"ok":False,"reason":"no repair recorded"}
        try:
            self.engine.rollback(last)
            self.state["last"]=last
            return {"ok":True,"status":"rolled_back"}
        except Exception as exc:
            return {"ok":False,"reason":str(exc)}
