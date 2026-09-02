from __future__ import annotations
import os, socket, time, traceback, threading
from typing import Callable
from core.storage.job_store import JobStore


class JobWorker:
    def __init__(self, store: JobStore, handlers: dict[str, Callable], worker_id=None, lease_timeout=300, heartbeat_interval=None):
        self.store=store
        self.handlers=handlers
        self.worker_id=worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.running=True
        self.lease_timeout=float(lease_timeout)
        self.heartbeat_interval=float(heartbeat_interval or max(1.0, self.lease_timeout/3.0))

    def stop(self): self.running=False

    def _heartbeat(self, job_id, stop_event):
        while not stop_event.wait(self.heartbeat_interval):
            try:
                self.store.heartbeat(job_id, self.worker_id)
            except Exception:
                break

    def run_once(self) -> bool:
        self.store.recover_expired(self.lease_timeout)
        job=self.store.claim(self.worker_id)
        if not job: return False
        stop_event=threading.Event()
        heartbeat=threading.Thread(target=self._heartbeat, args=(job["id"], stop_event), daemon=True)
        heartbeat.start()
        try:
            handler=self.handlers[job["kind"]]
            handler(job["payload"], job)
            self.store.complete(job["id"], worker_id=self.worker_id)
        except Exception as exc:
            self.store.fail(job["id"], traceback.format_exc())
        finally:
            stop_event.set()
            heartbeat.join(timeout=1)
        return True

    def run_forever(self, idle_sleep=1.0):
        while self.running:
            if not self.run_once(): time.sleep(idle_sleep)
