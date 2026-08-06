import os
import hmac
import hashlib
import base64
import time
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import bcrypt

SECRET_KEY = os.getenv("APP_SECRET") or os.getenv("DATABASE_URL") or "development-secret"
security = HTTPBearer()


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(message: str) -> str:
    digest = hmac.new(SECRET_KEY.encode(), message.encode(), hashlib.sha256).digest()
    return _base64url_encode(digest)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    return bcrypt.checkpw(password.encode(), hashed_password.encode())


def create_access_token(email: str, expires_in: int = 7 * 24 * 60 * 60) -> str:
    email_encoded = _base64url_encode(email.encode())
    expires = str(int(time.time()) + expires_in)
    payload = f"{email_encoded}.{expires}"
    signature = _sign(payload)
    return f"{payload}.{signature}"


def verify_access_token(token: str) -> str:
    try:
        email_encoded, expires, signature = token.split(".")
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization token")

    payload = f"{email_encoded}.{expires}"
    expected_signature = _sign(payload)

    if not hmac.compare_digest(expected_signature, signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization token")

    if int(expires) < int(time.time()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization token has expired")

    try:
        email = _base64url_decode(email_encoded).decode()
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization token")

    return email


async def get_current_user_email(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing or invalid")
    return verify_access_token(credentials.credentials)
