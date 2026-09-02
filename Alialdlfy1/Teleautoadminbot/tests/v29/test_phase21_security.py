import os, sqlite3
from cryptography.fernet import Fernet
from core.security.hardening import SecurityHardener
from core.security.access import AccessController
from core.security.secret_registry import SecretRegistry
from core.secrets.manager import SecretManager

def test_secret_values_are_redacted_and_detected(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-value")
    r=SecretRegistry(); h=SecurityHardener(r); assert h.refresh() >= 1
    assert "super-secret-value" not in h.redact("GEMINI_API_KEY=super-secret-value")

def test_rbac_sensitive_actions_require_admin():
    a=AccessController(admin_check=lambda uid: uid==1)
    assert not a.authorize(2,"rotate_secrets").allowed
    assert a.authorize(1,"rotate_secrets").allowed
    a.set_role(2,"operator")
    assert a.authorize(2,"retry_dead_letter").allowed

def test_encrypted_secret_master_rotation(tmp_path, monkeypatch):
    old=Fernet.generate_key().decode(); new=Fernet.generate_key().decode()
    monkeypatch.setenv("P29_SECRET_MASTER_KEY", old)
    path=str(tmp_path/"secrets.sqlite")
    m=SecretManager(path); m.set("GEMINI_API_KEY","abc123",kind="ai")
    assert m.get("GEMINI_API_KEY")=="abc123"
    assert m.rotate_master_key(new)==1
    assert m.get("GEMINI_API_KEY")=="abc123"
    monkeypatch.setenv("P29_SECRET_MASTER_KEY", new)
    m2=SecretManager(path); assert m2.get("GEMINI_API_KEY")=="abc123"
