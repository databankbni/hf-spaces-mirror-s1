"""Backward-compatible secret resolver.

Environment variable names are deliberately kept identical to the legacy P28/P29
names. Environment values always win, so existing deployments keep working
without any changes. If an environment value is absent, an encrypted value in
SecretManager may be used when the master key is configured.
"""
import os
from typing import Optional

# Canonical names used by the existing project. Do not rename these.
LEGACY_SECRET_NAMES = {
    "API_ID", "API_HASH", "BOT_TOKEN", "SESSION_STRING", "ADMINS", "ADMIN_ID",
    "MIDDLE_CHANNEL",
    "GEMINI_KEY_1", "GEMINI_KEY_2", "GROQ_KEY_1", "OPENROUTER_KEY_1",
    "BLOGGER_BLOG_ID", "BLOGGER_CLIENT_ID", "BLOGGER_CLIENT_SECRET", "BLOGGER_REFRESH_TOKEN",
    "P29_SECRET_MASTER_KEY",
}


def env_or_secret(name: str, db_path: Optional[str] = None, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    if value is not None and value != "":
        return value
    if not db_path:
        db_path = os.getenv("APP_DB_PATH", "data/app.sqlite3")
    try:
        from .manager import SecretManager
        manager = SecretManager(db_path, allow_unconfigured=True)
        return manager.get(name) or default
    except Exception:
        # Secrets must never prevent the legacy environment-only deployment from booting.
        return default


def env_names(prefix: str):
    """Return all configured names matching a legacy prefix, from env and secret store."""
    names = {k for k, v in os.environ.items() if k.startswith(prefix) and v}
    try:
        from .manager import SecretManager
        manager = SecretManager(os.getenv("APP_DB_PATH", "data/app.sqlite3"), allow_unconfigured=True)
        names.update(row[0] for row in manager.list_metadata() if row[0].startswith(prefix) and row[2])
    except Exception:
        pass
    return sorted(names)
