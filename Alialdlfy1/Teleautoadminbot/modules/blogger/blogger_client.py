import time
import hashlib
import logging
from typing import Optional, Dict, Any

import httpx

from modules.blogger.config import BLOGGER_TOKEN_URL, BLOGGER_API_BASE, BloggerConfig
from modules.publish_target import PublishTarget

logger = logging.getLogger(__name__)


class BloggerClient(PublishTarget):
    def __init__(self, db, config=None):
        self.db = db
        self.config = config or BloggerConfig(db)
        self._access_token = None
        self._token_expires_at = 0
        self._http = httpx.AsyncClient(timeout=30.0)
        self._log_env_status()

    def _log_env_status(self):
        env = self.config._env_overrides()
        for key, env_name in [
            ("blog_id", "BLOGGER_BLOG_ID"),
            ("client_id", "BLOGGER_CLIENT_ID"),
            ("client_secret", "BLOGGER_CLIENT_SECRET"),
            ("refresh_token", "BLOGGER_REFRESH_TOKEN"),
        ]:
            if key in env:
                logger.info(f"{env_name}: FOUND (from os.environ)")
            else:
                logger.info(f"{env_name}: NOT FOUND")

    def is_configured(self):
        cfg = self.config.get_all()
        return bool(cfg.get("blog_id") and cfg.get("client_id") and cfg.get("client_secret") and cfg.get("refresh_token"))

    def _log_oauth_error(self, resp, data=None):
        """Temporary diagnostic logging only (to be removed later)."""
        status = getattr(resp, "status_code", "?")
        headers = dict(resp.headers) if resp is not None else {}
        body = resp.text if resp is not None else ""
        if not isinstance(data, dict):
            try:
                data = resp.json() if resp is not None else None
            except Exception:
                data = None
        if not isinstance(data, dict):
            data = {}
        err = data.get("error", "N/A")
        err_desc = data.get("error_description", "N/A")
        logger.error(
            "========== GOOGLE OAUTH ERROR ==========\n"
            f"HTTP Status: {status}\n"
            f"Response Headers:\n{headers}\n"
            f"Response Body:\n{body}\n"
            f"JSON:\n{data if data else 'not JSON'}\n"
            f"error:\n{err}\n"
            f"error_description:\n{err_desc}\n"
            "========================================"
        )

    async def authenticate(self) -> bool:
        cfg = self.config.get_all()
        if not cfg.get("client_id") or not cfg.get("client_secret") or not cfg.get("refresh_token"):
            logger.warning("Blogger: missing credentials, cannot authenticate")
            return False
        logger.info("Blogger: authenticating with OAuth2...")
        try:
            resp = await self._http.post(
                BLOGGER_TOKEN_URL,
                data={
                    "client_id": cfg["client_id"],
                    "client_secret": cfg["client_secret"],
                    "refresh_token": cfg["refresh_token"],
                    "grant_type": "refresh_token",
                },
            )
            try:
                data = resp.json()
            except Exception:
                data = None
            if resp.is_error or data is None or "access_token" not in data:
                self._log_oauth_error(resp, data)
                logger.error(f"Blogger auth failed: {data.get('error_description', data) if isinstance(data, dict) else resp.text}")
                return False
            self._access_token = data["access_token"]
            self._token_expires_at = time.time() + data.get("expires_in", 3600) - 60
            logger.info("Blogger: authenticated successfully")
            return True
        except Exception as e:
            logger.exception(f"Blogger auth error: {e}")
            return False

    async def _ensure_token(self) -> Optional[str]:
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token
        ok = await self.authenticate()
        return self._access_token if ok else None

    async def _api_request(self, method, path, json_data=None, params=None):
        token = await self._ensure_token()
        if not token:
            return None, "auth_failed"
        url = f"{BLOGGER_API_BASE}{path}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            resp = await self._http.request(method, url, headers=headers, json=json_data, params=params)
            data = resp.json()
            if resp.is_error:
                error_msg = data.get("error", {}).get("message", str(resp.status_code))
                logger.error(f"Blogger API error {resp.status_code}: {error_msg}")
                return None, error_msg
            return data, None
        except httpx.TimeoutException:
            logger.error("Blogger API timeout")
            return None, "timeout"
        except Exception as e:
            logger.exception(f"Blogger API request failed: {e}")
            return None, str(e)

    async def test_connection(self) -> bool:
        cfg = self.config.get_all()
        blog_id = cfg.get("blog_id", "self")
        logger.info(f"BloggerClient: testing connection to blog {blog_id}")
        data, err = await self._api_request("GET", f"/blogs/{blog_id}")
        if err:
            logger.error(f"BloggerClient: connection test FAILED: {err}")
            return False
        logger.info(f"BloggerClient: connection OK: {data.get('name', 'unknown')}")
        return True

    async def publish(self, article: Dict[str, Any], draft: bool = False) -> Optional[str]:
        cfg = self.config.get_all()
        blog_id = cfg.get("blog_id", "self")
        is_draft = draft or cfg.get("publish_as_draft", False)
        title = article.get("title", "")[:30]
        logger.info(f"BloggerClient: publishing '{title}' to blog {blog_id}, draft={is_draft}")
        body = {
            "kind": "blogger#post",
            "title": article.get("title", ""),
            "content": article.get("content", ""),
        }
        labels = article.get("labels", [])
        logger.info(f"JSON Payload Labels: {labels}")
        if labels:
            body["labels"] = labels
            logger.info(f"Labels added to body: {labels}")
        else:
            logger.warning(f"No labels to send! article keys: {list(article.keys())}")
            logger.warning(f"article.get('labels'): {article.get('labels')}")
        if is_draft:
            body["status"] = "draft"
        logger.info(f"Hashtags Sent To Blogger: present in content={bool(article.get('content', '') and '<hr' in article.get('content', ''))}")
        data, err = await self._api_request("POST", f"/blogs/{blog_id}/posts", json_data=body)
        if err:
            logger.error(f"BloggerClient: publish FAILED for '{title}': {err}")
            return None
        post_id = data.get("id")
        if post_id:
            logger.info(f"BloggerClient: publish SUCCESS for '{title}', post_id={post_id}")
        else:
            logger.warning(f"BloggerClient: publish returned no post_id for '{title}'")
        return str(post_id) if post_id else None

    async def get_post_url(self, post_id: str) -> Optional[str]:
        cfg = self.config.get_all()
        blog_id = cfg.get("blog_id", "self")
        data, err = await self._api_request("GET", f"/blogs/{blog_id}/posts/{post_id}")
        if err or not data:
            return None
        return data.get("url")

    async def update_post(self, post_id: str, article: Dict[str, Any]) -> bool:
        cfg = self.config.get_all()
        blog_id = cfg.get("blog_id", "self")
        body = {
            "kind": "blogger#post",
            "title": article.get("title", ""),
            "content": article.get("content", ""),
        }
        labels = article.get("labels", [])
        if labels:
            body["labels"] = labels
        data, err = await self._api_request("PUT", f"/blogs/{blog_id}/posts/{post_id}", json_data=body)
        if err:
            return False
        return True

    async def close(self):
        await self._http.aclose()
