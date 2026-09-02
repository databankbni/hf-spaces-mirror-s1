from __future__ import annotations
import hashlib, re
from dataclasses import dataclass

@dataclass(frozen=True)
class PreflightResult:
    accepted: bool
    reason: str
    cleaned: str
    fingerprint: str

class ContentPreflight:
    """Zero-AI-cost gate: blocked words and exact/normalized duplicates run first."""
    def __init__(self, blocked_words=()):
        self.blocked={str(x).strip().casefold() for x in blocked_words if str(x).strip()}

    @staticmethod
    def normalize(text):
        return re.sub(r'\s+',' ',re.sub(r'[^\w\s]',' ',str(text),flags=re.UNICODE)).strip().casefold()

    def fingerprint(self,text):
        return hashlib.sha256(self.normalize(text).encode("utf-8")).hexdigest()

    def run(self,text,seen_fingerprints=None):
        raw=str(text)
        norm=self.normalize(raw)
        hits=[w for w in self.blocked if w in norm]
        if hits:
            return PreflightResult(False,"blocked_word:"+hits[0],raw,self.fingerprint(raw))
        fp=self.fingerprint(raw)
        if seen_fingerprints is not None and fp in seen_fingerprints:
            return PreflightResult(False,"duplicate",raw,fp)
        cleaned=raw
        return PreflightResult(True,"accepted",cleaned,fp)
