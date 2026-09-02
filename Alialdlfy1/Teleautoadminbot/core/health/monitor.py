from __future__ import annotations
from dataclasses import dataclass, field
from time import monotonic
from threading import RLock
from typing import Callable, Any

@dataclass
class ServiceHealth:
    name: str
    status: str = "unknown"
    consecutive_failures: int = 0
    last_error: str = ""
    last_ok: float = 0.0
    last_check: float = 0.0
    metadata: dict = field(default_factory=dict)

class HealthMonitor:
    """Lightweight health registry. Checks are injected so providers remain decoupled."""
    def __init__(self, on_unhealthy: Callable[[str, ServiceHealth], Any] | None = None):
        self.on_unhealthy = on_unhealthy
        self._services: dict[str, ServiceHealth] = {}
        self._checks: dict[str, Callable[[], Any]] = {}
        self._lock=RLock()

    def register(self, name: str, check: Callable[[], Any]):
        with self._lock:
            self._services.setdefault(name, ServiceHealth(name))
            self._checks[name]=check

    def check(self, name: str) -> ServiceHealth:
        with self._lock:
            service=self._services.setdefault(name, ServiceHealth(name))
            check=self._checks[name]
        try:
            result=check()
            with self._lock:
                service.status="healthy"
                service.consecutive_failures=0
                service.last_error=""
                service.last_ok=monotonic()
                service.last_check=monotonic()
                if isinstance(result,dict): service.metadata=result
                return service
        except Exception as exc:
            with self._lock:
                service.status="unhealthy"
                service.consecutive_failures += 1
                service.last_error=str(exc)[:2000]
                service.last_check=monotonic()
                if self.on_unhealthy:
                    try:
                        self.on_unhealthy(name, service)
                    except Exception:
                        pass
                return service

    def check_all(self) -> dict[str, ServiceHealth]:
        return {name:self.check(name) for name in list(self._checks)}

    def snapshot(self):
        with self._lock:
            return {n:s.__dict__.copy() for n,s in self._services.items()}
