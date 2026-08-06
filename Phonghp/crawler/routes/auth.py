import re

from fastapi import APIRouter, Depends, HTTPException, status
from schemas import AuthRequest
import auth as auth_utils
import database as db_mod

router = APIRouter(prefix="/auth", tags=["auth"])

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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
async def login(request: AuthRequest):
    email = _normalize_email(request.email)
    password = request.password.strip() if isinstance(request.password, str) else ""

    if not email or not password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email và mật khẩu không được để trống")

    user = await db_mod.client.user.find_unique(where={"email": email})
    password_hash = _get_user_value(user, "password_hash", "")
    if not user or not auth_utils.verify_password(password, password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email hoặc mật khẩu không đúng")

    token = auth_utils.create_access_token(email)
    return {
        "success": True,
        "data": {
            "token": token,
            "user": {
                "email": _get_user_value(user, "email", ""),
                "name": _get_user_value(user, "name") or "",
            },
        },
    }


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
        },
    }
