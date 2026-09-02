import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status

import database as db_mod

DEFAULT_EXPIRES_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRES_DAYS", "30"))


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def create_refresh_token(user_email: str, expires_days: Optional[int] = None) -> str:
    token = secrets.token_urlsafe(48)
    days = expires_days if expires_days is not None else DEFAULT_EXPIRES_DAYS
    expires_at = _now_utc() + timedelta(days=days)

    await db_mod.client.refreshtoken.create(
        data={
            "token": token,
            "userEmail": user_email,
            "expires_at": expires_at,
        }
    )

    return token


async def verify_refresh_token(token: Optional[str]):
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")

    rt = await db_mod.client.refreshtoken.find_unique(where={"token": token})
    if not rt:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token not found")

    if getattr(rt, "revoked", False):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked")

    expires_at = getattr(rt, "expires_at", None)
    if expires_at and expires_at < _now_utc():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    return rt


async def revoke_refresh_token(token: str):
    try:
        await db_mod.client.refreshtoken.update(where={"token": token}, data={"revoked": True})
    except Exception:
        # ignore if not found
        pass


async def rotate_refresh_token(old_token: Optional[str], user_email: str) -> str:
    if old_token:
        await revoke_refresh_token(old_token)
    new_token = await create_refresh_token(user_email)
    return new_token


async def revoke_all_refresh_tokens_for_user(user_email: str):
    await db_mod.client.refreshtoken.update_many(where={"userEmail": user_email}, data={"revoked": True})
