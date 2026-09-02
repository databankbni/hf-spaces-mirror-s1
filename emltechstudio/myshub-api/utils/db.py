import os
import threading
import json
import secrets
import time
import math
from datetime import datetime
from io import BytesIO
from typing import Optional

import pandas as pd
from huggingface_hub import HfApi, hf_hub_download
from huggingface_hub.utils import EntryNotFoundError

# ═══ ENVIRONMENT ═════════════════════════════════════════════════════════════
HF_TOKEN = os.getenv("HF_TOKEN")
PUBLIC_REPO = os.getenv("PUBLIC_DATASET", "emltechstudio/myshub-db-public")
PRIVATE_REPO = os.getenv("PRIVATE_DATASET", "emltechstudio/myshub-db-private")

api = HfApi(token=HF_TOKEN)
_lock = threading.Lock()

# ═══ IN-MEMORY INDEX ═════════════════════════════════════════════════════════
# shop_index: slug -> {category, country, state, lga, plan, business_name, tagline, lat, lng, file_path}
_shop_index: dict = {}

# In-memory caches for private data
_users: Optional[list] = None
_admins: Optional[list] = None
_staff_keys: Optional[list] = None
_notifications: Optional[list] = None
_feedback: Optional[list] = None  # NEW

# Dirty flags & flush timers
_dirty = {"users": False, "admins": False, "staff_keys": False, "notifications": False, "feedback": False}
_timers = {"users": None, "admins": None, "staff_keys": None, "notifications": None, "feedback": None}

FLUSH_DELAY_USERS = 150.0
FLUSH_DELAY_ADMINS = 30.0
FLUSH_DELAY_STAFF_KEYS = 30.0
FLUSH_DELAY_NOTIFICATIONS = 60.0
FLUSH_DELAY_FEEDBACK = 60.0  # NEW

# ═══ SCHEMAS ═════════════════════════════════════════════════════════════════
USER_SCHEMA = {
    "email": "object",
    "password_hash": "object",
    "security_questions": "object",
    "country": "object",
    "referral_code": "object",
    "referred_by": "object",
    "created_at": "object",
    "push_subscription": "object",
}
ADMIN_SCHEMA = {
    "email": "object",
    "password": "object",
    "role": "object",
    "created_at": "object",
    "created_by": "object",
    "active": "bool",
}
STAFF_KEY_SCHEMA = {
    "key": "object",
    "role": "object",
    "created_by": "object",
    "created_at": "object",
    "used": "bool",
}
NOTIFICATION_SCHEMA = {
    "id": "object",
    "email": "object",
    "type": "object",
    "title": "object",
    "message": "object",
    "read": "bool",
    "created_at": "object",
    "data": "object",
}
# NEW: Feedback schema
FEEDBACK_SCHEMA = {
    "id": "object",
    "name": "object",
    "email": "object",
    "message": "object",
    "type": "object",
    "created_at": "object",
}

PRIVATE_SCHEMAS = {
    "users.parquet": USER_SCHEMA,
    "admins.parquet": ADMIN_SCHEMA,
    "staff_keys.parquet": STAFF_KEY_SCHEMA,
    "notifications.parquet": NOTIFICATION_SCHEMA,
    "feedback.parquet": FEEDBACK_SCHEMA,  # NEW
}

# ═══ SERIALIZATION HELPERS ═══════════════════════════════════════════════════
def _serialize(val):
    if isinstance(val, (list, dict)):
        return json.dumps(val)
    return val

def _deserialize(val):
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            if isinstance(parsed, (list, dict)):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return val

# ═══ PUBLIC DATASET HELPERS ═════════════════════════════════════════════════
def _list_public_files() -> list:
    try:
        files = api.list_repo_files(repo_id=PUBLIC_REPO, repo_type="dataset", token=HF_TOKEN)
        return [f for f in files if f.endswith(".parquet")]
    except Exception as e:
        print(f"[DB] Error listing public files: {e}")
        return []

