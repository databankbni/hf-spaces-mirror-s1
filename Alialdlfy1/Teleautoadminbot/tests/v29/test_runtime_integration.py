import pathlib
import tempfile

from core.runtime.integration import RuntimeIntegration
from core.ai.gateway import AIGateway
from core.providers.pool import AIProviderPool


def make_runtime(td, ai_adapter=None, publisher_adapter=None):
    db = pathlib.Path(td) / "runtime.sqlite3"
    pool = AIProviderPool({"GEMINI_KEY_1": "k1", "GEMINI_KEY_2": "k2"})
    gateway = AIGateway(pool, {"gemini": ai_adapter} if ai_adapter else {})
    rt = RuntimeIntegration(db_path=str(db), ai_gateway=gateway)
    if publisher_adapter:
        rt.register_publisher("news", publisher_adapter)
        rt.register_publisher("sports", publisher_adapter)
        rt.register_publisher("blogger", publisher_adapter)
    return rt


def test_blocked_never_enters_queue_or_ai():
    calls = []
    def ai(key, payload):
        calls.append(1)
        return {"body": "ok"}
    with tempfile.TemporaryDirectory() as td:
        rt = make_runtime(td, ai)
        rt.set_section_state("news", blocked_words=["forbidden"])
        r = rt.ingest("news", "hello forbidden", "1", source="x")
        assert r.status == "rejected"
        assert rt.queue.store.get_stats()["queued"] == 0
        assert calls == []


def test_duplicate_is_persistent_before_ai_and_queue():
    calls = []
    def ai(key, payload):
        calls.append(1)
        return {"body": "ok"}
    with tempfile.TemporaryDirectory() as td:
        rt = make_runtime(td, ai)
        a = rt.ingest("news", "same article", "1", source="x", source_url="https://x/1")
        b = rt.ingest("news", "same article", "2", source="x", source_url="https://x/1")
        assert a.status == "queued"
        assert b.status == "rejected"
        assert b.reason == "duplicate"
        assert calls == []


def test_full_runtime_batch_and_idempotent_publish():
    ai_calls = []
    publish_calls = []
    def ai(key, payload):
        ai_calls.append(payload)
        return {
            "title": "T", "body": "B", "summary": "S",
            "keywords": ["k"], "hashtags": ["#h"],
        }
    def pub(content, **kwargs):
        publish_calls.append(kwargs["idempotency_key"])
        return {"remote_id": "R1"}
    with tempfile.TemporaryDirectory() as td:
        rt = make_runtime(td, ai, pub)
        queued = rt.ingest("sports", "raw", "1", source="sports", target="sports")
        assert queued.status == "queued"
        worker = rt.build_worker("w1")
        assert worker.run_once() is True
        assert len(ai_calls) == 1
        assert len(publish_calls) == 1
        # Re-running the same job id after a restart cannot produce a second publish.
        assert rt.publisher.publish("sports", "sports:1", "B")["status"] == "already_published"
        assert len(publish_calls) == 1


def test_worker_recovery_after_stale_claim():
    with tempfile.TemporaryDirectory() as td:
        rt = make_runtime(td, lambda k, p: {"body": "B"}, lambda c, **k: {"remote_id": "R"})
        q = rt.queue.store
        jid = q.enqueue("article.process", {"section": "news", "article": "x", "article_id": "news:1", "target": "news"})
        claimed = q.claim("crashed-worker")
        assert claimed["id"] == jid
        assert q.recover_expired(timeout=0) >= 1
        assert q.claim("restarted-worker")["id"] == jid


def test_job_store_migrates_legacy_jobs_schema():
    import sqlite3
    from core.storage.job_store import JobStore
    with tempfile.TemporaryDirectory() as td:
        db = pathlib.Path(td) / "legacy.sqlite3"
        with sqlite3.connect(db) as c:
            c.execute("""CREATE TABLE jobs(
                id TEXT PRIMARY KEY, type TEXT NOT NULL, payload TEXT NOT NULL,
                status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 5, run_after TEXT NOT NULL,
                locked_by TEXT, locked_at TEXT, last_error TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            c.execute("""INSERT INTO jobs VALUES
                ('legacy-1','article.process','{"article":"x"}','queued',0,5,
                 '2030-01-01T00:00:00+00:00',NULL,NULL,NULL,
                 '2030-01-01T00:00:00+00:00','2030-01-01T00:00:00+00:00')""")
        store = JobStore(str(db))
        assert store.get("legacy-1")["kind"] == "article.process"
        assert store.get_stats()["queued"] == 1
