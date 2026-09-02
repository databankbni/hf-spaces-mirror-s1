from __future__ import annotations
import time
from threading import Lock

class TokenBucket:
    def __init__(self,rate_per_second=1.0,capacity=1):
        self.rate=max(float(rate_per_second),0.001); self.capacity=max(int(capacity),1)
        self.tokens=float(self.capacity); self.updated=time.monotonic(); self.lock=Lock()
    def acquire(self,tokens=1):
        tokens=float(tokens)
        while True:
            with self.lock:
                now=time.monotonic()
                self.tokens=min(self.capacity,self.tokens+(now-self.updated)*self.rate)
                self.updated=now
                if self.tokens>=tokens:
                    self.tokens-=tokens; return
                wait=(tokens-self.tokens)/self.rate
            time.sleep(min(max(wait,0.01),5))

class ProviderLimiter:
    def __init__(self):
        self.buckets={}
    def configure(self,name,rate_per_second,capacity=1):
        self.buckets[name]=TokenBucket(rate_per_second,capacity)
    def acquire(self,name,tokens=1):
        self.buckets.setdefault(name,TokenBucket()).acquire(tokens)