def _read_public_parquet(filename: str) -> dict:
    try:
        path = hf_hub_download(
            repo_id=PUBLIC_REPO,
            filename=filename,
            repo_type="dataset",
            token=HF_TOKEN
        )
        df = pd.read_parquet(path)
        if len(df) == 0:
            return {}
        record = df.to_dict("records")[0]
        for k, v in list(record.items()):
            record[k] = _deserialize(v)
        return record
    except EntryNotFoundError:
        return {}
    except Exception as e:
        print(f"[DB] Error reading public {filename}: {e}")
        return {}

def _write_public_parquet(filename: str, record: dict):
    serialized = {k: _serialize(v) for k, v in record.items()}
    df = pd.DataFrame([serialized])
    buf = BytesIO()
    df.to_parquet(buf, index=False)
    buf.seek(0)
    api.upload_file(
        path_or_fileobj=buf,
        path_in_repo=filename,
        repo_id=PUBLIC_REPO,
        repo_type="dataset",
        token=HF_TOKEN
    )

def _delete_public_parquet(filename: str):
    try:
        api.delete_file(
            path_in_repo=filename,
            repo_id=PUBLIC_REPO,
            repo_type="dataset",
            token=HF_TOKEN
        )
    except Exception as e:
        print(f"[DB] Error deleting public {filename}: {e}")

# ═══ PRIVATE DATASET HELPERS ═════════════════════════════════════════════════
def _create_empty_private(filename: str):
    schema = PRIVATE_SCHEMAS[filename]
    df = pd.DataFrame({col: pd.Series(dtype=dt) for col, dt in schema.items()})
    buf = BytesIO()
    df.to_parquet(buf, index=False)
    buf.seek(0)
    api.upload_file(
        path_or_fileobj=buf,
        path_in_repo=filename,
        repo_id=PRIVATE_REPO,
        repo_type="dataset",
        token=HF_TOKEN
    )
    print(f"[DB] Created empty {filename} in private dataset")

def _read_private_parquet(filename: str) -> list:
    try:
        path = hf_hub_download(
            repo_id=PRIVATE_REPO,
            filename=filename,
            repo_type="dataset",
            token=HF_TOKEN
        )
        df = pd.read_parquet(path)
        records = df.to_dict("records")
        for r in records:
            for k, v in list(r.items()):
                r[k] = _deserialize(v)
        return records
    except EntryNotFoundError:
        _create_empty_private(filename)
        return []
    except Exception as e:
        print(f"[DB Read Error {filename}] {e}")
        return []

def _write_private_parquet(filename: str, records: list):
    if not records:
        schema = PRIVATE_SCHEMAS[filename]
        df = pd.DataFrame({col: pd.Series(dtype=dt) for col, dt in schema.items()})
    else:
        serialized = []
        for r in records:
            row = {k: _serialize(v) for k, v in r.items()}
            serialized.append(row)
        df = pd.DataFrame(serialized)
        schema = PRIVATE_SCHEMAS[filename]
        for col, dt in schema.items():
            if col not in df.columns:
                df[col] = pd.Series(dtype=dt)
    buf = BytesIO()
    df.to_parquet(buf, index=False)
    buf.seek(0)
    api.upload_file(
        path_or_fileobj=buf,
        path_in_repo=filename,
        repo_id=PRIVATE_REPO,
        repo_type="dataset",
        token=HF_TOKEN
    )

def _schedule_private_flush(key: str, filename: str, records: list, delay: float):
    global _dirty, _timers
    _dirty[key] = True
    if _timers.get(key) is not None:
        _timers[key].cancel()
    _timers[key] = threading.Timer(delay, lambda: _flush_private_file(key, filename, records))
    _timers[key].daemon = True
    _timers[key].start()

def _flush_private_file(key: str, filename: str, records: list):
    global _dirty, _timers
    with _lock:
        if not _dirty.get(key):
            return
        try:
            _write_private_parquet(filename, records)
            _dirty[key] = False
            print(f"[DB] Flushed {filename}")
        except Exception as e:
            print(f"[DB Flush Error {key}] {e}")
            raise
        finally:
            _timers[key] = None

