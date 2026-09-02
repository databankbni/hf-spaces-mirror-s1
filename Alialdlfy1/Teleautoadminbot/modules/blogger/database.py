import json
import os
import time
import threading
import logging

logger = logging.getLogger(__name__)

_DEFAULT_DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
_HF_DATA = "/data" if os.path.isdir("/data") and "SPACE_ID" in os.environ else None
DB_FILE = os.environ.get("BLOGGER_DB_PATH", os.path.join(_HF_DATA or _DEFAULT_DB_DIR, "blogger_data.json"))
lock = threading.Lock()

DEFAULT_BLOGGER_DATA = {
    "config": {
        "blog_id": "",
        "client_id": "",
        "client_secret": "",
        "refresh_token": "",
        "publish_as_draft": False,
        "enabled": False,
        "default_jobs_image": "",
    },
    "ai_keys": {},
    "channels": {},
    "articles": {},
    "published_ids": [],
    "sections": {},
    "logs": [],
    "stats": {
        "total_published": 0,
        "total_failed": 0,
        "daily": {},
        "monthly": {},
    },
}


class BloggerDatabase:
    def __init__(self):
        self._cache = None

    def _ensure_file(self):
        os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
        if not os.path.exists(DB_FILE):
            old_path = os.path.join(_DEFAULT_DB_DIR, "blogger_data.json")
            if _HF_DATA and os.path.isfile(old_path):
                import shutil
                shutil.copy2(old_path, DB_FILE)
                logger.info(f"Migrated DB from {old_path} to {DB_FILE}")
            else:
                with open(DB_FILE, "w", encoding="utf-8") as f:
                    json.dump(DEFAULT_BLOGGER_DATA, f, ensure_ascii=False, indent=2)

    def _read(self):
        self._ensure_file()
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            # Never silently convert a corrupt database into an empty database.
            # Recovery is handled by the caller/startup layer.
            raise RuntimeError(f"Blogger database read failed: {exc}") from exc
        for key, value in DEFAULT_BLOGGER_DATA.items():
            if key not in data:
                data[key] = value.copy() if isinstance(value, (list, dict)) else value
        if not isinstance(data.get("config"), dict):
            data["config"] = {}
        for k, v in DEFAULT_BLOGGER_DATA["config"].items():
            data["config"].setdefault(k, v)
        return data

    def _write(self, data):
        self._ensure_file()
        tmp = DB_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp, DB_FILE)
        self._cache = None

    def get_config(self):
        with lock:
            return dict(self._read().get("config", {}))

    def update_config(self, key, value):
        with lock:
            data = self._read()
            data["config"][key] = value
            self._write(data)

    def get_channel(self, channel_id):
        with lock:
            data = self._read()
            return data.get("channels", {}).get(str(channel_id))

    def get_all_channels(self):
        with lock:
            data = self._read()
            return list(data.get("channels", {}).values())

    def save_channel(self, channel_id, channel_data):
        with lock:
            data = self._read()
            data["channels"][str(channel_id)] = channel_data
            self._write(data)

    def delete_channel(self, channel_id):
        with lock:
            data = self._read()
            data["channels"].pop(str(channel_id), None)
            self._write(data)

    def save_article(self, article_id, article_data):
        with lock:
            data = self._read()
            data["articles"][str(article_id)] = article_data
            self._write(data)

    def get_article(self, article_id):
        with lock:
            data = self._read()
            return data.get("articles", {}).get(str(article_id))

    def delete_article(self, article_id):
        with lock:
            data = self._read()
            data["articles"].pop(str(article_id), None)
            self._write(data)

    def get_all_articles(self):
        with lock:
            data = self._read()
            return list(data.get("articles", {}).values())

    def is_published(self, fingerprint):
        with lock:
            data = self._read()
            return fingerprint in data.get("published_ids", [])

    def mark_published(self, fingerprint):
        with lock:
            data = self._read()
            if fingerprint not in data["published_ids"]:
                data["published_ids"].append(fingerprint)
                data["stats"]["total_published"] += 1
            self._write(data)

    def mark_failed(self):
        with lock:
            data = self._read()
            data["stats"]["total_failed"] += 1
            self._write(data)

    def add_log(self, entry):
        with lock:
            data = self._read()
            data["logs"].append(entry)
            if len(data["logs"]) > 1000:
                data["logs"] = data["logs"][-1000:]
            self._write(data)

    def get_logs(self, limit=50):
        with lock:
            data = self._read()
            return list(data["logs"])[-limit:]

    def get_stats(self):
        with lock:
            data = self._read()
            return dict(data.get("stats", {}))

    def get_articles_by_status(self, status):
        with lock:
            data = self._read()
            return [a for a in data.get("articles", {}).values() if a.get("status") == status]

    def update_article_status(self, article_id, status, extra=None):
        with lock:
            data = self._read()
            if str(article_id) in data["articles"]:
                data["articles"][str(article_id)]["status"] = status
                if extra:
                    data["articles"][str(article_id)].update(extra)
            self._write(data)

    def get_all_sections(self):
        with lock:
            data = self._read()
            return dict(data.get("sections", {}))

    def add_section(self, section_id, section_data):
        with lock:
            data = self._read()
            data["sections"][str(section_id)] = section_data
            self._write(data)

    def delete_section(self, section_id):
        with lock:
            data = self._read()
            data["sections"].pop(str(section_id), None)
            self._write(data)

    def get_all_ai_keys(self):
        with lock:
            data = self._read()
            return dict(data.get("ai_keys", {}))

    def add_ai_key(self, key_id, key_data):
        with lock:
            data = self._read()
            data["ai_keys"][str(key_id)] = {
                "name": key_data.get("name", str(key_id)),
                "key": key_data.get("key", ""),
                "enabled": key_data.get("enabled", True),
                "usage_count": 0,
                "error_count": 0,
                "last_used": 0,
                "added_at": int(time.time()),
            }
            self._write(data)

    def delete_ai_key(self, key_id):
        with lock:
            data = self._read()
            data["ai_keys"].pop(str(key_id), None)
            self._write(data)

    def set_ai_key_enabled(self, key_id, enabled):
        with lock:
            data = self._read()
            if str(key_id) in data["ai_keys"]:
                data["ai_keys"][str(key_id)]["enabled"] = enabled
            self._write(data)

    def increment_daily_count(self, section):
        with lock:
            data = self._read()
            today = time.strftime("%Y-%m-%d")
            if "daily" not in data["stats"]:
                data["stats"]["daily"] = {}
            if today not in data["stats"]["daily"]:
                data["stats"]["daily"][today] = {}
            data["stats"]["daily"][today][section] = data["stats"]["daily"][today].get(section, 0) + 1
            self._write(data)

    def increment_ai_key_usage(self, key_id):
        with lock:
            data = self._read()
            if str(key_id) in data["ai_keys"]:
                data["ai_keys"][str(key_id)]["usage_count"] = data["ai_keys"][str(key_id)].get("usage_count", 0) + 1
                data["ai_keys"][str(key_id)]["last_used"] = int(time.time())
            self._write(data)

    def increment_ai_key_error(self, key_id):
        with lock:
            data = self._read()
            if str(key_id) in data["ai_keys"]:
                data["ai_keys"][str(key_id)]["error_count"] = data["ai_keys"][str(key_id)].get("error_count", 0) + 1
            self._write(data)

    SCHEDULE_KEY = "_schedule"

    def get_schedule_state(self) -> dict:
        with lock:
            data = self._read()
            return data.get("stats", {}).get(self.SCHEDULE_KEY, {"day": "", "last_slot": -1})

    def save_schedule_state(self, state: dict):
        with lock:
            data = self._read()
            if "stats" not in data:
                data["stats"] = {}
            data["stats"][self.SCHEDULE_KEY] = state
            self._write(data)

    DAILY_SLOTS_KEY = "_daily_slots"

    def get_slots_state(self) -> dict:
        """Persistent daily slots state for sections that declare fixed publish slots.
        Shape: {"day": str, "sections": {section: {"fixed": {"HH:MM": fp|None},
        "candidates": {"HH:MM": fp|None}, "published": {"HH:MM": fp|None},
        "source_ids": {fp: source_id}}}}. Sections not yet seen today get empty dicts."""
        with lock:
            data = self._read()
            if "stats" not in data:
                data["stats"] = {}
            return data["stats"].get(self.DAILY_SLOTS_KEY, {"day": "", "sections": {}})

    def save_slots_state(self, state: dict):
        with lock:
            data = self._read()
            if "stats" not in data:
                data["stats"] = {}
            data["stats"][self.DAILY_SLOTS_KEY] = state
            self._write(data)

    GEMINI_PENDING_KEY = "_gemini_pending"

    def get_gemini_pending_queue(self) -> list:
        with lock:
            data = self._read()
            return data.get(self.GEMINI_PENDING_KEY, [])

    def save_gemini_pending_queue(self, queue: list):
        with lock:
            data = self._read()
            data[self.GEMINI_PENDING_KEY] = queue
            self._write(data)

    def add_to_gemini_pending(self, raw_text: str, source_url: str = "", media: list = None,
                               fingerprint: str = "", channel_id: str = "", section: str = ""):
        with lock:
            data = self._read()
            pending = data.get(self.GEMINI_PENDING_KEY, [])
            # Avoid duplicate entries for the same fingerprint (e.g. re-enqueued after a failed attempt)
            if fingerprint and any(p.get("fingerprint") == fingerprint for p in pending):
                return
            pending.append({
                "raw_text": raw_text,
                "source_url": source_url,
                "media": media or [],
                "fingerprint": fingerprint,
                "channel_id": channel_id,
                "section": section,
                "attempts": 0,
                "added_at": int(time.time()),
            })
            data[self.GEMINI_PENDING_KEY] = pending
            self._write(data)

    def remove_from_gemini_pending(self, index: int = 0):
        with lock:
            data = self._read()
            pending = data.get(self.GEMINI_PENDING_KEY, [])
            if 0 <= index < len(pending):
                pending.pop(index)
                data[self.GEMINI_PENDING_KEY] = pending
                self._write(data)

    def remove_pending_by_fingerprint(self, fingerprint: str):
        """Remove a pending item by fingerprint (safe against list reordering/races)."""
        with lock:
            data = self._read()
            pending = data.get(self.GEMINI_PENDING_KEY, [])
            new_pending = [p for p in pending if p.get("fingerprint") != fingerprint]
            if len(new_pending) != len(pending):
                data[self.GEMINI_PENDING_KEY] = new_pending
                self._write(data)

    def increment_pending_attempts(self, fingerprint: str) -> int:
        """Increment and return the attempt counter for a pending item. Returns -1 if not found."""
        with lock:
            data = self._read()
            pending = data.get(self.GEMINI_PENDING_KEY, [])
            for p in pending:
                if p.get("fingerprint") == fingerprint:
                    p["attempts"] = p.get("attempts", 0) + 1
                    data[self.GEMINI_PENDING_KEY] = pending
                    self._write(data)
                    return p["attempts"]
            return -1

    MAX_BACKOFF_SECONDS = 3600

    def set_pending_retry_after(self, fingerprint: str, attempts: int):
        """Apply exponential backoff to a pending item so the scheduler does not hot-loop
        a repeatedly failing article. Returns the seconds until the next retry."""
        seconds = min(self.MAX_BACKOFF_SECONDS, 60 * (2 ** max(0, attempts - 1)))
        with lock:
            data = self._read()
            pending = data.get(self.GEMINI_PENDING_KEY, [])
            for p in pending:
                if p.get("fingerprint") == fingerprint:
                    p["retry_after"] = int(time.time()) + seconds
                    data[self.GEMINI_PENDING_KEY] = pending
                    self._write(data)
                    return seconds
            return seconds

    GEMINI_STATE_KEY = "_gemini"

    def get_gemini_state(self) -> dict:
        with lock:
            data = self._read()
            if "stats" not in data:
                data["stats"] = {}
            return data["stats"].get(self.GEMINI_STATE_KEY, {"global_cooldown_until": 0.0})

    def save_gemini_state(self, state: dict):
        with lock:
            data = self._read()
            if "stats" not in data:
                data["stats"] = {}
            data["stats"][self.GEMINI_STATE_KEY] = state
            self._write(data)
