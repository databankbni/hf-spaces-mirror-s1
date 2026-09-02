import os
import hmac
import hashlib
import base64
import time
import jwt
from datetime import datetime, timedelta
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import bcrypt

import database as db_mod

APP_ENV = (os.getenv("APP_ENV") or "development").strip().lower()
APP_SECRET = (os.getenv("APP_SECRET") or "").strip()
JWT_SECRET_VALUE = (os.getenv("JWT_SECRET") or "").strip()

if APP_ENV == "development":
    if not APP_SECRET and not JWT_SECRET_VALUE:
        APP_SECRET = "development-secret"
        JWT_SECRET_VALUE = "development-secret"
elif not APP_SECRET and not JWT_SECRET_VALUE:
    raise RuntimeError(
        "Missing required auth secret: set APP_SECRET or JWT_SECRET before starting the app. "
        "Do not fall back to DATABASE_URL or a hard-coded dev secret in production."
    )

SECRET_KEY = APP_SECRET or JWT_SECRET_VALUE
JWT_SECRET = JWT_SECRET_VALUE or APP_SECRET
JWT_ALGO = os.getenv("JWT_ALGO") or "HS256"
# 15 days in seconds; can be overridden via ACCESS_TOKEN_EXPIRE_SECONDS in .env
ACCESS_TOKEN_EXPIRE_SECONDS = int(os.getenv("ACCESS_TOKEN_EXPIRE_SECONDS") or 15 * 24 * 60 * 60)
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


def create_access_token(email: str, expires_in: int = None) -> str:
    """Create a JWT access token. Defaults to `ACCESS_TOKEN_EXPIRE_SECONDS` if expires_in is None.

    This function preserves the old HMAC-signed token format for legacy compatibility
    when `jwt` decoding fails.
    """
    if expires_in is None:
        expires_in = ACCESS_TOKEN_EXPIRE_SECONDS

    exp = datetime.utcnow() + timedelta(seconds=expires_in)
    payload = {"sub": email, "exp": exp}
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)
    return token


def verify_access_token(token: str) -> str:
    """Verify an access token and return the email (`sub`).

    Attempts to decode as JWT first; if that fails due to invalid signature or format,
    falls back to the legacy HMAC-signed token format used previously.
    """
    # Try JWT decode first
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization token")
        return sub
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization token has expired")
    except jwt.InvalidTokenError:
        # Fall back to legacy token format
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


async def get_current_user(current_email: str = Depends(get_current_user_email)):
    user = await db_mod.client.user.find_unique(where={"email": current_email})
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User không tồn tại")
    return user


async def get_current_admin_user(user=Depends(get_current_user)):
    role = user.role if not isinstance(user, dict) else user.get("role")
    if role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Quyền bị từ chối")
    return user
