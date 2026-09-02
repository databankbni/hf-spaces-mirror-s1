from __future__ import annotations
import time
from dataclasses import dataclass, asdict

@dataclass
class LoadResult:
    submitted: int
    processed: int
    queued: int
    done: int
    dead: int
    elapsed: float
    throughput: float

class LoadHarness:
    """Deterministic in-process load/chaos harness; no external services required."""
    def __init__(self, queue, worker_pool_factory):
        self.queue = queue
        self.worker_pool_factory = worker_pool_factory

    def submit(self, kind, payload_factory, count: int):
        for i in range(max(0, int(count))):
            self.queue.store.enqueue(kind, payload_factory(i), job_id=f"load:{kind}:{i}")

    def run(self, kind, payload_factory, count: int, workers: int = 4) -> LoadResult:
        count = max(0, int(count)); self.submit(kind, payload_factory, count)
        start = time.monotonic()
        pool = self.worker_pool_factory(workers)
        results = pool.run(max_jobs=count, idle_rounds=2)
        elapsed = max(1e-9, time.monotonic() - start)
        stats = self.queue.store.get_stats()
        processed = sum(r.processed for r in results)
        return LoadResult(count, processed, stats.get('queued',0), stats.get('done',0), stats.get('dead',0), elapsed, processed/elapsed)

    @staticmethod
    def chaos_matrix() -> list[str]:
        return ['duplicate_enqueue','concurrent_claim','worker_crash','lease_expiry','provider_429','provider_5xx','timeout','publish_crash','restart_recovery']

    def snapshot(self):
        return asdict(self.queue.store.get_stats())