def _ensure_private_loaded():
    global _users, _admins, _staff_keys, _notifications, _feedback
    if _users is None:
        _users = _read_private_parquet("users.parquet")
    if _admins is None:
        _admins = _read_private_parquet("admins.parquet")
    if _staff_keys is None:
        _staff_keys = _read_private_parquet("staff_keys.parquet")
    if _notifications is None:
        _notifications = _read_private_parquet("notifications.parquet")
    if _feedback is None:  # NEW
        _feedback = _read_private_parquet("feedback.parquet")

# ═══ SHOP INDEX (RAM) ════════════════════════════════════════════════════════
def build_shop_index():
    """Build the in-memory index from public dataset. Called on startup."""
    global _shop_index
    _shop_index = {}
    files = _list_public_files()
    print(f"[INDEX] Found {len(files)} shop files")
    for filename in files:
        slug = filename.replace(".parquet", "")
        try:
            shop = _read_public_parquet(filename)
            if not shop:
                continue
            shop_json = shop.get("shop_json", {})
            if isinstance(shop_json, str):
                try:
                    shop_json = json.loads(shop_json)
                except:
                    shop_json = {}

            analytics = shop_json.get("analytics", {})
            visit_count = shop.get("visit_count", 0) or analytics.get("visit_count", 0)

            _shop_index[slug] = {
                "slug": slug,
                "email": shop.get("email", ""),
                "business_name": shop_json.get("business_name", ""),
                "tagline": shop_json.get("tagline", ""),
                "description": shop_json.get("description", ""),
                "category": shop_json.get("category", ""),
                "country": shop.get("country", ""),
                "state": shop_json.get("state", ""),
                "lga": shop_json.get("lga", ""),
                "city": shop_json.get("city", ""),
                "plan": shop.get("plan", "free"),
                "status": shop.get("status", "active"),
                "visit_count": visit_count,
                "referral_code": shop.get("referral_code", ""),
                "referred_by": shop.get("referred_by", ""),
                "created_at": shop.get("created_at", ""),
                "lat": shop_json.get("lat"),
                "lng": shop_json.get("lng"),
                "file_path": f"{PUBLIC_REPO}/resolve/main/{filename}",
            }
        except Exception as e:
            print(f"[INDEX] Error indexing {slug}: {e}")
    print(f"[INDEX] Indexed {len(_shop_index)} shops")

def get_shop_index() -> dict:
    return _shop_index.copy()

def add_to_index(slug: str, metadata: dict):
    _shop_index[slug] = metadata

def update_index(slug: str, updates: dict):
    if slug in _shop_index:
        _shop_index[slug].update(updates)

def remove_from_index(slug: str):
    _shop_index.pop(slug, None)

# ═══ PUBLIC SHOP CRUD ════════════════════════════════════════════════════════
def get_shop_by_slug(slug: str) -> Optional[dict]:
    slug = slug.lower().strip()
    filename = f"{slug}.parquet"
    return _read_public_parquet(filename)

def get_shop_by_email(email: str) -> Optional[dict]:
    e = email.lower().strip()
    index = get_shop_index()
    for slug, meta in index.items():
        if meta.get("email") == e:
            return get_shop_by_slug(slug)
    return None

def create_shop(data: dict) -> dict:
    slug = data["slug"].lower().strip()
    filename = f"{slug}.parquet"
    data["created_at"] = datetime.utcnow().isoformat()
    data["visit_count"] = 0
    _write_public_parquet(filename, data)

    shop_json = data.get("shop_json", {})
    if isinstance(shop_json, str):
        try:
            shop_json = json.loads(shop_json)
        except:
            shop_json = {}

    lat = shop_json.get("lat")
    lng = shop_json.get("lng")

    add_to_index(slug, {
        "slug": slug,
        "email": data.get("email", ""),
        "business_name": shop_json.get("business_name", ""),
        "tagline": shop_json.get("tagline", ""),
        "description": shop_json.get("description", ""),
        "category": shop_json.get("category", ""),
        "country": data.get("country", ""),
        "state": shop_json.get("state", ""),
        "lga": shop_json.get("lga", ""),
        "city": shop_json.get("city", ""),
        "plan": data.get("plan", "free"),
        "status": data.get("status", "active"),
        "visit_count": 0,
        "referral_code": data.get("referral_code", ""),
        "referred_by": data.get("referred_by", ""),
        "created_at": data["created_at"],
        "lat": lat,
        "lng": lng,
        "file_path": f"{PUBLIC_REPO}/resolve/main/{filename}",
    })
    return data

