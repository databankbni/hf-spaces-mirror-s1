from core.publishing.ledger import PublishLedger
from core.publishing.publisher import IdempotentPublisher
import tempfile, pathlib

def test_same_article_target_is_idempotent():
    with tempfile.TemporaryDirectory() as d:
        s=PublishLedger(str(pathlib.Path(d)/"db.sqlite3"))
        calls=[]
        def adapter(content, **kw):
            calls.append(kw["idempotency_key"])
            return {"remote_id":"R1"}
        p=IdempotentPublisher(s, {"blogger":adapter})
        a=p.publish("blogger","a1","hello")
        b=p.publish("blogger","a1","hello")
        assert a["status"]=="published"
        assert b["status"]=="already_published"
        assert len(calls)==1

def test_failed_publish_can_retry():
    with tempfile.TemporaryDirectory() as d:
        s=PublishLedger(str(pathlib.Path(d)/"db.sqlite3"))
        calls=[]
        def adapter(content, **kw):
            calls.append(1)
            if len(calls)==1: raise RuntimeError("temporary")
            return {"remote_id":"R2"}
        p=IdempotentPublisher(s, {"blogger":adapter})
        try: p.publish("blogger","a2","hello")
        except RuntimeError: pass
        r=p.publish("blogger","a2","hello")
        assert r["status"]=="published"
        assert len(calls)==2
