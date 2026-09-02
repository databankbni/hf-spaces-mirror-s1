"""Private dataset operations for MyShub API.

Stores: users, admins, shops_meta, staff_keys
Uses Hugging Face Dataset with Parquet files.
Delayed flush for batch commits.
"""
import os
import threading
import json
import math
from datetime import datetime, timezone
from io import BytesIO

import pandas as pd
from huggingface_hub import HfApi, hf_hub_download
from huggingface_hub.utils import EntryNotFoundError

HF_TOKEN = os.getenv("HF_TOKEN")
REPO_ID = os.getenv("DATASET_PRIVATE", "emltechstudio/myshub-db-private")

api = HfApi(token=HF_TOKEN)
_lock = threading.Lock()

# In-memory caches
_shops_meta = None
_users = None
_admins = None
_staff_keys = None

_dirty = {"shops_meta": False, "users": False, "admins": False, "staff_keys": False}
_timers = {"shops_meta": None, "users": None, "admins": None, "staff_keys": None}

FLUSH_DELAY_SHOPS = 150.0   # 150s for shop metadata (was 150s in old)
FLUSH_DELAY_USERS = 150.0   # 150s for users
FLUSH_DELAY_ADMINS = 30.0   # 30s for admins
FLUSH_DELAY_STAFF = 30.0    # 30s for staff keys

# ─── Schemas ────────────────────────────────────────────────────────────────
SHOPS_META_SCHEMA = {
    "email": "object",
    "slug": "object",
    "plan": "object",
    "status": "object",
    "sub_type": "object",
    "country": "object",
    "city": "object",
    "category": "object",
    "lat": "float64",
    "lng": "float64",
    "referral_code": "object",
    "referred_by": "object",
    "expires_at": "object",
    "visit_count": "int64",
    "created_at": "object",
    "updated_at": "object",
}

