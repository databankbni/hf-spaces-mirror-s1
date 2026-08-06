import os
import json
import uuid
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from jose import JWTError, jwt

# ── Config ──────────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("JWT_SECRET", "ai-learning-assistant-super-secret-key-2024")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

USERS_FILE = os.path.join(os.path.dirname(__file__), "..", "users.json")


# ── User Store (flat JSON file) ───────────────────────────────────────────────
def _load_users() -> dict:
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r") as f:
        return json.load(f)


def _save_users(users: dict):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)


# ── Password Helpers ──────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    # Bcrypt max is 72 bytes — truncate to avoid any library-level errors
    pw_bytes = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    pw_bytes = plain.encode("utf-8")[:72]
    return bcrypt.checkpw(pw_bytes, hashed.encode("utf-8"))


# ── User CRUD ─────────────────────────────────────────────────────────────────
def create_user(username: str, password: str) -> dict:
    users = _load_users()
    if username in users:
        raise ValueError("Username already exists")
    user_id = str(uuid.uuid4())
    users[username] = {
        "id": user_id,
        "username": username,
        "hashed_password": hash_password(password),
        "created_at": datetime.utcnow().isoformat(),
    }
    _save_users(users)
    return {"id": user_id, "username": username}


def authenticate_user(username: str, password: str) -> Optional[dict]:
    users = _load_users()
    user = users.get(username)
    if not user:
        return None
    if not verify_password(password, user["hashed_password"]):
        return None
    return {"id": user["id"], "username": user["username"]}


# ── JWT ───────────────────────────────────────────────────────────────────────
def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None
