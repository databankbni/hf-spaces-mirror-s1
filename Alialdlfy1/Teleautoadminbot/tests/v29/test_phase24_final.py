import tempfile
from pathlib import Path

from core.app import App
from core.runtime.integration import RuntimeResult


def test_final_go_live_dry_run_and_plugins(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.chdir(d)
        app = App(project_root=d)
        report = app.go_live_report(require_telegram=False)
        assert report["ready"]
        assert {"blogger", "news", "sports"}.issubset(app.discover_plugins())


def test_final_end_to_end_all_sections_without_external_services(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.chdir(d)
        monkeypatch.setenv("GEMINI_KEY_99", "TEST_FINAL_KEY")
        app = App(project_root=d)
        calls = []

        def ai_adapter(key, payload):
            return {"title": payload["article"], "article": payload["article"], "summary": payload["article"], "keywords": [], "hashtags": []}

        def publish(content, **kwargs):
            calls.append((kwargs.get("section"), kwargs.get("idempotency_key")))
            return {"remote_id": f"remote-{len(calls)}"}

        app.register_ai_provider("gemini", ai_adapter)
        for section in ("news", "sports", "blogger"):
            app.register_publisher(section, publish)
            r = app.runtime.ingest(section, f"unique {section} article", f"id-{section}", target=section)
            assert r.status == "queued"
            job = app.runtime.queue.store.claim("final-test")
            assert job
            result = app.runtime.handle_job(job["payload"], job)
            assert result.status in {"published", "already_published"}
            app.runtime.queue.store.complete(job["id"], worker_id="final-test")
        assert len(calls) == 3


def test_final_idempotency_race_is_single_claim():
    with tempfile.TemporaryDirectory() as d:
        from core.publishing.ledger import PublishLedger
        from core.publishing.publisher import IdempotentPublisher
        ledger = PublishLedger(str(Path(d) / "p.sqlite3"))
        calls = []
        def adapter(content, **kwargs):
            calls.append(1)
            return {"remote_id": "r1"}
        p = IdempotentPublisher(ledger, {"x": adapter})
        first = p.publish("x", "a", "body")
        second = p.publish("x", "a", "body")
        assert first["status"] == "published"
        assert second["status"] == "already_published"
        assert len(calls) == 1
