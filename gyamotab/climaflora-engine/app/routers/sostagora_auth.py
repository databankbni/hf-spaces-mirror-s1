from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.config import Settings, get_settings
from app.services.supabase_billing import SupabaseBillingStore

router = APIRouter(prefix="/auth/sostagora", tags=["auth"])
SettingsDep = Annotated[Settings, Depends(get_settings)]


class SostagoraCodeRequest(BaseModel):
    code: str = Field(min_length=32, max_length=256)


class SostagoraIdentity(BaseModel):
    wordpress_user_id: int = Field(gt=0)
    email: str
    active: bool
    access_level: Literal["none", "sostagora", "sostagora_elite"]
    issued_at: int | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Invalid email")
        return normalized


class SostagoraRedirectResponse(BaseModel):
    url: str


async def _consume_code(payload: SostagoraCodeRequest, settings: Settings) -> SostagoraIdentity:
    url = settings.sostagora_wordpress_exchange_url.strip()
    if not url.startswith("https://"):
        raise HTTPException(503, "Sostagora authentication is not configured")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json={"code": payload.code})
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Sostagora authentication is unavailable") from exc
    if response.status_code in {400, 401, 403, 404, 410}:
        raise HTTPException(401, "Sostagora login code is invalid or expired")
    if response.status_code >= 400:
        raise HTTPException(503, "Sostagora authentication is unavailable")
    try:
        return SostagoraIdentity.model_validate(response.json())
    except (ValueError, TypeError) as exc:
        raise HTTPException(502, "Sostagora returned an invalid identity") from exc


def _grant_values(identity: SostagoraIdentity, user_id: str | None = None) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    values: dict[str, Any] = {
        "wordpress_user_id": identity.wordpress_user_id,
        "email_hash": hashlib.sha256(identity.email.encode("utf-8")).hexdigest(),
        "access_level": identity.access_level,
        "active": identity.active,
        "issued_at": (
            datetime.fromtimestamp(identity.issued_at, UTC).isoformat()
            if identity.issued_at
            else None
        ),
        "last_synced_at": now,
    }
    if user_id:
        values.update({"supabase_user_id": user_id, "linked_at": now})
    return values


async def _sync_identity(identity: SostagoraIdentity, store: SupabaseBillingStore) -> str | None:
    current = await store.sostagora_grant(identity.wordpress_user_id)
    user_id = str(current["supabase_user_id"]) if current and current.get("supabase_user_id") else None
    await store.upsert_sostagora_grant(_grant_values(identity, user_id))
    if user_id:
        await store.update_profile(
            user_id,
            {
                "sostagora_access": identity.active,
                "sostagora_wp_user_id": identity.wordpress_user_id,
                "sostagora_access_updated_at": datetime.now(UTC).isoformat(),
            },
        )
    return user_id


@router.post("/sync")
async def sync_sostagora_access(
    payload: SostagoraCodeRequest,
    settings: SettingsDep,
) -> dict[str, Any]:
    identity = await _consume_code(payload, settings)
    store = SupabaseBillingStore(settings)
    user_id = await _sync_identity(identity, store)
    return {"synced": True, "active": identity.active, "linked": bool(user_id)}


@router.post("/exchange", response_model=SostagoraRedirectResponse)
async def exchange_sostagora_login(
    payload: SostagoraCodeRequest,
    settings: SettingsDep,
) -> SostagoraRedirectResponse:
    identity = await _consume_code(payload, settings)
    if not identity.active:
        await _sync_identity(identity, SupabaseBillingStore(settings))
        raise HTTPException(403, "No active Sostagora access")

    store = SupabaseBillingStore(settings)
    user_id, action_link = await store.generate_magic_link(
        identity.email,
        settings.sostagora_redirect_url,
    )
    await store.update_profile(
        user_id,
        {
            "sostagora_access": True,
            "sostagora_wp_user_id": identity.wordpress_user_id,
            "sostagora_access_updated_at": datetime.now(UTC).isoformat(),
        },
    )
    await store.upsert_sostagora_grant(_grant_values(identity, user_id))
    return SostagoraRedirectResponse(url=action_link)
