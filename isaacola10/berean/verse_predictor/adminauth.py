"""Minimal admin auth: password login -> short-lived HMAC-signed token.

No extra deps. Set ADMIN_PASSWORD to enable the admin area; if it's unset,
admin login is disabled (returns "not configured"). ADMIN_SECRET (optional)
signs tokens — defaults to a value derived from the password so tokens stay
valid across restarts as long as the password is unchanged.
"""
import base64
import hashlib
import hmac
import json
import os
import time

TOKEN_TTL = 7 * 86400  # 7 days


def _password() -> str | None:
    return os.environ.get("ADMIN_PASSWORD") or None


def _secret() -> bytes:
    s = os.environ.get("ADMIN_SECRET")
    if not s:
        # Derive a stable secret from the password so tokens survive restarts.
        s = "verseo::" + (_password() or "disabled")
    return s.encode()


def is_configured() -> bool:
    return _password() is not None


def _sign(payload: bytes) -> str:
    sig = hmac.new(_secret(), payload, hashlib.sha256).digest()
    b = base64.urlsafe_b64encode
    return f"{b(payload).decode()}.{b(sig).decode()}"


def login(password: str) -> str | None:
    pw = _password()
    if not pw or not hmac.compare_digest(password or "", pw):
        return None
    payload = json.dumps({"exp": int(time.time()) + TOKEN_TTL}).encode()
    return _sign(payload)


def verify(token: str) -> bool:
    if not token or "." not in token:
        return False
    try:
        ub = base64.urlsafe_b64decode
        payload_b64, sig_b64 = token.split(".", 1)
        payload = ub(payload_b64)
        expected = hmac.new(_secret(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(ub(sig_b64), expected):
            return False
        return json.loads(payload).get("exp", 0) > time.time()
    except Exception:  # noqa: BLE001
        return False
