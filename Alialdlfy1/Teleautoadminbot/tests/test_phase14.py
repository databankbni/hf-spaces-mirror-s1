from core.content.preflight import ContentPreflight
from core.content.orchestrator import ContentGate
from core.infra.rate_limiter import ProviderLimiter
from core.security.redaction import redact
import tempfile, pathlib

def test_blocked_before_ai():
    p=ContentPreflight(["forbidden"])
    r=p.run("hello forbidden world")
    assert not r.accepted and r.reason.startswith("blocked_word")

def test_dedup_persistent():
    with tempfile.TemporaryDirectory() as d:
        g=ContentGate(dedup=__import__("core.content.dedup",fromlist=["DedupStore"]).DedupStore(str(pathlib.Path(d)/"x.db")))
        assert g.check("Same article","news","1").accepted
        assert not g.check("Same article","news","2").accepted

def test_rate_limiter_and_redaction():
    p=ProviderLimiter(); p.configure("x",100,1); p.acquire("x")
    assert "<REDACTED>" in redact("api_key=SECRET123")
