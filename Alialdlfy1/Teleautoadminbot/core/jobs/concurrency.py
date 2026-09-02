from __future__ import annotations
import threading, time
from dataclasses import dataclass
from typing import Callable
from core.jobs.worker import JobWorker

@dataclass
class WorkerRunResult:
    worker_id: str
    processed: int = 0
    errors: int = 0
    duration: float = 0.0

class ConcurrentWorkers:
    """Small, dependency-free worker pool for bounded parallel queue processing."""
    def __init__(self, store, handlers: dict[str, Callable], workers: int = 2, lease_timeout=300):
        self.store = store
        self.handlers = handlers
        self.workers = max(1, min(32, int(workers)))
        self.lease_timeout = lease_timeout

    def run(self, max_jobs: int | None = None, idle_rounds: int = 1, idle_sleep: float = 0.01) -> list[WorkerRunResult]:
        lock = threading.Lock()
        remaining = [None if max_jobs is None else max(0, int(max_jobs))]
        results: list[WorkerRunResult] = []
        def loop(idx: int):
            worker = JobWorker(self.store, self.handlers, worker_id=f"p29-pool-{idx}-{threading.get_ident()}", lease_timeout=self.lease_timeout)
            r = WorkerRunResult(worker.worker_id); start = time.monotonic()
            idle = 0
            while idle < max(1, idle_rounds):
                with lock:
                    if remaining[0] is not None and remaining[0] <= 0: break
                    if remaining[0] is not None: remaining[0] -= 1
                got = worker.run_once()
                if got:
                    r.processed += 1; idle = 0
                else:
                    if remaining[0] is not None:
                        with lock: remaining[0] += 1
                    idle += 1
                    if idle < idle_rounds: time.sleep(idle_sleep)
            r.duration = time.monotonic() - start
            with lock: results.append(r)
        threads = [threading.Thread(target=loop, args=(i,), daemon=True) for i in range(self.workers)]
        for t in threads: t.start()
        for t in threads: t.join()
        return sorted(results, key=lambda x: x.worker_id)
