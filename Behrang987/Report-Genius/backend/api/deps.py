"""FastAPI dependencies: tenant authentication and admin gating."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from backend.api import security
from backend.config import settings


def get_current_tenant(authorization: str = Header(default="")) -> str:
    """Resolve the tenant id from a Bearer JWT."""
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = security.decode_token(token)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    tenant_id = payload.get("sub")
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing subject"
        )
    from backend.storage import tenant_store

    tenant_store.ensure_tenant_schema(tenant_id)
    return tenant_id


def get_internal_tenant(
    authorization: str = Header(default=""),
    x_service_token: str = Header(default="", alias="X-Service-Token"),
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
) -> str:
    """Resolve tenant for Node BFF / internal routes.

    Prefer ``X-Service-Token`` + ``X-Tenant-ID`` when ``internal_service_token``
    is configured. Otherwise fall back to tenant JWT (local/dev).
    """
    from backend.storage import tenant_store

    expected = (settings.internal_service_token or "").strip()
    if expected:
        if not x_service_token or x_service_token != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing X-Service-Token",
            )
        tenant_id = (x_tenant_id or "").strip()
        if not tenant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="X-Tenant-ID is required for internal calls",
            )
        tenant_store.ensure_tenant_schema(tenant_id)
        return tenant_id

    # Dev fallback: allow JWT when service token is not configured.
    return get_current_tenant(authorization=authorization)


def require_admin(
    tenant_id: str = Depends(get_current_tenant),
    x_admin_token: str = Header(default=""),
) -> str:
    """Require both a valid JWT and the configured admin token, with the master
    upload feature flag enabled."""
    if not settings.master_template_upload_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin master-template override is disabled (master_template_upload_enabled=false).",
        )
    if not settings.admin_token or x_admin_token != settings.admin_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin token"
        )
    return tenant_id