USER_SCHEMA = {
    "email": "object",
    "password_hash": "object",
    "security_questions": "object",
    "country": "object",
    "referral_code": "object",
    "referred_by": "object",
    "created_at": "object",
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

SCHEMAS = {
    "shops_meta.parquet": SHOPS_META_SCHEMA,
    "users.parquet": USER_SCHEMA,
    "admins.parquet": ADMIN_SCHEMA,
    "staff_keys.parquet": STAFF_KEY_SCHEMA,
}


def _serialize(val):
    if isinstance(val, (list, dict)):
        return json.dumps(val)
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
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


def _create_empty_file(filename: str):
    """Create an empty Parquet file with correct schema on the Hub."""
    schema = SCHEMAS[filename]
    df = pd.DataFrame({col: pd.Series(dtype=dt) for col, dt in schema.items()})
    buf = BytesIO()
    df.to_parquet(buf, index=False)
    buf.seek(0)
    api.upload_file(
        path_or_fileobj=buf,
        path_in_repo=filename,
        repo_id=REPO_ID,
        repo_type="dataset",
        token=HF_TOKEN
    )
    print(f"[DB] Created empty {filename} on Hub")


def _read_parquet(filename: str) -> list[dict]:
    try:
        path = hf_hub_download(
            repo_id=REPO_ID,
            filename=filename,
            repo_type="dataset",
            token=HF_TOKEN
        )
        df = pd.read_parquet(path)
        records = df.to_dict("records")
        for r in records:
            for k, v in list(r.items()):
                r[k] = _deserialize(v)
                # Handle NaN floats
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    r[k] = None
        return records
    except EntryNotFoundError:
        _create_empty_file(filename)
        return []
    except Exception as e:
        print(f"[DB Read Error {filename}] {e}")
        return []


def _write_parquet(filename: str, records: list[dict]):
    if not records:
        schema = SCHEMAS[filename]
        df = pd.DataFrame({col: pd.Series(dtype=dt) for col, dt in schema.items()})
    else:
        serialized = []
        for r in records:
            row = {k: _serialize(v) for k, v in r.items()}
            serialized.append(row)
        df = pd.DataFrame(serialized)
        schema = SCHEMAS[filename]
        for col, dt in schema.items():
            if col not in df.columns:
                df[col] = pd.Series(dtype=dt)
    buf = BytesIO()
    df.to_parquet(buf, index=False)
    buf.seek(0)
    api.upload_file(
        path_or_fileobj=buf,
        path_in_repo=filename,
        repo_id=REPO_ID,
        repo_type="dataset",
        token=HF_TOKEN
    )


def _ensure_loaded():
    global _shops_meta, _users, _admins, _staff_keys
    if _shops_meta is None:
        _shops_meta = _read_parquet("shops_meta.parquet")
    if _users is None:
        _users = _read_parquet("users.parquet")
    if _admins is None:
        _admins = _read_parquet("admins.parquet")
    if _staff_keys is None:
        _staff_keys = _read_parquet("staff_keys.parquet")


def _flush_file(key: str, filename: str, records: list[dict]):
    global _dirty, _timers
    with _lock:
        if not _dirty.get(key):
            return
        try:
            _write_parquet(filename, records)
            _dirty[key] = False
        except Exception as e:
            print(f"[DB Flush Error {key}] {e}")
            raise
        finally:
            _timers[key] = None


def _schedule_flush(key: str, filename: str, records: list[dict], delay: float):
    global _dirty, _timers
    _dirty[key] = True
    if _timers.get(key) is not None:
        _timers[key].cancel()
    _timers[key] = threading.Timer(delay, lambda: _flush_file(key, filename, records))
    _timers[key].daemon = True
    _timers[key].start()


# ─── Shops Meta ─────────────────────────────────────────────────────────────
def get_shop_meta_by_email(email: str) -> dict | None:
    with _lock:
        _ensure_loaded()
        e = email.lower().strip()
        for r in _shops_meta:
            if r.get("email") == e:
                return r.copy()
        return None


def get_shop_meta_by_slug(slug: str) -> dict | None:
    with _lock:
        _ensure_loaded()
        s = slug.lower().strip()
        for r in _shops_meta:
            if r.get("slug") == s:
                return r.copy()
        return None


def create_shop_meta(data: dict) -> dict:
    with _lock:
        _ensure_loaded()
        data["email"] = data["email"].lower().strip()
        data["slug"] = data["slug"].lower().strip()
        data["created_at"] = datetime.now(timezone.utc).isoformat()
        data["updated_at"] = data["created_at"]
        data.setdefault("status", "active")
        data.setdefault("plan", "free")
        data.setdefault("sub_type", "")
        data.setdefault("country", "")
        data.setdefault("city", "")
        data.setdefault("category", "")
        data.setdefault("lat", None)
        data.setdefault("lng", None)
        data.setdefault("referral_code", "")
        data.setdefault("referred_by", "")
        data.setdefault("expires_at", "")
        data.setdefault("visit_count", 0)
        _shops_meta.append(data)
        _schedule_flush("shops_meta", "shops_meta.parquet", _shops_meta, FLUSH_DELAY_SHOPS)
        return data


def update_shop_meta(email: str, updates: dict) -> dict | None:
    with _lock:
        _ensure_loaded()
        e = email.lower().strip()
        for i, r in enumerate(_shops_meta):
            if r.get("email") == e:
                updates["updated_at"] = datetime.now(timezone.utc).isoformat()
                _shops_meta[i].update(updates)
                _schedule_flush("shops_meta", "shops_meta.parquet", _shops_meta, FLUSH_DELAY_SHOPS)
                return _shops_meta[i].copy()
        return None


def update_shop_meta_slug(old_slug: str, new_slug: str):
    with _lock:
        _ensure_loaded()
        old = old_slug.lower().strip()
        new = new_slug.lower().strip()
        for i, r in enumerate(_shops_meta):
            if r.get("slug") == old:
                _shops_meta[i]["slug"] = new
                _shops_meta[i]["updated_at"] = datetime.now(timezone.utc).isoformat()
                _schedule_flush("shops_meta", "shops_meta.parquet", _shops_meta, FLUSH_DELAY_SHOPS)
                return True
        raise ValueError("Shop not found")


def get_all_shops_meta() -> list[dict]:
    with _lock:
        _ensure_loaded()
        return [r.copy() for r in _shops_meta]


def increment_visit(slug: str):
    """Increment visit count in metadata (fast counter)."""
    with _lock:
        _ensure_loaded()
        s = slug.lower().strip()
        for i, r in enumerate(_shops_meta):
            if r.get("slug") == s:
                _shops_meta[i]["visit_count"] = int(r.get("visit_count", 0)) + 1
                _schedule_flush("shops_meta", "shops_meta.parquet", _shops_meta, FLUSH_DELAY_SHOPS)
                return


# ─── Users ──────────────────────────────────────────────────────────────────
def get_user_by_email(email: str) -> dict | None:
    with _lock:
        _ensure_loaded()
        e = email.lower().strip()
        for r in _users:
            if r.get("email") == e:
                return r.copy()
        return None


def create_user(data: dict) -> dict:
    with _lock:
        _ensure_loaded()
        data["email"] = data["email"].lower().strip()
        data["created_at"] = datetime.now(timezone.utc).isoformat()
        _users.append(data)
        _schedule_flush("users", "users.parquet", _users, FLUSH_DELAY_USERS)
        return data


def update_user(email: str, updates: dict) -> dict | None:
    with _lock:
        _ensure_loaded()
        e = email.lower().strip()
        for i, r in enumerate(_users):
            if r.get("email") == e:
                _users[i].update(updates)
                _schedule_flush("users", "users.parquet", _users, FLUSH_DELAY_USERS)
                return _users[i].copy()
        return None


# ─── Admins ─────────────────────────────────────────────────────────────────
def get_admin(email: str) -> dict | None:
    with _lock:
        _ensure_loaded()
        e = email.lower().strip()
        for a in _admins:
            if a.get("email") == e:
                return a.copy()
        return None


def create_admin(email: str, password_hash: str, role: str, created_by: str = None) -> bool:
    with _lock:
        _ensure_loaded()
        e = email.lower().strip()
        for a in _admins:
            if a.get("email") == e:
                return False
        admin = {
            "email": e,
            "password": password_hash,
            "role": role,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": created_by or "system",
            "active": True
        }
        _admins.append(admin)
        _schedule_flush("admins", "admins.parquet", _admins, FLUSH_DELAY_ADMINS)
        return True


def update_admin(email: str, updates: dict) -> bool:
    with _lock:
        _ensure_loaded()
        e = email.lower().strip()
        for a in _admins:
            if a.get("email") == e:
                a.update(updates)
                _schedule_flush("admins", "admins.parquet", _admins, FLUSH_DELAY_ADMINS)
                return True
        return False


def delete_admin(email: str) -> bool:
    with _lock:
        _ensure_loaded()
        e = email.lower().strip()
        for i, a in enumerate(_admins):
            if a.get("email") == e:
                del _admins[i]
                _schedule_flush("admins", "admins.parquet", _admins, FLUSH_DELAY_ADMINS)
                return True
        return False


def list_admins() -> list:
    with _lock:
        _ensure_loaded()
        return [a.copy() for a in _admins]


# ─── Staff Keys ─────────────────────────────────────────────────────────────
def create_staff_key(created_by: str, role: str = "viewer") -> str:
    import secrets
    key = secrets.token_urlsafe(16)
    with _lock:
        _ensure_loaded()
        key_data = {
            "key": key,
            "role": role,
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "used": False
        }
        _staff_keys.append(key_data)
        _schedule_flush("staff_keys", "staff_keys.parquet", _staff_keys, FLUSH_DELAY_STAFF)
        return key


def use_staff_key(key: str) -> dict | None:
    with _lock:
        _ensure_loaded()
        for k in _staff_keys:
            if k.get("key") == key and not k.get("used"):
                k["used"] = True
                _schedule_flush("staff_keys", "staff_keys.parquet", _staff_keys, FLUSH_DELAY_STAFF)
                return k.copy()
        return None


def list_staff_keys() -> list:
    with _lock:
        _ensure_loaded()
        return [k.copy() for k in _staff_keys]


# ─── Force flush ────────────────────────────────────────────────────────────
def flush_all():
    _flush_file("shops_meta", "shops_meta.parquet", _shops_meta)
    _flush_file("users", "users.parquet", _users)
    _flush_file("admins", "admins.parquet", _admins)
    _flush_file("staff_keys", "staff_keys.parquet", _staff_keys)


def flush_db():
    """Alias for flush_all() — backwards compatibility."""
    flush_all()


import atexit
atexit.register(flush_all)
