from core.control.repair_control import RepairControl
from core.control.repair_buttons import REPAIR_BUTTONS

class E:
    def __init__(self): self.rolled=False
    def rollback(self, r): self.rolled=True

def test_control_callbacks():
    e=E(); c=RepairControl(e,None)
    assert c.router.dispatch("repair:status")["enabled"] is True
    assert c.router.dispatch("repair:disable")["enabled"] is False
    assert c.router.dispatch("repair:enable")["enabled"] is True
    assert len(REPAIR_BUTTONS)>=6

def test_pending_approval():
    e=E(); c=RepairControl(e,None)
    class R: repair_id="r1"
    c.queue_for_approval(R())
    out=c.approve("r1", lambda r: r)
    assert out["ok"] is True
    assert c.state["pending"]==[]
