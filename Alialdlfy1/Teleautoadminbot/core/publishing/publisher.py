from __future__ import annotations
from typing import Callable, Optional
from .ledger import PublishLedger

class IdempotentPublisher:
    def __init__(self, ledger: PublishLedger, adapters: dict[str, Callable], lease_timeout: float = 300):
        self.ledger = ledger
        self.adapters = adapters
        self.lease_timeout = float(lease_timeout)

    def publish(self, target: str, article_id: str, content: str, **kwargs):
        self.ledger.recover_stale(self.lease_timeout)
        record = self.ledger.begin(target, article_id, content)

        # Already completed: never publish again.
        if record["status"] == "published":
            return {"status": "already_published", "remote_id": record["remote_id"]}

        # Another worker is publishing it. Avoid duplicate remote calls.
        if record["status"] == "publishing":
            return {"status": "in_progress", "remote_id": record["remote_id"]}

        adapter = self.adapters[target]
        key = record["idempotency_key"]
        if not self.ledger.claim_attempt(key):
            latest = self.ledger.get(key) or {}
            if latest.get("status") == "published":
                return {"status": "already_published", "remote_id": latest.get("remote_id")}
            return {"status": "in_progress", "remote_id": latest.get("remote_id")}
        try:
            result = adapter(content, idempotency_key=key, **kwargs)
            remote_id = result.get("remote_id") if isinstance(result, dict) else None
            self.ledger.mark_published(key, remote_id)
            return {"status": "published", "remote_id": remote_id, "result": result}
        except Exception as exc:
            self.ledger.mark_failed(key, str(exc))
            raise
