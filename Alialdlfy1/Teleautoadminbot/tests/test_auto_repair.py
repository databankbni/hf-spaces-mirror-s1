from core.repair.sandbox import PatchSandbox
from core.repair.engine import AutoRepairEngine
import tempfile, pathlib

PATCH = """--- a/repair_test.py
+++ b/repair_test.py
@@ -1 +1 @@
-value = 1
+value = 2
"""

def test_sandbox_accepts_safe_patch():
    with tempfile.TemporaryDirectory() as d:
        p=pathlib.Path(d); (p/"repair_test.py").write_text("value = 1\n")
        s=PatchSandbox(d)
        r=s.test(PATCH)
        assert r.passed

def test_sandbox_rejects_secret_paths():
    with tempfile.TemporaryDirectory() as d:
        p=pathlib.Path(d); (p/"secrets.py").write_text("x=1\n")
        patch="""--- a/secrets.py
+++ b/secrets.py
@@ -1 +1 @@
-x=1
+x=2
"""
        r=PatchSandbox(d).test(patch)
        assert not r.passed

def test_apply_and_rollback():
    with tempfile.TemporaryDirectory() as d:
        p=pathlib.Path(d); f=p/"repair_test.py"; f.write_text("value = 1\n")
        e=AutoRepairEngine(d, str(p/"backups"))
        rec,res=e.propose_and_test(PATCH)
        assert rec.status=="approved"
        e.apply_approved(rec,res.sandbox_dir)
        assert f.read_text()=="value = 2\n"
        e.rollback(rec)
        assert f.read_text()=="value = 1\n"
