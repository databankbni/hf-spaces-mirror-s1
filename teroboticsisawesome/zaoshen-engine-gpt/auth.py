"""Small password/session helpers with no external authentication dependency."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240_000)
    return "pbkdf2_sha256$240000$%s$%s" % (
        base64.urlsafe_b64encode(salt).decode().rstrip("="),
        base64.urlsafe_b64encode(digest).decode().rstrip("="),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt_text, digest_text = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text + "==")
        expected = base64.urlsafe_b64decode(digest_text + "==")
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(rounds))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _secret() -> bytes:
    value = os.environ.get("SESSION_SECRET") or os.environ.get("ADMIN_CODE")
    if not value:
        value = "local-preview-only-change-before-deploy"
    return value.encode()


def make_session(user_id: int, role: str, hours: int = 12) -> str:
    body = {"uid": user_id, "role": role, "exp": int(time.time()) + hours * 3600}
    raw = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()
    return raw + "." + sig


def read_session(token: str):
    try:
        raw, sig = token.rsplit(".", 1)
        expected = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        body = json.loads(base64.urlsafe_b64decode(raw + "=="))
        return body if int(body.get("exp", 0)) > time.time() else None
    except Exception:
        return None


def random_code(length: int = 8) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
