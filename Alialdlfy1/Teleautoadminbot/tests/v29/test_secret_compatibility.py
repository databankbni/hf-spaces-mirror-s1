import os
import tempfile
from pathlib import Path

from core.secrets.manager import SecretManager
from core.secrets.compat import env_or_secret, env_names


def test_legacy_environment_name_wins():
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "app.sqlite3")
        os.environ["P29_SECRET_MASTER_KEY"] = __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode()
        sm = SecretManager(db)
        sm.set("GEMINI_KEY_1", "db-value", kind="ai")
        os.environ["GEMINI_KEY_1"] = "env-value"
        assert env_or_secret("GEMINI_KEY_1", db_path=db) == "env-value"
        del os.environ["GEMINI_KEY_1"]
        assert env_or_secret("GEMINI_KEY_1", db_path=db) == "db-value"


def test_dynamic_key_names_are_discovered():
    os.environ["GEMINI_KEY_999"] = "test"
    try:
        assert "GEMINI_KEY_999" in env_names("GEMINI_KEY_")
    finally:
        del os.environ["GEMINI_KEY_999"]
