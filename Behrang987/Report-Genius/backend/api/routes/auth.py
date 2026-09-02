"""Tenant registration and login."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from backend.api import security
from backend.api.deps import get_current_tenant

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    password: str = Field(default="", max_length=256)
    passphrase: str = Field(default="", max_length=256)

    @model_validator(mode="after")
    def _resolve_secret(self) -> Credentials:
        secret = (self.password or self.passphrase or "").strip()
        if len(secret) < 6:
            raise ValueError("password or passphrase must be at least 6 characters")
        object.__setattr__(self, "password", secret)
        return self


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_id: str = ""
    expires_at: int | None = None


class WhoAmIResponse(BaseModel):
    tenant_id: str


def _token_response(tenant_id: str) -> TokenResponse:
    import time

    from backend.config import settings

    expires_at = int(time.time()) + settings.jwt_expiry_minutes * 60
    return TokenResponse(
        access_token=security.create_token(tenant_id),
        tenant_id=tenant_id,
        expires_at=expires_at,
    )


@router.post(
    "/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED
)
def register(creds: Credentials) -> TokenResponse:
    if not security.register_user(creds.tenant_id, creds.password):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Tenant already exists"
        )
    from backend.storage.tenant_provision import provision_tenant_from_default

    provision_tenant_from_default(creds.tenant_id)
    return _token_response(creds.tenant_id)


@router.post("/login", response_model=TokenResponse)
def login(creds: Credentials) -> TokenResponse:
    if not security.authenticate(creds.tenant_id, creds.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    return _token_response(creds.tenant_id)


@router.get("/me", response_model=WhoAmIResponse)
def me(tenant_id: str = Depends(get_current_tenant)) -> WhoAmIResponse:
    return WhoAmIResponse(tenant_id=tenant_id)
