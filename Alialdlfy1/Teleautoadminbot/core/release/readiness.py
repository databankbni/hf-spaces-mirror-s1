from __future__ import annotations
import os, sqlite3, sys, time
from dataclasses import dataclass, asdict
from pathlib import Path

@dataclass(frozen=True)
class ReadinessFinding:
    code: str
    severity: str
    detail: str

@dataclass(frozen=True)
class ReadinessReport:
    ready: bool
    findings: tuple[ReadinessFinding, ...]
    checks: dict
    generated_at: float

class ProductionReadiness:
    """Deterministic preflight gate; never mutates runtime state."""
    def __init__(self, runtime=None, project_root="."):
        self.runtime=runtime; self.root=Path(project_root)

    def _db_check(self, path):
        p=Path(path)
        if not p.exists(): return False, "database_missing"
        try:
            with sqlite3.connect(p, timeout=5) as c:
                row=c.execute("PRAGMA integrity_check").fetchone()
                return bool(row and row[0]=="ok"), str(row[0] if row else "unknown")
        except Exception as exc:return False, str(exc)[:200]

    def evaluate(self, require_secrets: tuple[str,...]=()) -> ReadinessReport:
        findings=[]; checks={}
        if sys.version_info < (3,10): findings.append(ReadinessFinding("python_version","critical",sys.version.split()[0]))
        checks["python_version"]=sys.version.split()[0]
        db_path=getattr(getattr(self.runtime,"queue",None),"store",None)
        db_path=getattr(db_path,"path",None) or getattr(self.runtime,"db_path",None)
        if db_path:
            ok,detail=self._db_check(db_path); checks["database_integrity"]=detail
            if not ok: findings.append(ReadinessFinding("database_integrity","critical",detail))
        if self.runtime is not None:
            try:
                stats=self.runtime.queue.store.get_stats(); checks["queue"]=stats
                if stats.get("running",0): findings.append(ReadinessFinding("running_jobs","warning",str(stats["running"])))
            except Exception as exc: findings.append(ReadinessFinding("queue_check","critical",str(exc)[:200]))
            try:
                health=self.runtime.health_snapshot(); checks["health"]=health
                bad=[k for k,v in health.items() if v.get("status")=="unhealthy"]
                if bad: findings.append(ReadinessFinding("unhealthy_services","critical",",".join(bad)))
            except Exception as exc: findings.append(ReadinessFinding("health_check","critical",str(exc)[:200]))
            try:
                sf=self.runtime.security.validate_environment(require_secrets)
                checks["security_findings"]=[asdict(x) for x in sf]
                findings.extend(ReadinessFinding(x.code,x.severity,x.detail) for x in sf)
            except Exception as exc: findings.append(ReadinessFinding("security_check","critical",str(exc)[:200]))
        for name in require_secrets:
            if not os.getenv(name): findings.append(ReadinessFinding("missing_secret","critical",name))
        critical=any(x.severity=="critical" for x in findings)
        return ReadinessReport(not critical,tuple(findings),checks,time.time())

    def assert_ready(self, **kwargs):
        report=self.evaluate(**kwargs)
        if not report.ready:
            raise RuntimeError("P29 production readiness failed: " + "; ".join(f"{x.code}:{x.detail}" for x in report.findings if x.severity=="critical"))
        return report
