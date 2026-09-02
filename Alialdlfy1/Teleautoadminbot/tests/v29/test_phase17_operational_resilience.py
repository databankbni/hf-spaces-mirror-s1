import sqlite3
import tempfile
import time
from pathlib import Path

from core.publishing.ledger import PublishLedger
from core.publishing.publisher import IdempotentPublisher
from core.storage.job_store import JobStore
from core.runtime.integration import RuntimeIntegration
from core.providers.pool import AIProviderPool
from core.ai.gateway import AIGateway
from core.control.section_control import SectionControl


def test_publish_ledger_migrates_existing_schema():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "jobs.sqlite3"
        c = sqlite3.connect(path)
        c.execute("""CREATE TABLE publish_ledger(
            idempotency_key TEXT PRIMARY KEY, target TEXT NOT NULL, article_id TEXT NOT NULL,
            content_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', remote_id TEXT,
            attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, created_at REAL NOT NULL,
            updated_at REAL NOT NULL, UNIQUE(target, article_id))""")
        c.commit(); c.close()
        ledger = PublishLedger(str(path))
        cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(publish_ledger)")}
        assert "attempt_started_at" in cols


def test_stale_publish_lease_is_recovered_and_idempotency_key_reused():
    with tempfile.TemporaryDirectory() as td:
        ledger = PublishLedger(str(Path(td) / "jobs.sqlite3"))
        calls = []
        def adapter(content, idempotency_key, **kwargs):
            calls.append(idempotency_key)
            return {"remote_id": "remote-1"}
        publisher = IdempotentPublisher(ledger, {"news": adapter}, lease_timeout=1)
        first = ledger.begin("news", "article-1", "hello")
        ledger.mark_attempt(first["idempotency_key"])
        with ledger._conn() as c:
            c.execute("UPDATE publish_ledger SET attempt_started_at=?, updated_at=? WHERE idempotency_key=?", (time.time()-10, time.time()-10, first["idempotency_key"]))
        result = publisher.publish("news", "article-1", "hello")
        assert result["status"] == "published"
        assert len(calls) == 1
        assert calls[0] == first["idempotency_key"]


def test_published_operation_never_calls_remote_adapter_twice():
    with tempfile.TemporaryDirectory() as td:
        ledger = PublishLedger(str(Path(td) / "jobs.sqlite3"))
        calls = []
        def adapter(content, idempotency_key, **kwargs):
            calls.append(1)
            return {"remote_id": "r"}
        publisher = IdempotentPublisher(ledger, {"news": adapter})
        assert publisher.publish("news", "a", "x")["status"] == "published"
        assert publisher.publish("news", "a", "x")["status"] == "already_published"
        assert len(calls) == 1


def test_dead_letter_can_be_requeued():
    with tempfile.TemporaryDirectory() as td:
        store = JobStore(str(Path(td) / "jobs.sqlite3"))
        jid = store.enqueue("x", {})
        job = store.claim("worker")
        store.fail(jid, "boom", max_attempts=1)
        assert store.get(jid)["status"] == "dead"
        assert store.requeue_dead(jid)
        assert store.get(jid)["status"] == "queued"


def test_runtime_auto_repair_toggle_persists():
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "runtime.sqlite3")
        pool = AIProviderPool({"GEMINI_KEY_1": "k"})
        ai = AIGateway(pool, {"gemini": lambda key, payload: {"body": "ok"}})
        rt = RuntimeIntegration(db_path=db, ai_gateway=ai)
        rt.set_auto_repair(False)
        rt2 = RuntimeIntegration(db_path=db, ai_gateway=ai)
        assert rt2.control_snapshot()["auto_repair"]["enabled"] is False


def test_control_exposes_metrics_health_and_dead_letters_without_payload():
    with tempfile.TemporaryDirectory() as td:
        pool = AIProviderPool({"GEMINI_KEY_1": "k"})
        ai = AIGateway(pool, {"gemini": lambda key, payload: {"body": "ok"}})
        rt = RuntimeIntegration(db_path=str(Path(td) / "runtime.sqlite3"), ai_gateway=ai)
        control = SectionControl(rt)
        assert control.handle("news:metrics")["ok"]
        assert control.handle("news:health")["ok"]
        result = control.handle("news:dead")
        assert result["ok"] and "jobs" in result
        assert all("payload" not in j for j in result["jobs"])
