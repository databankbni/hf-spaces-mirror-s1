"""
CustomerCore API — JWT Authentication & Tenant Extraction (Phase 10)

WHY JWT AND NOT SESSION TOKENS?
---------------------------------
CustomerCore is a B2B multi-tenant platform. Each API request must:
  1. Prove the caller is who they say they are (authentication)
  2. Identify which tenant the caller belongs to (authorization / data isolation)

JWT (JSON Web Tokens) are the industry standard for stateless API authentication because:
  - Stateless: The server doesn't need to query a database on every request — the tenant_id
    and role are encoded directly in the token payload and verified cryptographically.
  - Scalable: Any API pod can verify a JWT without shared session state.
  - Standard: Every language, framework, and API gateway understands JWTs.

TOKEN STRUCTURE:
  Header:  {"alg": "HS256", "typ": "JWT"}
  Payload: {"tenant_id": "acme-corp", "role": "support_agent", "exp": 1748000000}
  Signature: HMAC-SHA256(base64(header) + "." + base64(payload), SECRET_KEY)

SECURITY MODEL:
  - Tokens are signed with the LITELLM_MASTER_KEY (injected via Doppler)
  - Expiry is enforced — expired tokens are rejected
  - The tenant_id from the token is used for ALL data isolation decisions
    (ChromaDB collection, DuckDB WHERE clauses, Supabase RLS policies)
  - Never trust the tenant_id from the request body — only from the verified token

HOW IT INTEGRATES WITH LANGGRAPH:
  The tenant_id extracted here is injected into the AgentState at the start of every
  triage run. This ensures the RAG agent only retrieves from that tenant's ChromaDB
  collection, and the Graph-RAG engine only reads that tenant's Gold mart data.
"""

from __future__ import annotations

import os
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# ─── Bearer token extractor ───────────────────────────────────────────────────
# FastAPI's HTTPBearer scheme reads the Authorization: Bearer <token> header
# and extracts the raw token string. It raises 403 automatically if the header
# is missing or malformed.
bearer_scheme = HTTPBearer(
    scheme_name="Bearer JWT",
    description="JWT token with tenant_id and role claims. "
                "Format: Authorization: Bearer <token>"
)


def _get_secret_key() -> str:
    """
    Retrieve the JWT signing secret from the environment.

    In development: injected by Doppler via `doppler run -- uvicorn ...`
    In production: injected as a Kubernetes Secret or HF Space secret.

    We use LITELLM_MASTER_KEY as the signing key so that the same secret
    that controls LiteLLM access also signs our JWTs — one secret to manage.
    Alternatively a dedicated JWT_SECRET_KEY can be added to Doppler.
    """
    key = os.getenv("LITELLM_MASTER_KEY") or os.getenv("JWT_SECRET_KEY")
    if not key:
        import logging
        logging.getLogger(__name__).warning(
            "JWT signing key not found. Using dev placeholder signing key."
        )
        return "dev-secret-jwt-signing-key-placeholder-only"
    return key


class AuthenticatedTenant:
    """
    The authenticated caller's identity, extracted from a verified JWT.

    This object is injected into route handlers via FastAPI's Depends() system.
    Route handlers can trust that if this object exists, the caller has a valid,
    unexpired JWT with a verified tenant_id.
    """

    def __init__(self, tenant_id: str, role: str, claims: dict[str, Any]) -> None:
        self.tenant_id = tenant_id
        self.role = role
        self.claims = claims  # Full decoded payload for any additional fields

    def __repr__(self) -> str:
        return f"AuthenticatedTenant(tenant_id={self.tenant_id!r}, role={self.role!r})"


def verify_token(
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
) -> AuthenticatedTenant:
    """
    FastAPI dependency: verifies the JWT and returns the authenticated tenant.

    Usage in a route:
        @router.post("/triage")
        async def submit_ticket(
            body: TicketSubmitRequest,
            caller: AuthenticatedTenant = Depends(verify_token),
        ):
            tenant_id = caller.tenant_id  # Safe to use — cryptographically verified

    Raises:
        401 UNAUTHORIZED — if the token is missing, expired, or has an invalid signature
        403 FORBIDDEN    — if the token is valid but the role is not allowed for this endpoint
    """
    try:
        secret = _get_secret_key()
        payload: dict[str, Any] = jwt.decode(
            credentials.credentials,
            secret,
            algorithms=["HS256"],
            options={"verify_exp": True},  # Always enforce expiry
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired. Request a new token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    tenant_id: str | None = payload.get("tenant_id")
    role: str = payload.get("role", "support_agent")

    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload missing required 'tenant_id' claim.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return AuthenticatedTenant(tenant_id=tenant_id, role=role, claims=payload)


def require_role(*allowed_roles: str):
    """
    FastAPI dependency factory for role-based access control (RBAC).

    Usage:
        @router.post("/triage/{id}/resume")
        async def resume_hitl(
            caller: AuthenticatedTenant = Depends(require_role("manager", "admin")),
        ):
            ...  # Only managers and admins can resume HITL tickets

    Why RBAC matters in B2B:
        A support_agent should be able to SUBMIT tickets but not RESUME HITL reviews.
        A manager can review and override AI decisions.
        An admin has full access.
        These role boundaries prevent privilege escalation — a compromised support
        agent token cannot approve high-risk actions.
    """
    def _check(caller: AuthenticatedTenant = Depends(verify_token)) -> AuthenticatedTenant:
        if caller.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{caller.role}' is not authorized for this endpoint. "
                       f"Required: {allowed_roles}",
            )
        return caller
    return _check


def generate_dev_token(tenant_id: str, role: str = "support_agent") -> str:
    """
    Generate a development JWT for testing the API locally.

    WARNING: This uses the dev secret key. NEVER use in production.
    Production tokens must be issued by a proper auth service (Supabase Auth or similar).

    Usage:
        from src.api.auth import generate_dev_token
        token = generate_dev_token("acme-corp", role="manager")
        # Use in: Authorization: Bearer <token>
    """
    import time
    payload = {
        "tenant_id": tenant_id,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + 86_400,  # 24 hours
    }
    secret = _get_secret_key()
    return jwt.encode(payload, secret, algorithm="HS256")