def update_shop(slug: str, updates: dict) -> Optional[dict]:
    slug = slug.lower().strip()
    filename = f"{slug}.parquet"
    shop = get_shop_by_slug(slug)
    if not shop:
        return None
    shop.update(updates)
    _write_public_parquet(filename, shop)

    shop_json = shop.get("shop_json", {})
    if isinstance(shop_json, str):
        try:
            shop_json = json.loads(shop_json)
        except:
            shop_json = {}

    lat = shop_json.get("lat")
    lng = shop_json.get("lng")
    analytics = shop_json.get("analytics", {})
    updated_visit_count = shop.get("visit_count", 0) or analytics.get("visit_count", 0)

    index_updates = {
        "business_name": shop_json.get("business_name", ""),
        "tagline": shop_json.get("tagline", ""),
        "description": shop_json.get("description", ""),
        "category": shop_json.get("category", ""),
        "country": shop.get("country", ""),
        "state": shop_json.get("state", ""),
        "lga": shop_json.get("lga", ""),
        "city": shop_json.get("city", ""),
        "plan": shop.get("plan", "free"),
        "status": shop.get("status", "active"),
        "visit_count": updated_visit_count,
        "referral_code": shop.get("referral_code", ""),
        "referred_by": shop.get("referred_by", ""),
    }
    if lat is not None:
        index_updates["lat"] = lat
    if lng is not None:
        index_updates["lng"] = lng
    update_index(slug, index_updates)
    return shop

def delete_shop(slug: str) -> bool:
    slug = slug.lower().strip()
    filename = f"{slug}.parquet"
    _delete_public_parquet(filename)
    remove_from_index(slug)
    return True

# ═══ PRIVATE CRUD (Users) ════════════════════════════════════════════════════
def get_user_by_email(email: str) -> Optional[dict]:
    with _lock:
        _ensure_private_loaded()
        e = email.lower().strip()
        for r in _users:
            if r.get("email") == e:
                return r.copy()
        return None

def create_user(data: dict) -> dict:
    with _lock:
        _ensure_private_loaded()
        data["email"] = data["email"].lower().strip()
        data["created_at"] = datetime.utcnow().isoformat()
        _users.append(data)
        _schedule_private_flush("users", "users.parquet", _users, FLUSH_DELAY_USERS)
        return data

def update_user(email: str, updates: dict) -> Optional[dict]:
    with _lock:
        _ensure_private_loaded()
        e = email.lower().strip()
        for i, r in enumerate(_users):
            if r.get("email") == e:
                _users[i].update(updates)
                _schedule_private_flush("users", "users.parquet", _users, FLUSH_DELAY_USERS)
                return _users[i].copy()
        return None

# ═══ PRIVATE CRUD (Admins) ═════════════════════════════════════════════════
def get_admin(email: str) -> Optional[dict]:
    with _lock:
        _ensure_private_loaded()
        e = email.lower().strip()
        for a in _admins:
            if a.get("email") == e:
                return a.copy()
        return None

def create_admin(email: str, password_hash: str, role: str, created_by: str = None) -> bool:
    with _lock:
        _ensure_private_loaded()
        e = email.lower().strip()
        for a in _admins:
            if a.get("email") == e:
                return False
        admin = {
            "email": e,
            "password": password_hash,
            "role": role,
            "created_at": datetime.utcnow().isoformat(),
            "created_by": created_by or "system",
            "active": True
        }
        _admins.append(admin)
        _schedule_private_flush("admins", "admins.parquet", _admins, FLUSH_DELAY_ADMINS)
        return True

def update_admin(email: str, updates: dict) -> bool:
    with _lock:
        _ensure_private_loaded()
        e = email.lower().strip()
        for a in _admins:
            if a.get("email") == e:
                a.update(updates)
                _schedule_private_flush("admins", "admins.parquet", _admins, FLUSH_DELAY_ADMINS)
                return True
        return False

