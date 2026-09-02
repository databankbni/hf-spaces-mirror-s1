import tempfile, os
from core.app import App
from core.control.section_control import ControlPlaneControl

def test_control_plane_snapshot_and_alerts():
    with tempfile.TemporaryDirectory() as d:
        app=App(project_root=d)
        snap=app.runtime.operational_snapshot()
        assert set(snap['sections'])=={'news','sports','blogger'}
        assert 'queue' in snap and 'alerts' in snap and 'providers' in snap

def test_detailed_metrics_preserves_legacy_api():
    with tempfile.TemporaryDirectory() as d:
        app=App(project_root=d)
        app.runtime.metrics.inc('x',2); app.runtime.metrics.observe('pipeline',0.5)
        assert app.runtime.metrics_snapshot()['x']==2
        assert app.runtime.metrics.detailed_snapshot()['latency']['pipeline']['count']==1

def test_global_control_callbacks_admin_gate():
    with tempfile.TemporaryDirectory() as d:
        app=App(project_root=d)
        c=ControlPlaneControl(app.runtime, admin_check=lambda uid: uid==7)
        assert c.handle('control:overview',7)['ok']
        assert c.handle('control:providers',7)['ok']
        assert c.handle('control:audit',6)['reason']=='admin_required'
        assert c.handle('control:audit',7)['ok']

def test_dead_letter_alert():
    with tempfile.TemporaryDirectory() as d:
        app=App(project_root=d)
        jid=app.runtime.queue.store.enqueue('x',{'safe':True},job_id='dead-1')
        app.runtime.queue.store.fail(jid,'boom',max_attempts=0)
        alerts=app.runtime.control_plane.evaluate()
        assert any(a['key']=='queue.dead' for a in alerts)
