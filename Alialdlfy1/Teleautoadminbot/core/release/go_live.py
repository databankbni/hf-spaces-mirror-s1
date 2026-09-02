from __future__ import annotations
import importlib.util
import os
import time
from dataclasses import dataclass, asdict
from typing import Any

@dataclass
class GoLiveCheck:
    name: str
    ok: bool
    detail: str = ""
    critical: bool = True

class GoLiveGate:
    """Final release gate. External Telegram credentials are never required for dry-run CI."""
    def __init__(self, app):
        self.app = app

    def checks(self, require_telegram: bool = False) -> list[GoLiveCheck]:
        out: list[GoLiveCheck] = []
        report = self.app.production_readiness()
        out.append(GoLiveCheck("production_readiness", report.ready, "; ".join(f.detail for f in report.findings)))
        out.append(GoLiveCheck("sqlite_integrity", self._sqlite_integrity(), "runtime databases integrity"))
        out.append(GoLiveCheck("plugins", set(self.app.discover_plugins()) >= {"blogger", "news", "sports"}, str(self.app.discover_plugins())))
        out.append(GoLiveCheck("telegram_dependency", self._pyrogram_available(), "pyrogram import" , critical=require_telegram))
        if require_telegram:
            out.append(GoLiveCheck("telegram_credentials", bool(os.getenv("API_ID")) and bool(os.getenv("API_HASH")), "API_ID/API_HASH present"))
        return out

    def evaluate(self, require_telegram: bool = False) -> dict[str, Any]:
        checks = self.checks(require_telegram=require_telegram)
        blocking = [c for c in checks if c.critical and not c.ok]
        return {"ready": not blocking, "checks": [asdict(c) for c in checks], "timestamp": time.time()}

    def _sqlite_integrity(self) -> bool:
        try:
            import sqlite3
            paths = {str(self.app.settings.db_path), str(self.app.runtime.db_path)}
            for path in paths:
                if not os.path.exists(path):
                    continue
                with sqlite3.connect(path) as c:
                    if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        return False
            return True
        except Exception:
            return False

    @staticmethod
    def _pyrogram_available() -> bool:
        return importlib.util.find_spec("pyrogram") is not None
