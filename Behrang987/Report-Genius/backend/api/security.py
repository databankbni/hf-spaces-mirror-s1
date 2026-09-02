"""Auth primitives: password hashing, JWT, and a small file-based user store.

Prefers ``passlib`` / ``python-jose`` when installed (see requirements.txt) and
falls back to stdlib implementations (PBKDF2-HMAC + a hand-rolled HS256 token) so
the backend runs and tests pass without those optional dependencies.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

from backend.config import settings

# ── password hashing ─────────────────────────────────────────────────────────
try:
    import bcrypt

    def hash_password(password: str) -> str:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")

    def verify_password(password: str, hashed: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))
        except Exception:  # noqa: BLE001
            return False

except ImportError:  # bcrypt unavailable → PBKDF2 fallback

    def hash_password(password: str) -> str:
        salt = os.urandom(16)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
        return f"pbkdf2_sha256$120000${salt.hex()}${dk.hex()}"

    def verify_password(password: str, hashed: str) -> bool:
        try:
            algo, iters, salt_hex, dk_hex = hashed.split("$")
        except ValueError:
            return False
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(dk.hex(), dk_hex)


# ── JWT ──────────────────────────────────────────────────────────────────────
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


try:
    from jose import jwt as _jose_jwt

    def create_token(tenant_id: str) -> str:
        payload = {
            "sub": tenant_id,
            "exp": int(time.time()) + settings.jwt_expiry_minutes * 60,
        }
        return _jose_jwt.encode(
            payload, settings.jwt_secret, algorithm=settings.jwt_algorithm
        )

    def decode_token(token: str) -> dict:
        return _jose_jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )

except Exception:  # noqa: BLE001 - python-jose unavailable → HS256 fallback

    def create_token(tenant_id: str) -> str:
        header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        payload = _b64url(
            json.dumps(
                {
                    "sub": tenant_id,
                    "exp": int(time.time()) + settings.jwt_expiry_minutes * 60,
                }
            ).encode()
        )
        signing_input = f"{header}.{payload}".encode()
        sig = hmac.new(
            settings.jwt_secret.encode(), signing_input, hashlib.sha256
        ).digest()
        return f"{header}.{payload}.{_b64url(sig)}"

    def decode_token(token: str) -> dict:
        try:
            header_b64, payload_b64, sig_b64 = token.split(".")
        except ValueError as exc:
            raise ValueError("Malformed token") from exc
        signing_input = f"{header_b64}.{payload_b64}".encode()
        expected = hmac.new(
            settings.jwt_secret.encode(), signing_input, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected, _b64url_decode(sig_b64)):
            raise ValueError("Invalid signature")
        payload = json.loads(_b64url_decode(payload_b64))
        if int(payload.get("exp", 0)) < int(time.time()):
            raise ValueError("Token expired")
        return payload


# ── user store ───────────────────────────────────────────────────────────────
def _users_path() -> Path:
    p = settings.data_dir_path / "users.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_users() -> dict[str, str]:
    path = _users_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_users(users: dict[str, str]) -> None:
    _users_path().write_text(json.dumps(users), encoding="utf-8")


def register_user(tenant_id: str, password: str) -> bool:
    """Create a tenant. Returns False if it already exists."""
    users = _load_users()
    if tenant_id in users:
        return False
    users[tenant_id] = hash_password(password)
    _save_users(users)
    return True


def authenticate(tenant_id: str, password: str) -> bool:
    users = _load_users()
    hashed = users.get(tenant_id)
    return bool(hashed and verify_password(password, hashed))
