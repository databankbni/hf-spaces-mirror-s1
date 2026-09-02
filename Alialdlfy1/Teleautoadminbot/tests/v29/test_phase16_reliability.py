import tempfile
from pathlib import Path

from core.runtime.integration import RuntimeIntegration
from core.providers.pool import AIProviderPool
from core.ai.gateway import AIGateway


def make_rt(td):
    pool = AIProviderPool({"GEMINI_KEY_1": "k1"})
    ai = AIGateway(pool, {"gemini": lambda key, payload: {"body": "ok"}})
    return RuntimeIntegration(db_path=str(Path(td) / "runtime.sqlite3"), ai_gateway=ai)


def test_section_state_persists_across_restart():
    with tempfile.TemporaryDirectory() as td:
        rt = make_rt(td)
        rt.set_section_state("news", enabled=False, blocked_words=["x"], sources=["wire"], duplicate_protection=False)
        rt2 = make_rt(td)
        state = rt2.get_section_state("news")
        assert state["enabled"] is False
        assert state["blocked_words"] == ["x"]
        assert state["sources"] == ["wire"]
        assert state["duplicate_protection"] is False


def test_source_allowlist_rejects_before_queue():
    with tempfile.TemporaryDirectory() as td:
        rt = make_rt(td)
        rt.set_section_state("news", sources=["trusted"])
        r = rt.ingest("news", "hello", "1", source="unknown")
        assert r.status == "rejected"
        assert r.reason == "source_not_allowed"
        assert rt.queue.store.get_stats()["queued"] == 0


def test_duplicate_protection_toggle_is_honored():
    with tempfile.TemporaryDirectory() as td:
        rt = make_rt(td)
        rt.set_section_state("news", duplicate_protection=False)
        a = rt.ingest("news", "same", "1", source="x", source_url="https://x/1")
        b = rt.ingest("news", "same", "2", source="x", source_url="https://x/1")
        assert a.status == "queued"
        assert b.status == "queued"


def test_worker_heartbeat_keeps_lease_alive():
    from core.jobs.worker import JobWorker
    from core.storage.job_store import JobStore
    import threading, time
    with tempfile.TemporaryDirectory() as td:
        store = JobStore(str(Path(td) / "jobs.sqlite3"))
        jid = store.enqueue("slow", {})
        started = threading.Event()
        release = threading.Event()
        def handler(payload, job):
            started.set()
            release.wait(1.2)
        worker = JobWorker(store, {"slow": handler}, worker_id="w", lease_timeout=0.6, heartbeat_interval=0.1)
        t = threading.Thread(target=worker.run_once)
        t.start()
        assert started.wait(1)
        time.sleep(0.8)
        assert store.recover_expired(timeout=0.6) == 0
        release.set()
        t.join(2)
        assert store.get(jid)["status"] == "done"
