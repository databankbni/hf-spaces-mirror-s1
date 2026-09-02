from __future__ import annotations
import json,time
from pathlib import Path
from core.security.redaction import redact
class AuditLog:
    def __init__(self,path="data/audit.jsonl"):self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
    def write(self,event,**data):
        row={"ts":time.time(),"event":event,**data}
        with self.path.open("a",encoding="utf-8") as f:f.write(json.dumps({k:redact(v) if isinstance(v,str) else v for k,v in row.items()},ensure_ascii=False)+"\n")
    def recent(self,limit=50):
        if not self.path.exists():return []
        out=[]
        for line in self.path.read_text(encoding="utf-8",errors="replace").splitlines()[-max(1,min(500,int(limit))):][::-1]:
            try:out.append(json.loads(line))
            except Exception:pass
        return out
