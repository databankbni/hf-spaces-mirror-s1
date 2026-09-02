from core.storage.job_store import JobStore
import tempfile, pathlib

def test_queue_survives_reopen():
    with tempfile.TemporaryDirectory() as d:
        p=str(pathlib.Path(d)/"jobs.sqlite3")
        a=JobStore(p); jid=a.enqueue("x",{"v":1},job_id="j1")
        b=JobStore(p); j=b.claim("w1")
        assert j["id"]=="j1" and j["payload"]["v"]==1
        b.complete("j1")
        assert b.get("j1")["status"]=="done"

def test_failed_job_retries_then_dead():
    with tempfile.TemporaryDirectory() as d:
        s=JobStore(str(pathlib.Path(d)/"jobs.sqlite3"))
        jid=s.enqueue("x",{})
        j=s.claim("w")
        s.fail(jid,"bad",retry_delay=0,max_attempts=1)
        assert s.get(jid)["status"]=="dead"
