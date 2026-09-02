from core.repair.policy import RepairGuard, RepairPolicy

def test_protected_files_blocked():
    g=RepairGuard()
    ok,risk,msg=g.authorize("i1",["core/secret_manager.py"],True)
    assert not ok and risk=="blocked"

def test_medium_requires_admin():
    g=RepairGuard(RepairPolicy(cooldown_seconds=0))
    ok,risk,msg=g.authorize("i1",["core/foo.py"],False)
    assert not ok and "approval" in msg
    ok,risk,msg=g.authorize("i1",["core/foo.py"],True)
    assert ok

def test_button_set_is_additive():
    from core.control.repair_buttons import REPAIR_BUTTONS
    keys=[x.key for x in REPAIR_BUTTONS]
    assert "repair_status" in keys and "repair_rollback" in keys