def delete_admin(email: str) -> bool:
    with _lock:
        _ensure_private_loaded()
        e = email.lower().strip()
        for i, a in enumerate(_admins):
            if a.get("email") == e:
                del _admins[i]
                _schedule_private_flush("admins", "admins.parquet", _admins, FLUSH_DELAY_ADMINS)
                return True
        return False

def list_admins() -> list:
    with _lock:
        _ensure_private_loaded()
        return [a.copy() for a in _admins]

# ═══ PRIVATE CRUD (Staff Keys) ═════════════════════════════════════════════
def create_staff_key(created_by: str, role: str = "viewer") -> str:
    key = secrets.token_urlsafe(16)
    with _lock:
        _ensure_private_loaded()
        key_data = {
            "key": key,
            "role": role,
            "created_by": created_by,
            "created_at": datetime.utcnow().isoformat(),
            "used": False
        }
        _staff_keys.append(key_data)
        _schedule_private_flush("staff_keys", "staff_keys.parquet", _staff_keys, FLUSH_DELAY_STAFF_KEYS)
        return key

def use_staff_key(key: str) -> Optional[dict]:
    with _lock:
        _ensure_private_loaded()
        for k in _staff_keys:
            if k.get("key") == key and not k.get("used"):
                k["used"] = True
                _schedule_private_flush("staff_keys", "staff_keys.parquet", _staff_keys, FLUSH_DELAY_STAFF_KEYS)
                return k.copy()
        return None

def list_staff_keys() -> list:
    with _lock:
        _ensure_private_loaded()
        return [k.copy() for k in _staff_keys]

# ═══ NOTIFICATIONS ══════════════════════════════════════════════════════════
def get_notifications(email: str) -> list:
    with _lock:
        _ensure_private_loaded()
        e = email.lower().strip()
        return [n.copy() for n in _notifications if n.get("email") == e or n.get("email") == "ALL"]

def create_notification(notification: dict) -> dict:
    with _lock:
        _ensure_private_loaded()
        notification["id"] = secrets.token_urlsafe(12)
        notification["created_at"] = datetime.utcnow().isoformat()
        notification.setdefault("read", False)
        _notifications.append(notification)
        _schedule_private_flush("notifications", "notifications.parquet", _notifications, FLUSH_DELAY_NOTIFICATIONS)
        return notification

def mark_notification_read(notification_id: str, email: str) -> bool:
    with _lock:
        _ensure_private_loaded()
        for n in _notifications:
            if n.get("id") == notification_id and (n.get("email") == email.lower().strip() or n.get("email") == "ALL"):
                n["read"] = True
                _schedule_private_flush("notifications", "notifications.parquet", _notifications, FLUSH_DELAY_NOTIFICATIONS)
                return True
        return False

# ═══ FEEDBACK (NEW) ═════════════════════════════════════════════════════════
def get_feedback() -> list:
    """Get all feedback entries (for admin)."""
    with _lock:
        _ensure_private_loaded()
        return [f.copy() for f in _feedback]

def create_feedback(data: dict) -> dict:
    """Create a new feedback entry from the public."""
    with _lock:
        _ensure_private_loaded()
        data["id"] = secrets.token_urlsafe(12)
        data["created_at"] = datetime.utcnow().isoformat()
        _feedback.append(data)
        _schedule_private_flush("feedback", "feedback.parquet", _feedback, FLUSH_DELAY_FEEDBACK)
        return data

def delete_feedback(feedback_id: str) -> bool:
    """Delete a feedback entry by ID (admin only)."""
    with _lock:
        _ensure_private_loaded()
        for i, f in enumerate(_feedback):
            if f.get("id") == feedback_id:
                del _feedback[i]
                _schedule_private_flush("feedback", "feedback.parquet", _feedback, FLUSH_DELAY_FEEDBACK)
                return True
        return False

# ═══ FORCE FLUSH ════════════════════════════════════════════════════════════
def flush_all():
    _flush_private_file("users", "users.parquet", _users)
    _flush_private_file("admins", "admins.parquet", _admins)
    _flush_private_file("staff_keys", "staff_keys.parquet", _staff_keys)
    _flush_private_file("notifications", "notifications.parquet", _notifications)
    _flush_private_file("feedback", "feedback.parquet", _feedback)  # NEW

import atexit
atexit.register(flush_all)