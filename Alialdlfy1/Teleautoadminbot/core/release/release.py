from __future__ import annotations
import hashlib, json, os, time
from pathlib import Path

class ReleaseManifest:
    """Reproducible release manifest without exposing environment secret values."""
    def __init__(self, root="."):
        self.root=Path(root)
    def build(self, version="29.0", phase="23", output=None):
        files=[]
        for p in sorted(self.root.rglob("*")):
            if not p.is_file() or any(part in {".git","__pycache__","data","backups"} for part in p.parts): continue
            if p.name.endswith(".pyc"): continue
            h=hashlib.sha256(p.read_bytes()).hexdigest()
            files.append({"path":str(p.relative_to(self.root)),"sha256":h,"size":p.stat().st_size})
        doc={"product":"P29","version":version,"phase":str(phase),"generated_at":time.time(),"python_min":"3.10","files":files}
        if output:
            out=Path(output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(doc,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
        return doc
