import os
import logging
from core.secrets.compat import env_or_secret

logger = logging.getLogger(__name__)

DEFAULT_BLOGGER_CONFIG = {
    "blog_id": "",
    "client_id": "",
    "client_secret": "",
    "refresh_token": "",
    "publish_as_draft": False,
    "enabled": False,
    "default_jobs_image": "",
}

BLOGGER_API_SCOPE = "https://www.googleapis.com/auth/blogger"
BLOGGER_TOKEN_URL = "https://oauth2.googleapis.com/token"
BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"

ENV_MAP = {
    "blog_id": "BLOGGER_BLOG_ID",
    "client_id": "BLOGGER_CLIENT_ID",
    "client_secret": "BLOGGER_CLIENT_SECRET",
    "refresh_token": "BLOGGER_REFRESH_TOKEN",
    "publish_as_draft": "BLOGGER_PUBLISH_AS_DRAFT",
    "enabled": "BLOGGER_ENABLED",
    "default_jobs_image": "BLOGGER_DEFAULT_JOBS_IMAGE",
}

ENV_KEYS = set(ENV_MAP.keys())


class BloggerConfig:
    def __init__(self, db):
        self.db = db

    def _env_overrides(self) -> dict:
        overrides = {}
        for key, env_name in ENV_MAP.items():
            val = env_or_secret(env_name)
            if val is not None:
                if key in ("publish_as_draft", "enabled"):
                    overrides[key] = val.lower() in ("true", "1", "yes")
                else:
                    overrides[key] = val
        return overrides

    def env_keys(self) -> set:
        return {k for k, env in ENV_MAP.items() if env_or_secret(env) is not None}

    def get(self, key, default=None):
        env = self._env_overrides()
        if key in env:
            return env[key]
        cfg = self.db.get_config()
        return cfg.get(key, default)

    def set(self, key, value):
        if key in ENV_KEYS and env_or_secret(ENV_MAP[key]):
            logger.warning(f"BloggerConfig: '{key}' is set via env var, ignoring DB write")
            return
        self.db.update_config(key, value)

    def get_all(self):
        cfg = dict(self.db.get_config())
        env = self._env_overrides()
        for k, v in env.items():
            cfg[k] = v
        return cfg

    def is_configured(self):
        cfg = self.get_all()
        return bool(cfg.get("blog_id") and cfg.get("client_id") and cfg.get("client_secret") and cfg.get("refresh_token"))

    def is_enabled(self):
        return bool(self.get("enabled", False))
