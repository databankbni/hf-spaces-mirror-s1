from __future__ import annotations
from dataclasses import dataclass
from .preflight import ContentPreflight
from .dedup import DedupStore

@dataclass
class GateDecision:
    accepted: bool
    reason: str
    fingerprint: str

class ContentGate:
    def __init__(self,blocked_words=(),dedup=None):
        self.preflight=ContentPreflight(blocked_words)
        self.dedup=dedup or DedupStore()
    def check(self,text,source="unknown",article_id=None):
        r=self.preflight.run(text)
        if not r.accepted: return GateDecision(False,r.reason,r.fingerprint)
        if self.dedup.seen(r.fingerprint):
            return GateDecision(False,"duplicate",r.fingerprint)
        self.dedup.remember(r.fingerprint,source,article_id)
        return GateDecision(True,"accepted",r.fingerprint)
