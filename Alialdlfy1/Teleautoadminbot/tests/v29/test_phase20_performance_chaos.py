import threading, time
from core.jobs.store import JobStore
from core.jobs.concurrency import ConcurrentWorkers
from core.infra.load import LoadHarness


def test_duplicate_enqueue_is_idempotent(tmp_path):
    s=JobStore(str(tmp_path/'j.sqlite3'))
    ids=[]
    for _ in range(20): ids.append(s.enqueue('x', {'n':1}, job_id='same'))
    assert len(s.list_jobs()) == 1 and len(set(ids)) == 1

def test_concurrent_workers_do_not_double_claim(tmp_path):
    s=JobStore(str(tmp_path/'j.sqlite3')); seen=[]; lock=threading.Lock()
    for i in range(30): s.enqueue('x', {'i':i}, job_id=f'j{i}')
    def handler(payload, job):
        time.sleep(0.001)
        with lock: seen.append(payload['i'])
    pool=ConcurrentWorkers(s, {'x':handler}, workers=6)
    res=pool.run(max_jobs=30, idle_rounds=3)
    assert sorted(seen)==list(range(30)); assert len(seen)==len(set(seen)); assert s.get_stats()['done']==30

def test_lease_recovery_after_worker_crash(tmp_path):
    s=JobStore(str(tmp_path/'j.sqlite3')); s.enqueue('x', {'a':1}, job_id='crash')
    job=s.claim('dead-worker'); assert job
    s.recover_expired(0)
    assert s.get('crash')['status']=='queued'

def test_load_harness(tmp_path):
    s=JobStore(str(tmp_path/'j.sqlite3'))
    class Q: store=s
    def factory(n): return ConcurrentWorkers(s, {'x':lambda p,j: None}, workers=n)
    h=LoadHarness(Q(), factory)
    r=h.run('x', lambda i:{'i':i}, 40, workers=4)
    assert r.processed==40 and r.done==40 and r.dead==0 and r.throughput>0

def test_chaos_matrix_is_present():
    assert {'provider_429','timeout','publish_crash','restart_recovery'} <= set(LoadHarness.chaos_matrix())
