from __future__ import annotations
import time, traceback
from dataclasses import dataclass
from threading import RLock
from typing import Callable

@dataclass
class SupervisedService:
    name: str
    start: Callable[[], None]
    stop: Callable[[], None]
    restart: Callable[[], None]
    is_alive: Callable[[], bool]
    failures: int = 0
    restarts: int = 0
    last_error: str = ""
    disabled: bool = False

class Supervisor:
    """Supervises services without taking control of their internal event loops."""
    def __init__(self, max_restarts: int = 5, backoff_seconds: float = 2.0):
        self.services: dict[str,SupervisedService]={}
        self.max_restarts=max_restarts
        self.backoff_seconds=backoff_seconds
        self._lock=RLock()

    def register(self, service: SupervisedService):
        with self._lock: self.services[service.name]=service

    def ensure(self, name: str) -> bool:
        with self._lock:
            s=self.services[name]
            if s.disabled: return False
        try:
            if s.is_alive(): return True
            if s.restarts >= self.max_restarts:
                s.disabled=True
                return False
            s.restart()
            s.restarts += 1
            time.sleep(min(self.backoff_seconds * (2 ** max(0,s.restarts-1)), 60))
            return bool(s.is_alive())
        except Exception as exc:
            s.failures += 1
            s.last_error=traceback.format_exc()[:4000]
            return False

    def run_once(self) -> dict[str,bool]:
        return {name:self.ensure(name) for name in list(self.services)}

    def reset(self,name:str):
        with self._lock:
            s=self.services[name]
            s.failures=0; s.restarts=0; s.last_error=""; s.disabled=False
