from __future__ import annotations
from collections import Counter, defaultdict
from threading import Lock
from time import monotonic
class Metrics:
    def __init__(self): self._c=Counter(); self._timings=defaultdict(lambda:[0.0,0,0.0]); self._lock=Lock()
    def inc(self,name,n=1):
        with self._lock:self._c[name]+=n
    def observe(self,name,seconds):
        v=max(0.0,float(seconds))
        with self._lock:
            x=self._timings[name]; x[0]+=v; x[1]+=1; x[2]=max(x[2],v)
    def timer(self,name):
        metrics=self; start=monotonic()
        class T:
            def __enter__(self):return self
            def __exit__(self,*exc):metrics.observe(name,monotonic()-start)
        return T()
    def snapshot(self):
        with self._lock:return dict(self._c)
    def detailed_snapshot(self):
        with self._lock:return {"counters":dict(self._c),"latency":{k:{"total_seconds":round(v[0],6),"count":v[1],"max_seconds":round(v[2],6),"avg_seconds":round(v[0]/v[1],6) if v[1] else 0} for k,v in self._timings.items()}}
