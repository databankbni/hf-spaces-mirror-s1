import json, sqlite3, sys
from pathlib import Path
from core.release.backup import BackupManager
from core.release.readiness import ProductionReadiness
from core.release.release import ReleaseManifest
from core.runtime.integration import RuntimeIntegration

def test_backup_is_atomic_and_verifiable(tmp_path):
    db=tmp_path/"state.sqlite3"
    with sqlite3.connect(db) as c:
        c.execute("create table t(id integer primary key, value text)")
        c.execute("insert into t(value) values('ok')")
    mgr=BackupManager(str(tmp_path),str(tmp_path/"backups"))
    r=mgr.create([str(db)],label="test")
    assert r.ok and r.verified and mgr.verify(r.path)
    assert Path(r.path).exists()

def test_readiness_detects_corrupt_database(tmp_path):
    db=tmp_path/"bad.sqlite3"; db.write_bytes(b"not sqlite")
    class Q: pass
    class S: pass
    s=S(); s.path=str(db); q=Q(); q.store=s
    class R: queue=q; db_path=str(db)
    r=ProductionReadiness(R()).evaluate()
    assert not r.ready
    assert any(x.code=="database_integrity" for x in r.findings)

def test_release_manifest_excludes_runtime_state(tmp_path):
    (tmp_path/"a.py").write_text("print('ok')")
    (tmp_path/"data").mkdir(); (tmp_path/"data"/"secret.db").write_text("x")
    m=ReleaseManifest(tmp_path).build(output=tmp_path/"manifest.json")
    paths=[x["path"] for x in m["files"]]
    assert "a.py" in paths and "data/secret.db" not in paths

def test_runtime_readiness_on_clean_temp_db(tmp_path):
    r=RuntimeIntegration(db_path=str(tmp_path/"runtime.sqlite3"), project_root=str(tmp_path))
    report=ProductionReadiness(r,str(tmp_path)).evaluate()
    assert report.ready, report.findings
