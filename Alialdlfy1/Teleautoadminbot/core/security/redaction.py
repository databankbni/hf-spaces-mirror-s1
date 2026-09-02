from __future__ import annotations
import re

_SECRET_PATTERNS=(
    re.compile(r'(?i)(api[_-]?key|token|secret|password|credential)\s*[:=]\s*[^\s,;]+'),
    re.compile(r'(?i)bearer\s+[A-Za-z0-9._-]+'),
)

def redact(text:str)->str:
    out=str(text)
    for p in _SECRET_PATTERNS:
        out=p.sub(lambda m: m.group(0).split(":")[0].split("=")[0]+"=<REDACTED>",out)
    return out


def redact_mapping(mapping):
    if not isinstance(mapping, dict):
        return redact(mapping)
    return {k: ("<REDACTED>" if re.search(r'(?i)(api[_-]?key|token|secret|password|credential)', str(k)) else redact(v)) for k,v in mapping.items()}
