from core.health.monitor import HealthMonitor
from core.supervisor.supervisor import Supervisor, SupervisedService

def test_health_monitor_recovers():
    m=HealthMonitor(); state={"ok":False}
    m.register("x", lambda: {"v":1} if state["ok"] else (_ for _ in ()).throw(RuntimeError("down")))
    assert m.check("x").status=="unhealthy"
    state["ok"]=True
    assert m.check("x").status=="healthy"

def test_supervisor_restarts_dead_service():
    state={"alive":False,"restarts":0}
    def restart(): state["restarts"]+=1; state["alive"]=True
    s=SupervisedService("x",lambda:None,lambda:None,restart,lambda:state["alive"])
    sup=Supervisor(backoff_seconds=0)
    sup.register(s)
    assert sup.ensure("x") is True
    assert state["restarts"]==1

def test_supervisor_caps_restarts():
    state={"alive":False}
    s=SupervisedService("x",lambda:None,lambda:None,lambda:None,lambda:False)
    sup=Supervisor(max_restarts=1,backoff_seconds=0); sup.register(s)
    sup.ensure("x")
    assert sup.ensure("x") is False
    assert s.disabled is True
