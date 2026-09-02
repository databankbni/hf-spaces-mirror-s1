import asyncio, os, sqlite3, tempfile
from pathlib import Path
from core.jobs.store import JobStore
from core.events.bus import EventBus
from core.plugins.registry import PluginRegistry, PluginSpec
from core.health.registry import HealthRegistry


def test_job_store_persists_and_recovers_stale():
    with tempfile.TemporaryDirectory() as td:
        db=str(Path(td)/'jobs.sqlite3'); store=JobStore(db)
        jid=store.enqueue('publish', {'article_id': 1})
        assert jid
        store.recover_stale()
        row=sqlite3.connect(db).execute("select status from jobs where id=?",(jid,)).fetchone()
        assert row[0]=='queued'

def test_plugin_registry():
    r=PluginRegistry(); r.register(PluginSpec('x','ai',secrets=['X_KEY']))
    assert r.get('x').secrets == ['X_KEY']

def test_health_registry():
    h=HealthRegistry(); h.set('db', True, 'ok'); assert h.snapshot()['db']['ok'] is True

def test_event_bus():
    seen=[]
    async def handler(**payload): seen.append(payload['x'])
    async def run():
        b=EventBus(); b.on('x',handler); await b.emit('x',x=7)
    asyncio.run(run()); assert seen==[7]
