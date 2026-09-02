import re

import os

from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from schemas import AuthRequest
import auth as auth_utils
from services import auth_service
import database as db_mod

router = APIRouter(prefix="/auth", tags=["auth"])

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _cookie_secure_flag() -> bool:
    return os.getenv("COOKIE_SECURE", "false").strip().lower() in ("1", "true", "yes", "on")


def _get_user_value(user, key, default=None):
    if user is None:
        return default

    if hasattr(user, "get"):
        try:
            return user.get(key, default)
        except TypeError:
            pass

    if hasattr(user, "__getitem__"):
        try:
            return user[key]
        except (KeyError, IndexError, TypeError):
            pass

    if hasattr(user, key):
        return getattr(user, key)

    if hasattr(user, "model_dump"):
        try:
            return user.model_dump().get(key, default)
        except Exception:
            pass

    return default


def _normalize_email(email):
    if not isinstance(email, str):
        return ""
    return email.strip().lower()


def _is_valid_email(email):
    return bool(EMAIL_PATTERN.match(email)) if isinstance(email, str) and email else False


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(request: AuthRequest):
    email = _normalize_email(request.email)
    password = request.password.strip() if isinstance(request.password, str) else ""

    if not email or not password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email và mật khẩu không được để trống")

    if not _is_valid_email(email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email không hợp lệ")

    existing_user = await db_mod.client.user.find_unique(where={"email": email})
    if existing_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email đã tồn tại")

    password_hash = auth_utils.hash_password(password)
    try:
        await db_mod.client.user.create(
            data={
                "email": email,
                "password_hash": password_hash,
            }
        )
    except Exception as exc:
        if getattr(exc, "code", None) == "P2002" or "Unique" in str(exc):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email đã tồn tại") from exc
        raise

    return {"success": True, "data": {"email": email}}


@router.post("/login")
async def login(request: AuthRequest, response: Response):
    email = _normalize_email(request.email)
    password = request.password.strip() if isinstance(request.password, str) else ""

    if not email or not password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email và mật khẩu không được để trống")

    user = await db_mod.client.user.find_unique(where={"email": email})
    password_hash = _get_user_value(user, "password_hash", "")
    if not user or not auth_utils.verify_password(password, password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email hoặc mật khẩu không đúng")

    # Create access token and a DB-backed refresh token (sent as HttpOnly cookie)
    access_token = auth_utils.create_access_token(email)
    refresh_token = await auth_service.create_refresh_token(email)

    # Cookie options: HttpOnly, Secure where appropriate, SameSite none to allow cross-site usage
    secure_flag = _cookie_secure_flag()
    max_age = int(os.getenv("REFRESH_TOKEN_EXPIRES_SECONDS", 30 * 24 * 3600))
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=secure_flag,
        samesite="none",
        max_age=max_age,
        path="/",
    )

    return {
        "success": True,
        "data": {
            "token": access_token,
            "user": {
                "email": _get_user_value(user, "email", ""),
                "name": _get_user_value(user, "name") or "",
                "role": _get_user_value(user, "role", "user"),
            },
        },
    }



@router.post("/refresh")
async def refresh(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    rt = await auth_service.verify_refresh_token(token)

    user_email = _get_user_value(rt, "userEmail") or _get_user_value(rt, "user_email")
    if not user_email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    # Rotate refresh token: revoke old and issue new
    new_refresh = await auth_service.rotate_refresh_token(token, user_email)
    secure_flag = _cookie_secure_flag()
    max_age = int(os.getenv("REFRESH_TOKEN_EXPIRES_SECONDS", 30 * 24 * 3600))
    response.set_cookie(
        key="refresh_token",
        value=new_refresh,
        httponly=True,
        secure=secure_flag,
        samesite="none",
        max_age=max_age,
        path="/",
    )

    access_token = auth_utils.create_access_token(user_email)
    user = await db_mod.client.user.find_unique(where={"email": user_email})

    return {
        "success": True,
        "data": {
            "token": access_token,
            "user": {
                "email": _get_user_value(user, "email", ""),
                "name": _get_user_value(user, "name") or "",
                "role": _get_user_value(user, "role", "user"),
            },
        },
    }


@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    if token:
        await auth_service.revoke_refresh_token(token)

    # Clear cookie
    response.set_cookie(key="refresh_token", value="", httponly=True, secure=_cookie_secure_flag(), samesite="none", max_age=0, path="/")
    return {"success": True}


@router.get("/me")
async def me(current_email: str = Depends(auth_utils.get_current_user_email)):
    user = await db_mod.client.user.find_unique(where={"email": current_email})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User không tồn tại")

    return {
        "success": True,
        "data": {
            "email": _get_user_value(user, "email", ""),
            "name": _get_user_value(user, "name") or "",
            "role": _get_user_value(user, "role", "user"),
        },
    }
